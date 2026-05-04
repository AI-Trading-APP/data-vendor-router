"""Tests for the newsapi adapter (v0.1.1)."""
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
from data_vendor_router.vendors.newsapi import NewsAPIAdapter


def _make_response(status_code: int, json_payload=None, text=""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json = lambda: json_payload if json_payload is not None else {}
    resp.text = text
    return resp


def _patched_returns(response):
    return patch.object(httpx.Client, "get", return_value=response)


def test_get_news_happy_path():
    payload = {
        "status": "ok",
        "totalResults": 1,
        "articles": [{
            "source": {"id": "reuters", "name": "Reuters"},
            "author": "Author Name",
            "title": "NVDA reports record Q1",
            "description": "Strong earnings",
            "url": "https://example.com/nvda-q1",
            "publishedAt": "2026-05-01T14:00:00Z",
            "content": "Body...",
        }],
    }
    adapter = NewsAPIAdapter()
    with _patched_returns(_make_response(200, payload)):
        items = adapter.get_news("NVDA", lookback_days=7, top_n=5)
    assert len(items) == 1
    assert isinstance(items[0], NewsItem)
    assert items[0].title == "NVDA reports record Q1"
    assert items[0].source == "Reuters"
    assert items[0].tickers == ("NVDA",)


def test_get_news_empty_articles_returns_empty():
    adapter = NewsAPIAdapter()
    with _patched_returns(_make_response(200, {"status": "ok", "articles": []})):
        items = adapter.get_news("OBSCURE", lookback_days=7, top_n=5)
    assert items == []


def test_get_news_429_status_raises_rate_limit():
    adapter = NewsAPIAdapter()
    with _patched_returns(_make_response(429)):
        with pytest.raises(_RateLimitError):
            adapter.get_news("NVDA", lookback_days=7, top_n=5)


def test_get_news_200_with_status_error_rate_limited_body():
    """NewsAPI sometimes returns 200 with status='error', code='rateLimited'."""
    payload = {"status": "error", "code": "rateLimited", "message": "Daily limit reached"}
    adapter = NewsAPIAdapter()
    with _patched_returns(_make_response(200, payload)):
        with pytest.raises(_RateLimitError, match="Daily limit reached"):
            adapter.get_news("NVDA", lookback_days=7, top_n=5)


def test_get_news_200_with_status_error_invalid_key():
    payload = {"status": "error", "code": "apiKeyInvalid", "message": "Bad key"}
    adapter = NewsAPIAdapter()
    with _patched_returns(_make_response(200, payload)):
        with pytest.raises(_BadRequestError):
            adapter.get_news("NVDA", lookback_days=7, top_n=5)


def test_get_news_503_raises_server_error():
    adapter = NewsAPIAdapter()
    with _patched_returns(_make_response(503)):
        with pytest.raises(_ServerError):
            adapter.get_news("NVDA", lookback_days=7, top_n=5)


def test_get_news_400_raises_bad_request():
    adapter = NewsAPIAdapter()
    with _patched_returns(_make_response(400)):
        with pytest.raises(_BadRequestError):
            adapter.get_news("NVDA", lookback_days=7, top_n=5)


def test_get_news_network_error_translates():
    adapter = NewsAPIAdapter()
    with patch.object(httpx.Client, "get", side_effect=httpx.ConnectError("boom")):
        with pytest.raises(_NetworkError):
            adapter.get_news("NVDA", lookback_days=7, top_n=5)


def test_get_news_missing_articles_field_raises_invalid():
    adapter = NewsAPIAdapter()
    with _patched_returns(_make_response(200, {"status": "ok", "totalResults": 0})):
        with pytest.raises(VendorResponseInvalid):
            adapter.get_news("NVDA", lookback_days=7, top_n=5)


def test_get_news_top_n_limits():
    articles = [{
        "source": {"id": "x", "name": "X"},
        "title": f"T{i}", "url": f"https://example.com/{i}",
        "publishedAt": "2026-05-01T14:00:00Z",
        "description": "",
    } for i in range(10)]
    payload = {"status": "ok", "articles": articles}
    adapter = NewsAPIAdapter()
    with _patched_returns(_make_response(200, payload)):
        items = adapter.get_news("NVDA", lookback_days=7, top_n=3)
    assert len(items) == 3
    assert items[0].title == "T0"


def test_default_news_chain_now_includes_newsapi():
    """v0.1.1 promotes NewsAPI to primary in the News chain."""
    from data_vendor_router.chains import DEFAULT_CHAINS
    assert DEFAULT_CHAINS["news"][0] == "newsapi"
    assert "benzinga" in DEFAULT_CHAINS["news"]
    assert "alpha_vantage" in DEFAULT_CHAINS["news"]


def test_newsapi_in_builtin_adapter_modules():
    from data_vendor_router.vendors import _BUILTIN_ADAPTER_MODULES
    assert "newsapi" in _BUILTIN_ADAPTER_MODULES
