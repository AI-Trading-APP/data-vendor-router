"""Tests for the tiingo adapter (v0.1.2). Mirrors test_vendor_newsapi.py."""
from datetime import date
from unittest.mock import MagicMock, patch

import httpx
import pytest

from data_vendor_router.dto import NewsItem, OHLCBar
from data_vendor_router.exceptions import (
    VendorResponseInvalid,
    _BadRequestError,
    _NetworkError,
    _NotFoundError,
    _RateLimitError,
    _ServerError,
)
from data_vendor_router.vendors.tiingo import TiingoAdapter


def _make_response(status_code: int, json_payload=None, text=""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json = lambda: json_payload if json_payload is not None else {}
    resp.text = text
    return resp


def _patched_returns(response):
    return patch.object(httpx.Client, "get", return_value=response)


# ---------- News ----------

def test_get_news_happy_path():
    payload = [
        {
            "id": 1,
            "publishedDate": "2026-05-29T15:30:00.000Z",
            "title": "NVDA reports record Q1",
            "url": "https://example.com/nvda-q1",
            "source": "Reuters",
            "description": "Strong earnings",
            "tickers": ["nvda", "amd"],
        }
    ]
    adapter = TiingoAdapter()
    with _patched_returns(_make_response(200, payload)):
        items = adapter.get_news("NVDA", lookback_days=7, top_n=5)
    assert len(items) == 1
    assert isinstance(items[0], NewsItem)
    assert items[0].title == "NVDA reports record Q1"
    assert items[0].source == "Reuters"
    assert items[0].tickers == ("NVDA", "AMD")


def test_get_news_empty_articles_returns_empty():
    adapter = TiingoAdapter()
    with _patched_returns(_make_response(200, [])):
        items = adapter.get_news("OBSCURE", lookback_days=7, top_n=5)
    assert items == []


def test_get_news_429_raises_rate_limit():
    adapter = TiingoAdapter()
    with _patched_returns(_make_response(429)):
        with pytest.raises(_RateLimitError):
            adapter.get_news("NVDA", lookback_days=7, top_n=5)


def test_get_news_401_auth_failure():
    adapter = TiingoAdapter()
    with _patched_returns(_make_response(401)):
        with pytest.raises(_BadRequestError):
            adapter.get_news("NVDA", lookback_days=7, top_n=5)


def test_get_news_500_raises_server_error():
    adapter = TiingoAdapter()
    with _patched_returns(_make_response(500)):
        with pytest.raises(_ServerError):
            adapter.get_news("NVDA", lookback_days=7, top_n=5)


def test_get_news_network_error_translates():
    adapter = TiingoAdapter()
    with patch.object(httpx.Client, "get", side_effect=httpx.ConnectError("boom")):
        with pytest.raises(_NetworkError):
            adapter.get_news("NVDA", lookback_days=7, top_n=5)


def test_get_news_dict_response_treated_as_invalid():
    """Tiingo error path: returns {'detail': 'X'} instead of a list."""
    adapter = TiingoAdapter()
    with _patched_returns(_make_response(200, {"detail": "Bad ticker"})):
        with pytest.raises(VendorResponseInvalid):
            adapter.get_news("NVDA", lookback_days=7, top_n=5)


def test_get_news_top_n_limits():
    articles = [{
        "title": f"T{i}",
        "url": f"https://example.com/{i}",
        "publishedDate": "2026-05-01T14:00:00.000Z",
        "source": "Source",
        "tickers": ["nvda"],
    } for i in range(10)]
    adapter = TiingoAdapter()
    with _patched_returns(_make_response(200, articles)):
        items = adapter.get_news("NVDA", lookback_days=7, top_n=3)
    assert len(items) == 3
    assert items[0].title == "T0"


# ---------- OHLCV ----------

def test_get_ohlcv_happy_path():
    payload = [
        {
            "date": "2026-05-29T00:00:00.000Z",
            "open": 100.0, "high": 102.5, "low": 99.5, "close": 101.0, "volume": 1000000,
            "adjOpen": 100.0, "adjHigh": 102.5, "adjLow": 99.5, "adjClose": 101.0, "adjVolume": 1000000,
        },
        {
            "date": "2026-05-30T00:00:00.000Z",
            "open": 101.0, "high": 103.0, "low": 100.5, "close": 102.5, "volume": 1200000,
            "adjOpen": 101.0, "adjHigh": 103.0, "adjLow": 100.5, "adjClose": 102.5, "adjVolume": 1200000,
        },
    ]
    adapter = TiingoAdapter()
    with _patched_returns(_make_response(200, payload)):
        bars = adapter.get_ohlcv("AAPL", date(2026, 5, 29), date(2026, 5, 30))
    assert len(bars) == 2
    assert isinstance(bars[0], OHLCBar)
    assert bars[0].date == date(2026, 5, 29)
    assert bars[0].close == 101.0
    assert bars[1].volume == 1200000


def test_get_ohlcv_empty_response_raises_notfound():
    adapter = TiingoAdapter()
    with _patched_returns(_make_response(200, [])):
        with pytest.raises(_NotFoundError):
            adapter.get_ohlcv("OBSCURE", date(2026, 5, 1), date(2026, 5, 30))


def test_get_ohlcv_dict_response_raises_notfound():
    """Tiingo returns {'detail': 'Error: ...'} for unknown tickers on some paths."""
    adapter = TiingoAdapter()
    with _patched_returns(_make_response(200, {"detail": "Error: ticker not found"})):
        with pytest.raises(_NotFoundError):
            adapter.get_ohlcv("BADTICKER", date(2026, 5, 1), date(2026, 5, 30))


def test_get_ohlcv_404_raises_notfound():
    adapter = TiingoAdapter()
    with _patched_returns(_make_response(404)):
        with pytest.raises(_NotFoundError):
            adapter.get_ohlcv("NVDA", date(2026, 5, 1), date(2026, 5, 30))


def test_get_ohlcv_429_raises_rate_limit():
    adapter = TiingoAdapter()
    with _patched_returns(_make_response(429)):
        with pytest.raises(_RateLimitError):
            adapter.get_ohlcv("NVDA", date(2026, 5, 1), date(2026, 5, 30))


def test_get_ohlcv_falls_back_from_adj_to_raw():
    """If a bar has no adjOpen/adjClose, the adapter falls back to raw open/close."""
    payload = [{
        "date": "2026-05-29T00:00:00.000Z",
        "open": 100.0, "high": 102.5, "low": 99.5, "close": 101.0, "volume": 1000000,
    }]
    adapter = TiingoAdapter()
    with _patched_returns(_make_response(200, payload)):
        bars = adapter.get_ohlcv("AAPL", date(2026, 5, 29), date(2026, 5, 29))
    assert bars[0].close == 101.0


def test_get_ohlcv_network_error_translates():
    adapter = TiingoAdapter()
    with patch.object(httpx.Client, "get", side_effect=httpx.ConnectError("boom")):
        with pytest.raises(_NetworkError):
            adapter.get_ohlcv("NVDA", date(2026, 5, 1), date(2026, 5, 30))


# ---------- Registry / chain integration ----------

def test_tiingo_in_builtin_adapter_modules():
    from data_vendor_router.vendors import _BUILTIN_ADAPTER_MODULES
    assert "tiingo" in _BUILTIN_ADAPTER_MODULES


def test_default_news_chain_includes_tiingo():
    """v0.1.2: Tiingo slotted right behind NewsAPI in the News chain."""
    from data_vendor_router.chains import DEFAULT_CHAINS
    chain = DEFAULT_CHAINS["news"]
    assert "tiingo" in chain
    assert chain.index("tiingo") == 1  # right after newsapi


def test_default_ohlcv_chain_includes_tiingo():
    """DVR-3 / v0.1.3: Tiingo is in the OHLCV chain between polygon and alpaca."""
    from data_vendor_router.chains import DEFAULT_CHAINS
    chain = DEFAULT_CHAINS["ohlcv"]
    assert "tiingo" in chain
    # DVR-3: polygon is now first; tiingo stays between polygon and alpaca
    assert chain.index("polygon") < chain.index("tiingo") < chain.index("alpaca")
