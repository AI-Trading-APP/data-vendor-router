"""Tests for the benzinga adapter (T11). Stubs httpx.Client.get."""
from unittest.mock import MagicMock, patch

import httpx
import pytest

from data_vendor_router.dto import NewsItem
from data_vendor_router.exceptions import (
    VendorResponseInvalid,
    _BadRequestError,
    _NetworkError,
    _NotFoundError,
    _RateLimitError,
    _ServerError,
)
from data_vendor_router.vendors.benzinga import BenzingaAdapter


def _make_response(status_code: int, json_payload=None, text=""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json = lambda: json_payload if json_payload is not None else {}
    resp.text = text
    return resp


def _patched_client_returns(response):
    """Patch httpx.Client.get to return `response` (whether status OK or error)."""
    return patch.object(httpx.Client, "get", return_value=response)


def test_get_news_happy_path():
    payload = [
        {
            "id": 1,
            "title": "TSLA Q1 deliveries miss",
            "url": "https://example.com/tsla",
            "teaser": "EV demand softening",
            "created": "Fri, 02 May 2026 14:00:00 -0400",
            "stocks": [{"name": "TSLA"}, {"name": "RIVN"}],
        },
    ]
    adapter = BenzingaAdapter()
    with _patched_client_returns(_make_response(200, payload)):
        items = adapter.get_news("TSLA", lookback_days=7, top_n=5)
    assert len(items) == 1
    assert isinstance(items[0], NewsItem)
    assert items[0].title == "TSLA Q1 deliveries miss"
    assert items[0].source == "Benzinga"
    assert items[0].tickers == ("TSLA", "RIVN")


def test_get_news_empty_array_returns_empty():
    adapter = BenzingaAdapter()
    with _patched_client_returns(_make_response(200, [])):
        items = adapter.get_news("OBSCURE", lookback_days=7, top_n=5)
    assert items == []


def test_get_news_429_raises_rate_limit():
    adapter = BenzingaAdapter()
    with _patched_client_returns(_make_response(429, {})):
        with pytest.raises(_RateLimitError):
            adapter.get_news("TSLA", lookback_days=7, top_n=5)


def test_get_news_404_raises_not_found():
    adapter = BenzingaAdapter()
    with _patched_client_returns(_make_response(404, {})):
        with pytest.raises(_NotFoundError):
            adapter.get_news("TSLA", lookback_days=7, top_n=5)


def test_get_news_400_raises_bad_request():
    adapter = BenzingaAdapter()
    with _patched_client_returns(_make_response(400, {})):
        with pytest.raises(_BadRequestError):
            adapter.get_news("TSLA", lookback_days=7, top_n=5)


def test_get_news_503_raises_server_error():
    adapter = BenzingaAdapter()
    with _patched_client_returns(_make_response(503, {})):
        with pytest.raises(_ServerError):
            adapter.get_news("TSLA", lookback_days=7, top_n=5)


def test_get_news_network_error_translates():
    adapter = BenzingaAdapter()
    with patch.object(httpx.Client, "get", side_effect=httpx.ConnectError("boom")):
        with pytest.raises(_NetworkError):
            adapter.get_news("TSLA", lookback_days=7, top_n=5)


def test_get_news_non_list_payload_invalid():
    """If Benzinga returns a dict (instead of list), raise VendorResponseInvalid."""
    adapter = BenzingaAdapter()
    with _patched_client_returns(_make_response(200, {"items": []})):
        with pytest.raises(VendorResponseInvalid):
            adapter.get_news("TSLA", lookback_days=7, top_n=5)


def test_get_news_top_n_limits():
    items_data = [
        {"id": i, "title": f"T{i}", "url": f"https://example.com/{i}",
         "teaser": "", "created": "Fri, 02 May 2026 14:00:00 -0400",
         "stocks": [{"name": "NVDA"}]}
        for i in range(10)
    ]
    adapter = BenzingaAdapter()
    with _patched_client_returns(_make_response(200, items_data)):
        items = adapter.get_news("NVDA", lookback_days=7, top_n=3)
    assert len(items) == 3
