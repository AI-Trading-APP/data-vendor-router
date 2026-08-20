"""Tests for the polygon adapter (T12). Stubs httpx.Client.get."""
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from data_vendor_router.dto import FundamentalsSnapshot, OHLCBar
from data_vendor_router.exceptions import (
    VendorResponseInvalid,
    _BadRequestError,
    _NetworkError,
    _NotFoundError,
    _RateLimitError,
    _ServerError,
)
from data_vendor_router.vendors.polygon import PolygonAdapter


def _make_response(status_code: int, json_payload=None, text=""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json = lambda: json_payload if json_payload is not None else {}
    resp.text = text
    return resp


def _patched_client_returns(response):
    return patch.object(httpx.Client, "get", return_value=response)


# ============== get_ohlcv ==============


def test_get_ohlcv_happy_path():
    payload = {
        "results": [
            {
                "t": int(datetime(2026, 4, 1, 14, 30, tzinfo=timezone.utc).timestamp() * 1000),
                "o": 142.50, "h": 145.20, "l": 141.80, "c": 144.50, "v": 52_000_000,
            },
        ],
    }
    adapter = PolygonAdapter()
    with _patched_client_returns(_make_response(200, payload)):
        bars = adapter.get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 2))
    assert len(bars) == 1
    assert isinstance(bars[0], OHLCBar)
    assert bars[0].close == 144.50
    assert bars[0].date == date(2026, 4, 1)


def test_get_ohlcv_empty_results_raises_not_found():
    adapter = PolygonAdapter()
    with _patched_client_returns(_make_response(200, {"results": []})):
        with pytest.raises(_NotFoundError):
            adapter.get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 2))


def test_get_ohlcv_429_rate_limit():
    adapter = PolygonAdapter()
    with _patched_client_returns(_make_response(429, {})):
        with pytest.raises(_RateLimitError):
            adapter.get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 2))


def test_get_ohlcv_404():
    adapter = PolygonAdapter()
    with _patched_client_returns(_make_response(404, {})):
        with pytest.raises(_NotFoundError):
            adapter.get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 2))


def test_get_ohlcv_503():
    adapter = PolygonAdapter()
    with _patched_client_returns(_make_response(503, {})):
        with pytest.raises(_ServerError):
            adapter.get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 2))


def test_get_ohlcv_400_bad_request():
    adapter = PolygonAdapter()
    with _patched_client_returns(_make_response(400, {})):
        with pytest.raises(_BadRequestError):
            adapter.get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 2))


def test_get_ohlcv_network_error():
    adapter = PolygonAdapter()
    with patch.object(httpx.Client, "get", side_effect=httpx.TimeoutException("timeout")):
        with pytest.raises(_NetworkError):
            adapter.get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 2))


def test_get_ohlcv_malformed_bar_raises_invalid():
    """A bar missing required field → VendorResponseInvalid (not fallback)."""
    adapter = PolygonAdapter()
    bad_payload = {"results": [{"o": 142.0}]}  # missing t, h, l, c, v
    with _patched_client_returns(_make_response(200, bad_payload)):
        with pytest.raises(VendorResponseInvalid):
            adapter.get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 2))


# ============== get_fundamentals ==============


def test_get_fundamentals_happy_path():
    payload = {
        "results": {
            "market_cap": 2_800_000_000_000,
            "sic_description": "Semiconductors",
            "share_class_shares_outstanding": 24_500_000_000,
            "weighted_shares_outstanding": 24_400_000_000,
            "primary_exchange": "NASDAQ",
            "homepage_url": "https://nvidia.com",
        },
    }
    adapter = PolygonAdapter()
    with _patched_client_returns(_make_response(200, payload)):
        snap = adapter.get_fundamentals("NVDA")
    assert isinstance(snap, FundamentalsSnapshot)
    assert snap.market_cap == 2_800_000_000_000
    assert snap.sector == "Semiconductors"
    assert snap.extras["polygon"]["primary_exchange"] == "NASDAQ"


def test_get_fundamentals_no_results_raises_not_found():
    adapter = PolygonAdapter()
    with _patched_client_returns(_make_response(200, {})):
        with pytest.raises(_NotFoundError):
            adapter.get_fundamentals("NVDA")


# ===== SECURITY regression: key in Authorization header, never in URL/query =====
# httpx logs the full request URL; an apiKey query param would leak the raw key.
# See vendors/polygon.py SECURITY comments (pe-ff-secret-redact).


def _capture_get_call(monkeypatch, call_fn):
    monkeypatch.setenv("POLYGON_API_KEY", "SECRET_KEY_123")
    mock_get = MagicMock(
        return_value=_make_response(
            200,
            {
                "results": [
                    {
                        "t": int(datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp() * 1000),
                        "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 1,
                    }
                ]
            },
        )
    )
    with patch.object(httpx.Client, "get", mock_get):
        try:
            call_fn(PolygonAdapter())
        except Exception:
            # Downstream parsing may reject the stub payload for some endpoints —
            # irrelevant here; we only assert HOW the request was made.
            pass
    args, kwargs = mock_get.call_args
    url = args[0] if args else kwargs.get("url", "")
    params = kwargs.get("params") or {}
    headers = kwargs.get("headers") or {}
    return url, params, headers


def test_get_ohlcv_key_in_header_not_query(monkeypatch):
    url, params, headers = _capture_get_call(
        monkeypatch, lambda a: a.get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 2))
    )
    assert "SECRET_KEY_123" not in url and "apiKey" not in url
    assert "apiKey" not in params and "SECRET_KEY_123" not in str(params)
    assert headers.get("Authorization") == "Bearer SECRET_KEY_123"


def test_get_fundamentals_key_in_header_not_query(monkeypatch):
    url, params, headers = _capture_get_call(
        monkeypatch, lambda a: a.get_fundamentals("NVDA")
    )
    assert "SECRET_KEY_123" not in url and "apiKey" not in url
    assert "apiKey" not in params and "SECRET_KEY_123" not in str(params)
    assert headers.get("Authorization") == "Bearer SECRET_KEY_123"
