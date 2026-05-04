"""Tests for the alpaca adapter (T10). Stubs the alpaca-py SDK."""
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# alpaca-py may not be installed in the dev environment; skip cleanly if so
alpaca = pytest.importorskip("alpaca")

from data_vendor_router.dto import OHLCBar
from data_vendor_router.exceptions import (
    _NetworkError,
    _NotFoundError,
    _RateLimitError,
)
from data_vendor_router.vendors.alpaca import AlpacaAdapter


def _make_alpaca_response():
    """Build a fake alpaca-py StockBarsResponse with .data dict."""
    bar = MagicMock()
    bar.timestamp = datetime(2026, 4, 1, tzinfo=timezone.utc)
    bar.open = 142.50
    bar.high = 145.20
    bar.low = 141.80
    bar.close = 144.50
    bar.volume = 52_000_000
    response = MagicMock()
    response.data = {"NVDA": [bar]}
    return response


def test_get_ohlcv_happy_path():
    adapter = AlpacaAdapter()
    with patch.object(adapter, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.get_stock_bars.return_value = _make_alpaca_response()
        mock_get_client.return_value = mock_client
        bars = adapter.get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 5))
    assert len(bars) == 1
    assert isinstance(bars[0], OHLCBar)
    assert bars[0].close == 144.50


def test_get_ohlcv_empty_response_raises_not_found():
    adapter = AlpacaAdapter()
    empty_response = MagicMock()
    empty_response.data = {"NVDA": []}
    with patch.object(adapter, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.get_stock_bars.return_value = empty_response
        mock_get_client.return_value = mock_client
        with pytest.raises(_NotFoundError):
            adapter.get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 5))


def test_classify_rate_limit():
    adapter = AlpacaAdapter()
    with patch.object(adapter, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.get_stock_bars.side_effect = RuntimeError("HTTP 429 rate limit exceeded")
        mock_get_client.return_value = mock_client
        with pytest.raises(_RateLimitError):
            adapter.get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 5))


def test_classify_unknown_error_as_network():
    """Unknown alpaca errors are treated as transient → fall back."""
    adapter = AlpacaAdapter()
    with patch.object(adapter, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.get_stock_bars.side_effect = RuntimeError("some weird new error")
        mock_get_client.return_value = mock_client
        with pytest.raises(_NetworkError):
            adapter.get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 5))
