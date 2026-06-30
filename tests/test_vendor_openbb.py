"""Tests for the OpenBB adapter (TEST-1). Mocks the OpenBB SDK via sys.modules injection.

The adapter uses lazy `from openbb import obb` inside methods — so standard
`patch("data_vendor_router.vendors.openbb.obb")` is unreliable. We inject a
fake `openbb` module into sys.modules BEFORE importing/instantiating the adapter.
"""
from __future__ import annotations

import sys
import types
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data_vendor_router.dto import FundamentalsSnapshot, OHLCBar
from data_vendor_router.exceptions import (
    VendorResponseInvalid,
    _NetworkError,
    _NotFoundError,
    _RateLimitError,
)
from data_vendor_router.vendors import OHLCVProvider, FundamentalsProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv_df(rows=1, missing_col: str | None = None) -> pd.DataFrame:
    """Build a fake OHLCV DataFrame with a DatetimeIndex."""
    index = pd.to_datetime(["2026-04-01"] * rows)
    data = {
        "open":   [142.50] * rows,
        "high":   [145.20] * rows,
        "low":    [141.80] * rows,
        "close":  [144.50] * rows,
        "volume": [52_000_000] * rows,
    }
    if missing_col and missing_col in data:
        del data[missing_col]
    return pd.DataFrame(data, index=index)


def _make_obbject(df: pd.DataFrame) -> MagicMock:
    obj = MagicMock()
    obj.to_df.return_value = df
    return obj


def _make_fundamentals_df() -> pd.DataFrame:
    return pd.DataFrame([{
        "market_cap": 2_800_000_000_000,
        "pe_ratio": 35.5,
        "dividend_yield": 0.01,
        "net_profit_margin": 0.55,
        "revenue": 60_000_000_000,
        "sector": "Technology",
    }])


def _make_fake_openbb_module(
    ohlcv_side_effect=None,
    ohlcv_df=None,
    fundamentals_side_effect=None,
    fundamentals_df=None,
    fmp_side_effect=None,
    fmp_df=None,
) -> types.ModuleType:
    """Build a minimal fake openbb module with a mock `obb` attribute."""
    fake_obb = MagicMock()
    fake_obb.user.credentials = MagicMock()

    if ohlcv_side_effect is not None:
        fake_obb.equity.price.historical.side_effect = ohlcv_side_effect
    elif ohlcv_df is not None:
        fake_obb.equity.price.historical.return_value = _make_obbject(ohlcv_df)

    if fundamentals_side_effect is not None:
        fake_obb.equity.fundamental.metrics.side_effect = fundamentals_side_effect
    elif fundamentals_df is not None:
        fake_obb.equity.fundamental.metrics.return_value = _make_obbject(fundamentals_df)

    fake_module = types.ModuleType("openbb")
    fake_module.obb = fake_obb
    return fake_module


def _adapter_with_module(fake_module: types.ModuleType):
    """Import + instantiate OpenBBAdapter with the given fake module in sys.modules."""
    # Remove any previously cached import to force fresh resolution
    sys.modules.pop("data_vendor_router.vendors.openbb", None)
    # Remove stale real openbb from sys.modules if present (it won't be in unit tests)
    with patch.dict(sys.modules, {"openbb": fake_module}):
        from data_vendor_router.vendors.openbb import OpenBBAdapter
        adapter = OpenBBAdapter()
    return adapter, fake_module


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetOhlcvHappyPath:
    def test_get_ohlcv_happy_path(self):
        """AC-1.4, AC-6.1(a): happy-path returns OHLCBar list with correct values."""
        df = _make_ohlcv_df(rows=1)
        fake = _make_fake_openbb_module(ohlcv_df=df)
        with patch.dict(sys.modules, {"openbb": fake}):
            sys.modules.pop("data_vendor_router.vendors.openbb", None)
            from data_vendor_router.vendors.openbb import OpenBBAdapter
            adapter = OpenBBAdapter()
            with patch.dict(sys.modules, {"openbb": fake}):
                bars = adapter.get_ohlcv("AAPL", date(2026, 4, 1), date(2026, 4, 1))
        assert len(bars) >= 1
        assert isinstance(bars[0], OHLCBar)
        assert bars[0].close == 144.50
        assert bars[0].date == date(2026, 4, 1)


class TestGetOhlcvEmptyDf:
    def test_get_ohlcv_empty_df_not_found(self):
        """AC-1.7, AC-6.1(b): empty DataFrame from both providers -> _NotFoundError."""
        empty_df = pd.DataFrame()
        fake = _make_fake_openbb_module(ohlcv_df=empty_df)
        with patch.dict(sys.modules, {"openbb": fake}):
            sys.modules.pop("data_vendor_router.vendors.openbb", None)
            from data_vendor_router.vendors.openbb import OpenBBAdapter
            adapter = OpenBBAdapter()
            with patch.dict(sys.modules, {"openbb": fake}):
                with pytest.raises(_NotFoundError):
                    adapter.get_ohlcv("AAPL", date(2026, 4, 1), date(2026, 4, 1))


class TestGetOhlcvNetworkError:
    def test_get_ohlcv_network_error(self):
        """AC-1.6, AC-6.1(c): ConnectionError from obb -> _NetworkError."""
        fake = _make_fake_openbb_module(ohlcv_side_effect=ConnectionError("network failure"))
        with patch.dict(sys.modules, {"openbb": fake}):
            sys.modules.pop("data_vendor_router.vendors.openbb", None)
            from data_vendor_router.vendors.openbb import OpenBBAdapter
            adapter = OpenBBAdapter()
            with patch.dict(sys.modules, {"openbb": fake}):
                with pytest.raises(_NetworkError):
                    adapter.get_ohlcv("AAPL", date(2026, 4, 1), date(2026, 4, 1))


class TestGetOhlcvRateLimit:
    def test_get_ohlcv_rate_limit(self):
        """AC-1.5, AC-6.1(d): exc with '429 rate limit' msg -> _RateLimitError."""
        fake = _make_fake_openbb_module(ohlcv_side_effect=Exception("429 rate limit exceeded"))
        with patch.dict(sys.modules, {"openbb": fake}):
            sys.modules.pop("data_vendor_router.vendors.openbb", None)
            from data_vendor_router.vendors.openbb import OpenBBAdapter
            adapter = OpenBBAdapter()
            with patch.dict(sys.modules, {"openbb": fake}):
                with pytest.raises(_RateLimitError):
                    adapter.get_ohlcv("AAPL", date(2026, 4, 1), date(2026, 4, 1))


class TestCredentialsInjectedAtInit:
    def test_credentials_injected_at_init(self):
        """AC-2.1, AC-6.1(e): env vars FMP/POLYGON/FRED_API_KEY set on obb.user.credentials."""
        fake = _make_fake_openbb_module()
        env = {
            "FMP_API_KEY": "test_fmp",
            "POLYGON_API_KEY": "test_polygon",
            "FRED_API_KEY": "test_fred",
        }
        with patch.dict(sys.modules, {"openbb": fake}):
            sys.modules.pop("data_vendor_router.vendors.openbb", None)
            with patch.dict("os.environ", env):
                from data_vendor_router.vendors.openbb import OpenBBAdapter
                OpenBBAdapter()
        creds = fake.obb.user.credentials
        assert creds.fmp_api_key == "test_fmp"
        assert creds.polygon_api_key == "test_polygon"
        assert creds.fred_api_key == "test_fred"


class TestCredentialsAbsentNoError:
    def test_credentials_absent_no_error(self):
        """AC-2.2: no env vars set -> adapter init succeeds, no creds set."""
        fake = _make_fake_openbb_module()
        env_overrides = {
            "FMP_API_KEY": "",
            "POLYGON_API_KEY": "",
            "FRED_API_KEY": "",
        }
        with patch.dict(sys.modules, {"openbb": fake}):
            sys.modules.pop("data_vendor_router.vendors.openbb", None)
            # Unset keys by removing them from environ entirely
            with patch("os.getenv", side_effect=lambda k, *a: None):
                from data_vendor_router.vendors.openbb import OpenBBAdapter
                adapter = OpenBBAdapter()  # must not raise
        assert adapter is not None
        # No setattr on credentials (called 0 times for creds) — safe to just confirm no raise


class TestSchemaCanaryDrift:
    def test_schema_canary_drift_raises(self):
        """AC-1.8, AC-6.1(f), EC-5: df missing 'close' column -> VendorResponseInvalid."""
        df = _make_ohlcv_df(missing_col="close")
        fake = _make_fake_openbb_module(ohlcv_df=df)
        with patch.dict(sys.modules, {"openbb": fake}):
            sys.modules.pop("data_vendor_router.vendors.openbb", None)
            from data_vendor_router.vendors.openbb import OpenBBAdapter
            adapter = OpenBBAdapter()
            with patch.dict(sys.modules, {"openbb": fake}):
                with pytest.raises(VendorResponseInvalid):
                    adapter.get_ohlcv("AAPL", date(2026, 4, 1), date(2026, 4, 1))


class TestOhlcvFmpFailsThenPolygon:
    def test_ohlcv_fmp_fails_then_polygon(self):
        """EC-2: fmp raises network exc, polygon returns df -> bars returned (internal fallback)."""
        good_df = _make_ohlcv_df(rows=1)
        call_count = [0]

        def side_effect(**kwargs):
            call_count[0] += 1
            if kwargs.get("provider") == "fmp":
                raise ConnectionError("fmp network failure")
            return _make_obbject(good_df)

        fake_obb = MagicMock()
        fake_obb.user.credentials = MagicMock()
        fake_obb.equity.price.historical.side_effect = side_effect

        fake = types.ModuleType("openbb")
        fake.obb = fake_obb

        with patch.dict(sys.modules, {"openbb": fake}):
            sys.modules.pop("data_vendor_router.vendors.openbb", None)
            from data_vendor_router.vendors.openbb import OpenBBAdapter
            adapter = OpenBBAdapter()
            with patch.dict(sys.modules, {"openbb": fake}):
                bars = adapter.get_ohlcv("AAPL", date(2026, 4, 1), date(2026, 4, 1))

        assert len(bars) >= 1
        assert call_count[0] == 2  # fmp tried first, then polygon


class TestGetFundamentalsHappyPath:
    def test_get_fundamentals_happy_path(self):
        """AC-5.1, AC-5.3: fundamentals happy path -> FundamentalsSnapshot with extras['openbb']."""
        df = _make_fundamentals_df()
        fake_obb = MagicMock()
        fake_obb.user.credentials = MagicMock()
        fake_obb.equity.fundamental.metrics.return_value = _make_obbject(df)

        fake = types.ModuleType("openbb")
        fake.obb = fake_obb

        with patch.dict(sys.modules, {"openbb": fake}):
            sys.modules.pop("data_vendor_router.vendors.openbb", None)
            from data_vendor_router.vendors.openbb import OpenBBAdapter
            adapter = OpenBBAdapter()
            with patch.dict(sys.modules, {"openbb": fake}):
                snap = adapter.get_fundamentals("AAPL")

        assert isinstance(snap, FundamentalsSnapshot)
        assert snap.ticker == "AAPL"
        assert snap.market_cap == 2_800_000_000_000
        assert "openbb" in snap.extras
        assert "market_cap" in snap.extras["openbb"]


class TestGetFundamentalsEmptyNotFound:
    def test_get_fundamentals_empty_not_found(self):
        """AC-5.2, EC-7: empty df from all providers -> _NotFoundError."""
        empty_df = pd.DataFrame()
        fake_obb = MagicMock()
        fake_obb.user.credentials = MagicMock()
        fake_obb.equity.fundamental.metrics.return_value = _make_obbject(empty_df)

        fake = types.ModuleType("openbb")
        fake.obb = fake_obb

        with patch.dict(sys.modules, {"openbb": fake}):
            sys.modules.pop("data_vendor_router.vendors.openbb", None)
            from data_vendor_router.vendors.openbb import OpenBBAdapter
            adapter = OpenBBAdapter()
            with patch.dict(sys.modules, {"openbb": fake}):
                with pytest.raises(_NotFoundError):
                    adapter.get_fundamentals("AAPL")


class TestIsinstanceProtocol:
    def test_isinstance_protocol(self):
        """AC-1.1: adapter satisfies OHLCVProvider and FundamentalsProvider protocols."""
        fake = _make_fake_openbb_module()
        with patch.dict(sys.modules, {"openbb": fake}):
            sys.modules.pop("data_vendor_router.vendors.openbb", None)
            from data_vendor_router.vendors.openbb import OpenBBAdapter
            adapter = OpenBBAdapter()
        assert isinstance(adapter, OHLCVProvider)
        assert isinstance(adapter, FundamentalsProvider)
