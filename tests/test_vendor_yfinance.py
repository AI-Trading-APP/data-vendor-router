"""Tests for the yfinance adapter (T9). All vendor SDK calls are stubbed."""
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# Skip the whole module if yfinance isn't importable
pytest.importorskip("yfinance")

from data_vendor_router.dto import FundamentalsSnapshot, NewsItem, OHLCBar
from data_vendor_router.exceptions import (
    VendorResponseInvalid,
    _NetworkError,
    _NotFoundError,
)
from data_vendor_router.vendors.yfinance import YFinanceAdapter


def _make_history_df():
    """Build a fake pandas DataFrame mimicking yfinance.history() output."""
    import pandas as pd
    idx = [pd.Timestamp("2026-04-01"), pd.Timestamp("2026-04-02")]
    return pd.DataFrame({
        "Open":   [142.50, 144.50],
        "High":   [145.20, 147.30],
        "Low":    [141.80, 143.90],
        "Close":  [144.50, 146.80],
        "Volume": [52_000_000, 48_000_000],
    }, index=idx)


def test_get_ohlcv_happy_path():
    adapter = YFinanceAdapter()
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = _make_history_df()
    with patch("data_vendor_router.vendors.yfinance.yf.Ticker", return_value=fake_ticker):
        bars = adapter.get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 5))
    assert len(bars) == 2
    assert all(isinstance(b, OHLCBar) for b in bars)
    assert bars[0].close == 144.50
    assert bars[1].volume == 48_000_000


def test_get_ohlcv_empty_history_raises_not_found():
    import pandas as pd
    adapter = YFinanceAdapter()
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = pd.DataFrame()
    with patch("data_vendor_router.vendors.yfinance.yf.Ticker", return_value=fake_ticker):
        with pytest.raises(_NotFoundError):
            adapter.get_ohlcv("NOTREAL", date(2026, 4, 1), date(2026, 4, 5))


def test_get_ohlcv_yfinance_raises_translates_to_network_error():
    adapter = YFinanceAdapter()
    fake_ticker = MagicMock()
    fake_ticker.history.side_effect = RuntimeError("connection reset")
    with patch("data_vendor_router.vendors.yfinance.yf.Ticker", return_value=fake_ticker):
        with pytest.raises(_NetworkError, match="connection reset"):
            adapter.get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 5))


def test_get_news_happy_path():
    adapter = YFinanceAdapter()
    fake_ticker = MagicMock()
    fake_ticker.news = [
        {
            "title": "NVDA Q1 datacenter +60% YoY",
            "link": "https://example.com/nvda-q1",
            "providerPublishTime": int(datetime(2026, 5, 1, 14, 0, tzinfo=timezone.utc).timestamp()),
            "publisher": "Reuters",
            "summary": "Strong quarter",
            "relatedTickers": ["NVDA", "AMD"],
        },
    ]
    with patch("data_vendor_router.vendors.yfinance.yf.Ticker", return_value=fake_ticker):
        items = adapter.get_news("NVDA", lookback_days=7, top_n=10)
    assert len(items) == 1
    assert items[0].title == "NVDA Q1 datacenter +60% YoY"
    assert items[0].source == "Reuters"
    assert items[0].tickers == ("NVDA", "AMD")


def test_get_news_empty_returns_empty_list():
    adapter = YFinanceAdapter()
    fake_ticker = MagicMock()
    fake_ticker.news = []
    with patch("data_vendor_router.vendors.yfinance.yf.Ticker", return_value=fake_ticker):
        items = adapter.get_news("OBSCURE", lookback_days=7, top_n=10)
    assert items == []


def test_get_news_top_n_limits():
    adapter = YFinanceAdapter()
    fake_ticker = MagicMock()
    fake_ticker.news = [
        {"title": f"T{i}", "link": f"https://example.com/{i}",
         "providerPublishTime": int(datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp()),
         "publisher": "X", "relatedTickers": ["NVDA"]}
        for i in range(10)
    ]
    with patch("data_vendor_router.vendors.yfinance.yf.Ticker", return_value=fake_ticker):
        items = adapter.get_news("NVDA", lookback_days=7, top_n=3)
    assert len(items) == 3
    assert items[0].title == "T0"


def test_get_fundamentals_happy_path():
    adapter = YFinanceAdapter()
    fake_ticker = MagicMock()
    fake_ticker.info = {
        "symbol": "NVDA",
        "marketCap": 2_800_000_000_000,
        "trailingPE": 45.0,
        "dividendYield": 0.0001,
        "profitMargins": 0.30,
        "totalRevenue": 60_000_000_000,
        "sector": "Technology",
        "sharesOutstanding": 24_500_000_000,
        "beta": 1.5,
        "fiftyTwoWeekHigh": 199.0,
        "fiftyTwoWeekLow": 142.0,
    }
    with patch("data_vendor_router.vendors.yfinance.yf.Ticker", return_value=fake_ticker):
        snap = adapter.get_fundamentals("NVDA")
    assert isinstance(snap, FundamentalsSnapshot)
    assert snap.ticker == "NVDA"
    assert snap.market_cap == 2_800_000_000_000
    assert snap.pe == 45.0
    assert snap.sector == "Technology"
    assert snap.extras["yfinance"]["beta"] == 1.5


def test_get_fundamentals_no_symbol_raises_not_found():
    adapter = YFinanceAdapter()
    fake_ticker = MagicMock()
    fake_ticker.info = {}  # missing 'symbol'
    with patch("data_vendor_router.vendors.yfinance.yf.Ticker", return_value=fake_ticker):
        with pytest.raises(_NotFoundError):
            adapter.get_fundamentals("NOTREAL")


def test_adapter_registered_at_import():
    """Importing the module should auto-register it."""
    from data_vendor_router import vendors
    # Force fresh import + registration
    vendors.reset_registry()
    import importlib

    import data_vendor_router.vendors.yfinance
    importlib.reload(data_vendor_router.vendors.yfinance)
    assert vendors.is_registered("yfinance")
