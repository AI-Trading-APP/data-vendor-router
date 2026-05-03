"""Adapter Protocol definitions + registry. REQ-DVR-006.

Each real vendor adapter (in PR-B) registers itself via `register_adapter`
at module import time. Tests use stub adapters via the same registry.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Protocol, runtime_checkable

from ..dto import FundamentalsSnapshot, NewsItem, OHLCBar


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


# ---------- Registry ----------

_ADAPTERS: dict[str, Any] = {}


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
    """Test helper — clear all registered adapters."""
    _ADAPTERS.clear()


def list_registered() -> list[str]:
    return sorted(_ADAPTERS)
