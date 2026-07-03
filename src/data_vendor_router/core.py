"""Core router algorithm + 3 public functions. REQ-DVR-001 + REQ-DVR-002 + REQ-DVR-003.

The router is a try-vendor-fallback loop with per-vendor circuit breakers,
failure classification, OTel + Prometheus instrumentation, and DTO validation.

Cache integration (P1 — data-layer-dedup): a read-through shared Redis cache
(``DVRCache``) is injected at the top of ``_route`` when ``DVR_CACHE_ENABLED=true``.
When the flag is off the code path is byte-equivalent to the pre-feature version
(NFR-5, AC-9.1): no Redis client is constructed, no counters incremented.
"""
from __future__ import annotations

import time
from datetime import date
from typing import Any, Callable

from . import breakers, observability, vendors
from .cache import get_dvr_cache
from .chains import get_configured_chain
from .exceptions import (
    AllVendorsFailed,
    BadRequest,
    NoVendorsConfigured,
    NotFound,
    VendorResponseInvalid,
    _BadRequestError,
    _NetworkError,
    _NotFoundError,
    _RateLimitError,
    _ServerError,
)
from .retry import with_retry


def _route(
    *,
    category: str,
    method_name: str,
    ticker: str,
    provider_chain: list[str] | None,
    method_args: tuple,
    method_kwargs: dict,
) -> Any:
    """Generic router loop. Tries each vendor in the chain; falls back on transient
    failures; raises immediately on terminal failures (404 / 4xx-other / malformed).
    """
    chain = provider_chain if provider_chain is not None else get_configured_chain(category)
    if not chain:
        raise NoVendorsConfigured(f"No vendors configured for category {category!r}")

    # MIN-3: validate provider_chain entries against registered adapters
    if provider_chain is not None:
        unknown = [v for v in provider_chain if not vendors.is_registered(v)]
        if unknown:
            raise ValueError(
                f"Unknown vendor(s) in provider_chain: {unknown}; "
                f"registered: {vendors.list_registered()}"
            )

    attempts: list[tuple[str, str]] = []
    previous_failed_vendor: str | None = None
    started = time.perf_counter()

    # ----- Cache args: the parts of the cache key that vary per method call -----
    # ohlcv:        (start_iso, end_iso)
    # news:         (lookback_days, top_n)
    # fundamentals: () — ticker alone is sufficient
    def _cache_parts_for(cat: str, kwargs: dict) -> tuple:
        if cat == "ohlcv":
            # method_args = (ticker, start, end); start/end are positional
            return (str(method_args[1]), str(method_args[2]))
        if cat == "news":
            # Derive from the actual kwargs passed — no hard-coded defaults here
            # so that a caller-supplied non-default value is reflected in the key.
            return (kwargs.get("lookback_days"), kwargs.get("top_n"))
        return ()

    with observability.root_span(category, ticker) as root_record:
        # root_span initialises cache_hit=None already; the redundant assignment
        # below was a nit found in review — removed.

        # ---- P1 Read-through cache check (data-layer-dedup, DLD-2) ----
        _cache = get_dvr_cache()
        _active_cache_key: str | None = None

        if _cache is not None:
            from .cache import _cache_key as _build_key
            _active_cache_key = _build_key(category, ticker, *_cache_parts_for(category, method_kwargs))

            cached_result = _cache.get(_active_cache_key, category)
            if cached_result is not None:
                root_record["cache_hit"] = True
                observability.cache_hits_total.labels(category=category).inc()
                root_record["total_latency_ms"] = int((time.perf_counter() - started) * 1000)
                return cached_result
            # Miss — record and fall through to vendor chain
            observability.cache_misses_total.labels(category=category).inc()

        for vendor_name in chain:
            # SKIP open breakers (REQ-DVR-004). Skips are NOT counted as fallbacks
            # in user-facing metrics, only in the trace.
            if breakers.is_open(vendor_name):
                root_record["skip_count"] += 1
                attempts.append((vendor_name, "circuit_breaker_open"))
                continue

            with observability.vendor_span(vendor_name, category) as v_record:
                v_started = time.perf_counter()
                try:
                    breaker = breakers.get_breaker(vendor_name)
                    adapter = vendors.get_adapter(vendor_name)
                    method = getattr(adapter, method_name)
                    # Retry happens INSIDE the breaker call — 1 retry = 1 breaker event (CTO M4)
                    wrapped = with_retry(vendor_name)(method)
                    result = breaker.call(wrapped, *method_args, **method_kwargs)
                except _RateLimitError:
                    v_record["outcome"] = "rate_limit"
                    v_record["latency_ms"] = int((time.perf_counter() - v_started) * 1000)
                    attempts.append((vendor_name, "rate_limit"))
                    if previous_failed_vendor is not None or len(attempts) > 1:
                        observability.record_fallback(category, previous_failed_vendor or vendor_name, vendor_name, "rate_limit")
                    previous_failed_vendor = vendor_name
                    root_record["fallback_count"] += 1
                    continue
                except _ServerError:
                    v_record["outcome"] = "server_error"
                    v_record["latency_ms"] = int((time.perf_counter() - v_started) * 1000)
                    attempts.append((vendor_name, "server_error"))
                    previous_failed_vendor = vendor_name
                    root_record["fallback_count"] += 1
                    continue
                except _NetworkError:
                    v_record["outcome"] = "timeout"
                    v_record["latency_ms"] = int((time.perf_counter() - v_started) * 1000)
                    attempts.append((vendor_name, "timeout"))
                    previous_failed_vendor = vendor_name
                    root_record["fallback_count"] += 1
                    continue
                except _NotFoundError:
                    v_record["outcome"] = "not_found"
                    v_record["latency_ms"] = int((time.perf_counter() - v_started) * 1000)
                    raise NotFound(
                        f"Vendor {vendor_name} returned 404 for {ticker!r}",
                        ticker=ticker,
                        attempted_vendor=vendor_name,
                    )
                except _BadRequestError as e:
                    v_record["outcome"] = "bad_request"
                    v_record["latency_ms"] = int((time.perf_counter() - v_started) * 1000)
                    raise BadRequest(
                        f"Vendor {vendor_name} rejected request: {e}",
                        attempted_vendor=vendor_name,
                        status_code=e.status_code,
                    )
                except VendorResponseInvalid:
                    v_record["outcome"] = "dto_validation_failed"
                    v_record["latency_ms"] = int((time.perf_counter() - v_started) * 1000)
                    raise

                v_record["outcome"] = "success"
                v_record["latency_ms"] = int((time.perf_counter() - v_started) * 1000)
                root_record["final_vendor"] = vendor_name
                root_record["total_latency_ms"] = int((time.perf_counter() - started) * 1000)

                # ---- P1 Cache write-through (DLD-2) ----
                if _cache is not None and _active_cache_key is not None:
                    _cache.set(
                        _active_cache_key,
                        result,
                        _cache.ttl_for(category),
                        category,
                    )
                    root_record["cache_hit"] = False

                return result

        # Exhausted the chain without success
        primary_reason = attempts[0][1] if attempts else "unknown"
        if all(r == "circuit_breaker_open" for _, r in attempts):
            primary_reason = "circuit_breaker_open"
        raise AllVendorsFailed(
            f"All vendors failed for {category} {ticker!r}: {attempts}",
            attempts=attempts,
            primary_reason=primary_reason,
        )


# ---------- Public API ----------


def get_ohlcv(
    ticker: str,
    start: date,
    end: date,
    *,
    provider_chain: list[str] | None = None,
) -> list:
    """Fetch OHLCV bars for a ticker over a date range. REQ-DVR-001."""
    return _route(
        category="ohlcv",
        method_name="get_ohlcv",
        ticker=ticker,
        provider_chain=provider_chain,
        method_args=(ticker, start, end),
        method_kwargs={},
    )


def get_news(
    ticker: str,
    *,
    lookback_days: int = 7,
    top_n: int = 10,
    provider_chain: list[str] | None = None,
) -> list:
    """Fetch top-N news items for a ticker over the lookback window. REQ-DVR-001."""
    return _route(
        category="news",
        method_name="get_news",
        ticker=ticker,
        provider_chain=provider_chain,
        method_args=(ticker,),
        method_kwargs={"lookback_days": lookback_days, "top_n": top_n},
    )


def get_fundamentals(
    ticker: str,
    *,
    provider_chain: list[str] | None = None,
):
    """Fetch a fundamentals snapshot for a ticker. REQ-DVR-001."""
    return _route(
        category="fundamentals",
        method_name="get_fundamentals",
        ticker=ticker,
        provider_chain=provider_chain,
        method_args=(ticker,),
        method_kwargs={},
    )
