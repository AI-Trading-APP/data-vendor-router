"""OpenBB Platform adapter — OHLCV + Fundamentals (P1), Macro + News (P2).

Free MIT SDK. OHLCV via FMP key we hold; fundamentals via SEC EDGAR (free) then FMP.
openbb-polygon is NOT used here — the DVR native polygon.py adapter (chain slot 1) already
covers Polygon directly and is proven stable. openbb-polygon was removed because Polygon.io was
acquired/rebranded as Massive and the openbb-polygon extension is unmaintained against the
current Polygon API.
Credentials injected from env (NO ~/.openbb_platform/user_settings.json — VPS headless).
`obb` is lazy-imported inside methods (NFR-1 cold-start). Module import is guarded so
register_all_available() silent-skips when the [openbb] extras are absent (NFR-4 / US-4).
"""
from __future__ import annotations

import os
from datetime import date

from ..dto import FundamentalsSnapshot, OHLCBar
from ..exceptions import (
    VendorResponseInvalid,
    _NetworkError,
    _NotFoundError,
    _RateLimitError,
    _ServerError,
)
from . import register_adapter

VENDOR = "openbb"
_EXPECTED_OHLC_COLS = {"open", "high", "low", "close", "volume"}  # schema canary (NFR-3)

# Module-level guard: if openbb-core is NOT installed, raise ImportError so
# register_all_available() skips this module silently (matches existing pattern).
try:
    import openbb  # noqa: F401  (presence probe only; real obj lazy-imported per call)
except ImportError:  # pragma: no cover
    raise  # re-raise -> register_all_available() catches ImportError and skips


class OpenBBAdapter:
    name = VENDOR

    def __init__(self) -> None:
        # Inject creds ONCE at init (thread-safe re: EC-3 — never mutated per call).
        from openbb import obb
        for cred_attr, env_var in (
            ("fmp_api_key",     "FMP_API_KEY"),
            ("polygon_api_key", "POLYGON_API_KEY"),
            ("fred_api_key",    "FRED_API_KEY"),
        ):
            val = os.getenv(env_var)
            if val:  # AC-2.2: unset env -> no error, skip
                setattr(obb.user.credentials, cred_attr, val)

    def get_ohlcv(self, ticker: str, start: date, end: date) -> list[OHLCBar]:
        from openbb import obb
        # Use FMP only — openbb-polygon is dropped (Polygon rebranded to Massive;
        # openbb-polygon extension unmaintained). DVR native polygon.py covers Polygon at slot 1.
        try:
            obbject = obb.equity.price.historical(
                symbol=ticker,          # EC-6: pass as-is, no reformat
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                provider="fmp",
            )
            return self._obbject_to_bars(obbject, ticker)
        except (_NotFoundError, VendorResponseInvalid):
            raise  # terminal
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc, ticker) from exc

    def _obbject_to_bars(self, obbject, ticker: str) -> list[OHLCBar]:
        try:
            df = obbject.to_df()
        except Exception as exc:  # noqa: BLE001
            raise _ServerError(f"openbb to_df failed: {exc}") from exc
        if df is None or df.empty:
            raise _NotFoundError(f"openbb returned no OHLCV for {ticker}")  # AC-1.7 / EC-1
        cols = {c.lower() for c in df.columns}
        if not _EXPECTED_OHLC_COLS.issubset(cols):  # AC-1.8 / NFR-3 / EC-5 schema canary
            raise VendorResponseInvalid(
                f"openbb OHLC schema drift: have {sorted(cols)}",
                vendor=VENDOR,
                raw_response=sorted(cols),
                validation_errors=[{"msg": "missing OHLC columns"}],
            )
        df = df.rename(columns=str.lower)
        bars: list[OHLCBar] = []
        for idx, row in df.iterrows():  # idx = DatetimeIndex -> date
            try:
                bar_date = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
                bars.append(OHLCBar(
                    date=bar_date,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row["volume"]),
                ))
            except Exception as exc:  # noqa: BLE001
                raise VendorResponseInvalid(
                    f"openbb bar validation failed: {exc}",
                    vendor=VENDOR,
                    raw_response=str(row)[:500],
                    validation_errors=[{"msg": str(exc)}],
                ) from exc
        return bars

    def get_fundamentals(self, ticker: str) -> FundamentalsSnapshot:
        from openbb import obb
        last_exc = None
        for provider in ("sec", "fmp"):  # spec: sec(free) then fmp
            # INFO: "sec" is NOT a valid provider for obb.equity.fundamental.metrics;
            # the loop raises on it and falls through to "fmp" on every call.
            # openbb-sec covers filings (obb.equity.fundamental.income etc.), not metrics.
            # Pre-existing behavior: the exception is caught below and last_exc set to fmp.
            # No behavior change here — comment only (comment; no fix in this PR scope).
            try:
                obbject = obb.equity.fundamental.metrics(symbol=ticker, provider=provider)
                df = obbject.to_df()
                if df is None or df.empty:
                    raise _NotFoundError(f"openbb no fundamentals for {ticker}")  # AC-5.2/EC-7
                rec = df.iloc[0].to_dict()
                return FundamentalsSnapshot(
                    ticker=ticker.upper(),
                    market_cap=rec.get("market_cap"),
                    pe=rec.get("pe_ratio") or rec.get("pe"),
                    dividend_yield=rec.get("dividend_yield"),
                    profit_margin=rec.get("net_profit_margin") or rec.get("profit_margin"),
                    revenue_ttm=rec.get("revenue"),
                    sector=rec.get("sector"),
                    extras={"openbb": rec},  # AC-5.3: extras absorb vendor fields
                )
            except (_NotFoundError, VendorResponseInvalid):
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = self._translate(exc, ticker)
                continue
        raise last_exc or _NotFoundError(f"openbb fundamentals unavailable for {ticker}")

    @staticmethod
    def _translate(exc: Exception, ticker: str) -> Exception:
        name = type(exc).__name__.lower()
        msg = str(exc).lower()
        if "429" in msg or ("rate" in msg and "limit" in msg) or "ratelimit" in name:
            return _RateLimitError(f"openbb rate-limited: {exc}")
        if any(k in msg for k in ("404", "not found", "no data", "empty")):
            return _NotFoundError(f"openbb not found for {ticker}: {exc}")
        if any(k in msg for k in ("timeout", "connection", "network", "ssl", "dns")) \
                or name in ("connecterror", "timeout", "connectionerror", "readtimeout"):
            return _NetworkError(f"openbb network error: {exc}")
        if "500" in msg or "502" in msg or "503" in msg or "server" in msg:
            return _ServerError(f"openbb server error: {exc}")
        return _NetworkError(f"openbb transient error: {exc}")  # default → fallback-safe


import logging  # noqa: E402
register_adapter(VENDOR, OpenBBAdapter())
logging.getLogger(__name__).info("openbb adapter registered")  # AC-4.2
