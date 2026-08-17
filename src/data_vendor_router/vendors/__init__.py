"""Adapter Protocol definitions + registry. REQ-DVR-006.

Each real vendor adapter (in PR-B) registers itself via `register_adapter`
at module import time. Tests use stub adapters via the same registry.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Protocol, runtime_checkable

from ..dto import FundamentalsSnapshot, NewsItem, OHLCBar, Quote


@runtime_checkable
class OHLCVProvider(Protocol):
    name: str

    def get_ohlcv(self, ticker: str, start: date, end: date) -> list[OHLCBar]: ...


@runtime_checkable
class NewsProvider(Protocol):
    name: str

    def get_news(self, ticker: str, lookback_days: int, top_n: int) -> list[NewsItem]: ...


@runtime_checkable
class FundamentalsProvider(Protocol):
    name: str

    def get_fundamentals(self, ticker: str) -> FundamentalsSnapshot: ...


@runtime_checkable
class QuoteProvider(Protocol):
    name: str

    def get_quote(self, ticker: str) -> Quote | None: ...


# ---------- Registry ----------

_ADAPTERS: dict[str, Any] = {}

# Quote is a separate, single-slot seam (WL-004-DVR-1) — MVP $0 default has no
# quote vendor configured (vendor-gated, deferred), so there is no chain to
# fall back through yet, unlike the OHLCV/news/fundamentals categories above.
_QUOTE_PROVIDERS: dict[str, Any] = {}


def register_quote_provider(name: str, provider: Any) -> None:
    """Register a quote provider under its canonical name."""
    _QUOTE_PROVIDERS[name] = provider


def get_quote_provider(name: str) -> Any:
    """Return the registered quote provider for `name`, or raise ValueError."""
    if name not in _QUOTE_PROVIDERS:
        raise ValueError(
            f"Unknown quote provider: {name!r}; registered: {sorted(_QUOTE_PROVIDERS)}"
        )
    return _QUOTE_PROVIDERS[name]


def is_quote_registered(name: str) -> bool:
    return name in _QUOTE_PROVIDERS


def list_registered_quote_providers() -> list[str]:
    return sorted(_QUOTE_PROVIDERS)


def register_adapter(name: str, adapter: Any) -> None:
    """Register a vendor adapter under its canonical name."""
    _ADAPTERS[name] = adapter


def get_adapter(name: str) -> Any:
    """Return the registered adapter for `name`, or raise ValueError."""
    if name not in _ADAPTERS:
        raise ValueError(
            f"Unknown vendor: {name!r}; registered: {sorted(_ADAPTERS)}"
        )
    return _ADAPTERS[name]


def is_registered(name: str) -> bool:
    return name in _ADAPTERS


def reset_registry() -> None:
    """Test helper — clear all registered adapters (incl. quote providers)."""
    _ADAPTERS.clear()
    _QUOTE_PROVIDERS.clear()


def list_registered() -> list[str]:
    return sorted(_ADAPTERS)


# ---------- Auto-registration of all built-in adapters ----------

_BUILTIN_ADAPTER_MODULES = (
    "yfinance",
    "alpaca",
    "benzinga",
    "polygon",
    "alpha_vantage",
    "newsapi",
    "tiingo",
    "openbb",
)


def register_all_available() -> list[str]:
    """Attempt to import every built-in adapter module. Silently skip ones whose
    vendor SDK is not installed. Returns the list of vendor names successfully
    registered.

    Called automatically on `import data_vendor_router`. Consumers that want
    to opt out can clear the registry via `reset_registry()` after import,
    or install the package without the [vendors] extras.
    """
    registered = []
    for module_name in _BUILTIN_ADAPTER_MODULES:
        try:
            __import__(f"data_vendor_router.vendors.{module_name}")
            registered.append(module_name)
        except ImportError:
            pass  # vendor SDK / dependency missing; skip silently
    return registered
