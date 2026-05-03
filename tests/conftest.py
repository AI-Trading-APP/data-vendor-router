"""Shared fixtures + stub adapters for the data-vendor-router test suite."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# Make the package importable
SRC_DIR = Path(__file__).parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest

from data_vendor_router import breakers, vendors
from data_vendor_router.dto import FundamentalsSnapshot, NewsItem, OHLCBar
from data_vendor_router.exceptions import (
    _BadRequestError,
    _NetworkError,
    _NotFoundError,
    _RateLimitError,
    _ServerError,
    VendorResponseInvalid,
)


# ---------- Reset state between tests ----------


@pytest.fixture(autouse=True)
def reset_state():
    """Each test starts with a clean adapter registry + closed breakers."""
    breakers.reset_all()
    vendors.reset_registry()
    yield
    breakers.reset_all()
    vendors.reset_registry()


# ---------- Stub adapter ----------


class StubAdapter:
    """Configurable stub vendor adapter — used in unit tests instead of real HTTP calls.

    Each method can be programmed to:
      - return a fixed value
      - raise a specific internal exception
    via the `program(...)` helper.
    """

    def __init__(self, name: str):
        self.name = name
        self._programs: dict[str, Callable[..., Any]] = {}
        self.call_log: list[tuple[str, tuple, dict]] = []

    def program(self, method_name: str, behavior: Callable[..., Any]) -> None:
        """`behavior` is a callable that runs (raise / return) when the method is invoked."""
        self._programs[method_name] = behavior

    def __getattr__(self, method_name: str):
        # Only respond to the provider methods
        if method_name in {"get_ohlcv", "get_news", "get_fundamentals"}:
            def _method(*args, **kwargs):
                self.call_log.append((method_name, args, kwargs))
                if method_name not in self._programs:
                    raise AttributeError(
                        f"StubAdapter({self.name!r}) has no program for {method_name!r}"
                    )
                return self._programs[method_name](*args, **kwargs)
            return _method
        raise AttributeError(method_name)


@pytest.fixture
def make_stub() -> Callable[[str], StubAdapter]:
    """Factory: `stub = make_stub("yfinance")` returns a fresh, registered StubAdapter."""
    def _factory(name: str) -> StubAdapter:
        adapter = StubAdapter(name)
        vendors.register_adapter(name, adapter)
        return adapter
    return _factory


# ---------- Helpers to convert behaviors ----------


def returns(value):
    """Stub program: just return this value when invoked."""
    return lambda *a, **kw: value


def raises(exc):
    """Stub program: raise this exception when invoked."""
    def _raise(*a, **kw):
        raise exc
    return _raise


# ---------- DTO sample builders ----------


def sample_ohlc_bars(n: int = 1) -> list[OHLCBar]:
    """Build n OHLC bars. Day cycles within April to avoid month-overflow when n > 30."""
    return [
        OHLCBar(
            date=date(2026, 4, (i % 30) + 1),
            open=100 + i, high=105 + i, low=98 + i, close=102 + i, volume=1_000_000,
        )
        for i in range(n)
    ]


def sample_news_items(n: int = 1) -> list[NewsItem]:
    return [
        NewsItem(
            title=f"News {i}",
            url=f"https://example.com/{i}",
            published_at=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
            source="StubFeed",
            sentiment=0.5,
            tickers=("NVDA",),
        )
        for i in range(n)
    ]


def sample_fundamentals_snapshot(ticker: str = "NVDA") -> FundamentalsSnapshot:
    return FundamentalsSnapshot(
        ticker=ticker,
        market_cap=2_800_000_000_000.0,
        pe=45.0,
        sector="Technology",
        extras={"yfinance": {"shares_outstanding": 24_500_000_000}},
    )


# ---------- Golden data loader (optional — golden-data lives in AITradingAPP repo) ----------


GOLDEN_PATH = Path(__file__).parent.parent.parent.parent / "Personal_Projects" / "AI-Trading-APP" / "AITradingAPP" / "specs" / "data-vendor-router" / "golden-data.json"


@pytest.fixture(scope="session")
def golden_data() -> Optional[dict]:
    """Load the golden-data.json from the AITradingAPP repo if available."""
    if GOLDEN_PATH.exists():
        return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    return None
