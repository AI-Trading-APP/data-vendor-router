"""Tests for the alpha_vantage adapter (T13). Stubs httpx.Client.get."""
from unittest.mock import MagicMock, patch

import httpx
import pytest

from data_vendor_router.dto import FundamentalsSnapshot, NewsItem
from data_vendor_router.exceptions import (
    _BadRequestError,
    _NetworkError,
    _NotFoundError,
    _RateLimitError,
    _ServerError,
)
from data_vendor_router.vendors.alpha_vantage import AlphaVantageAdapter


def _make_response(status_code: int, json_payload=None, text=""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json = lambda: json_payload if json_payload is not None else {}
    resp.text = text
    return resp


def _patched_client_returns(response):
    return patch.object(httpx.Client, "get", return_value=response)


# ============== get_news ==============


def test_get_news_happy_path():
    payload = {
        "feed": [
            {
                "title": "AAPL WWDC keynote previewed",
                "url": "https://example.com/wwdc",
                "time_published": "20260502T140000",
                "source": "TechCrunch",
                "summary": "Big stuff",
                "ticker_sentiment": [
                    {"ticker": "AAPL", "ticker_sentiment_score": 0.42},
                    {"ticker": "GOOGL", "ticker_sentiment_score": 0.10},
                ],
            },
        ],
    }
    adapter = AlphaVantageAdapter()
    with _patched_client_returns(_make_response(200, payload)):
        items = adapter.get_news("AAPL", lookback_days=7, top_n=5)
    assert len(items) == 1
    assert isinstance(items[0], NewsItem)
    assert items[0].title == "AAPL WWDC keynote previewed"
    assert items[0].source == "TechCrunch"
    assert items[0].sentiment == 0.42
    assert "AAPL" in items[0].tickers


def test_get_news_empty_feed_returns_empty():
    adapter = AlphaVantageAdapter()
    with _patched_client_returns(_make_response(200, {"feed": []})):
        items = adapter.get_news("OBSCURE", lookback_days=7, top_n=5)
    assert items == []


def test_get_news_soft_rate_limit_via_note_field():
    """Alpha Vantage signals quota via HTTP-200 with 'Note' key — translate to _RateLimitError."""
    adapter = AlphaVantageAdapter()
    payload = {"Note": "Thank you for using Alpha Vantage! Our standard API call frequency is 5 calls per minute and 500 calls per day."}
    with _patched_client_returns(_make_response(200, payload)):
        with pytest.raises(_RateLimitError, match="Thank you"):
            adapter.get_news("NVDA", lookback_days=7, top_n=5)


def test_get_news_soft_rate_limit_via_information_field():
    """Newer AV responses use 'Information' field for rate-limit signals."""
    adapter = AlphaVantageAdapter()
    payload = {"Information": "We have detected your API key has been used 25 times today..."}
    with _patched_client_returns(_make_response(200, payload)):
        with pytest.raises(_RateLimitError, match="25 times today"):
            adapter.get_news("NVDA", lookback_days=7, top_n=5)


def test_get_news_429_status():
    adapter = AlphaVantageAdapter()
    with _patched_client_returns(_make_response(429, {})):
        with pytest.raises(_RateLimitError):
            adapter.get_news("NVDA", lookback_days=7, top_n=5)


def test_get_news_503():
    adapter = AlphaVantageAdapter()
    with _patched_client_returns(_make_response(503, {})):
        with pytest.raises(_ServerError):
            adapter.get_news("NVDA", lookback_days=7, top_n=5)


def test_get_news_network_error():
    adapter = AlphaVantageAdapter()
    with patch.object(httpx.Client, "get", side_effect=httpx.ConnectError("dns")):
        with pytest.raises(_NetworkError):
            adapter.get_news("NVDA", lookback_days=7, top_n=5)


# ============== get_fundamentals ==============


def test_get_fundamentals_happy_path():
    payload = {
        "Symbol": "JPM",
        "MarketCapitalization": "565000000000",
        "PERatio": "11.5",
        "DividendYield": "0.025",
        "ProfitMargin": "0.332",
        "RevenueTTM": "150000000000",
        "Sector": "FINANCE",
        "Industry": "Banks",
        "Exchange": "NYSE",
        "Country": "USA",
        "52WeekHigh": "210.50",
        "52WeekLow": "143.64",
    }
    adapter = AlphaVantageAdapter()
    with _patched_client_returns(_make_response(200, payload)):
        snap = adapter.get_fundamentals("JPM")
    assert isinstance(snap, FundamentalsSnapshot)
    assert snap.market_cap == 565_000_000_000
    assert snap.pe == 11.5
    assert snap.sector == "FINANCE"
    assert snap.extras["alpha_vantage"]["industry"] == "Banks"
    assert snap.extras["alpha_vantage"]["exchange"] == "NYSE"


def test_get_fundamentals_empty_payload_raises_not_found():
    adapter = AlphaVantageAdapter()
    with _patched_client_returns(_make_response(200, {})):
        with pytest.raises(_NotFoundError):
            adapter.get_fundamentals("NOTREAL")


def test_get_fundamentals_handles_none_strings():
    """AV returns 'None' / '-' for missing numeric fields — should become None, not crash."""
    payload = {
        "Symbol": "X", "MarketCapitalization": "None", "PERatio": "-",
        "DividendYield": None, "ProfitMargin": "0.10",
    }
    adapter = AlphaVantageAdapter()
    with _patched_client_returns(_make_response(200, payload)):
        snap = adapter.get_fundamentals("X")
    assert snap.market_cap is None
    assert snap.pe is None
    assert snap.dividend_yield is None
    assert snap.profit_margin == 0.10


def test_get_fundamentals_soft_rate_limit():
    payload = {"Note": "API call frequency limit reached"}
    adapter = AlphaVantageAdapter()
    with _patched_client_returns(_make_response(200, payload)):
        with pytest.raises(_RateLimitError):
            adapter.get_fundamentals("X")
