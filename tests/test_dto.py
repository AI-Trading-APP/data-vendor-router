from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from data_vendor_router.dto import FundamentalsSnapshot, NewsItem, OHLCBar


def test_ohlc_bar_happy():
    bar = OHLCBar(date=date(2026, 4, 1), open=100.0, high=105.0, low=98.0, close=102.0, volume=1_000_000)
    assert bar.open == 100.0


def test_ohlc_bar_negative_volume_fails():
    with pytest.raises(ValidationError):
        OHLCBar(date=date(2026, 4, 1), open=100.0, high=105.0, low=98.0, close=102.0, volume=-1)


def test_ohlc_bar_zero_open_fails():
    with pytest.raises(ValidationError):
        OHLCBar(date=date(2026, 4, 1), open=0.0, high=105.0, low=98.0, close=102.0, volume=0)


def test_ohlc_bar_is_frozen_and_hashable():
    bar = OHLCBar(date=date(2026, 4, 1), open=100.0, high=105.0, low=98.0, close=102.0, volume=1)
    with pytest.raises(ValidationError):
        bar.open = 999  # frozen
    assert hash(bar) is not None


def test_news_item_happy():
    item = NewsItem(
        title="T",
        url="https://example.com",
        published_at=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
        source="Test",
        sentiment=0.5,
        tickers=("NVDA",),
    )
    assert item.tickers == ("NVDA",)


def test_news_item_sentiment_out_of_range_fails():
    with pytest.raises(ValidationError):
        NewsItem(
            title="T", url="x", published_at=datetime.now(timezone.utc), source="S",
            sentiment=1.5,  # > 1.0
        )


def test_fundamentals_snapshot_happy():
    snap = FundamentalsSnapshot(
        ticker="NVDA", market_cap=2.8e12, pe=45.0, sector="Technology",
        extras={"yfinance": {"shares": 24.5e9}},
    )
    assert snap.ticker == "NVDA"
    assert snap.extras["yfinance"]["shares"] == 24.5e9


def test_fundamentals_snapshot_extras_namespaced_by_vendor():
    """CTO MIN-2: extras dict is keyed by vendor to avoid silent collision."""
    snap = FundamentalsSnapshot(
        ticker="X",
        extras={"yfinance": {"foo": 1}, "polygon": {"foo": 2}},
    )
    assert snap.extras["yfinance"]["foo"] == 1
    assert snap.extras["polygon"]["foo"] == 2


def test_fundamentals_snapshot_default_extras_is_empty_dict():
    snap = FundamentalsSnapshot(ticker="X")
    assert snap.extras == {}
