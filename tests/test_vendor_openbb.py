"""Tests for the OpenBB adapter (TEST-1). Mocks the OpenBB SDK via sys.modules injection.

The adapter uses lazy `from openbb import obb` inside methods — so standard
`patch("data_vendor_router.vendors.openbb.obb")` is unreliable. We inject a
fake `openbb` module into sys.modules BEFORE importing/instantiating the adapter.

Real-SDK integration tests are marked `@pytest.mark.live_vendor` and excluded from
the default run (pytest.ini: addopts = "-m 'not live_vendor'"). They exercise the
actual openbb>=4.7 package with yfinance (free, no key required) to prevent silent
"import skipped" regressions like the broken openbb-core>=4.3 pin (2026-06-30).
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
    """Build a fake OHLCV DataFrame with a DatetimeIndex (pandas Timestamp index)."""
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


def _make_ohlcv_df_date_index(rows=1) -> pd.DataFrame:
    """Build OHLCV DataFrame with datetime.date index (as yfinance/polygon return via OpenBB)."""
    index = [date(2026, 4, 1)] * rows
    data = {
        "open":   [142.50] * rows,
        "high":   [145.20] * rows,
        "low":    [141.80] * rows,
        "close":  [144.50] * rows,
        "volume": [52_000_000] * rows,
    }
    return pd.DataFrame(data, index=pd.Index(index))


def _make_obbject(df: pd.DataFrame) -> MagicMock:
    obj = MagicMock()
    obj.to_df.return_value = df
    return obj


def _make_profile_df() -> pd.DataFrame:
    """Profile data from equity.profile(provider='yfinance')."""
    return pd.DataFrame([{
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "sector": "Technology",
        "market_cap": 2_800_000_000_000,
        "dividend_yield": 0.01,
        "beta": 1.2,
    }])


def _make_income_df() -> pd.DataFrame:
    """Income statement from equity.fundamental.income(provider='sec')."""
    return pd.DataFrame([{
        "period_ending": "2024-09-28",
        "fiscal_period": "FY",
        "total_revenue": 60_000_000_000,
        "operating_revenue": 60_000_000_000,
        "net_income": 33_000_000_000,
    }])


def _make_fake_openbb_module(
    ohlcv_side_effect=None,
    ohlcv_df=None,
    # New: separate profile and income kwargs for the fixed fundamentals path
    profile_side_effect=None,
    profile_df=None,
    income_side_effect=None,
    income_df=None,
    # Legacy compat: if set, wires fundamental.metrics (FMP enrichment path only)
    metrics_side_effect=None,
    metrics_df=None,
) -> types.ModuleType:
    """Build a minimal fake openbb module with a mock `obb` attribute."""
    fake_obb = MagicMock()
    fake_obb.user.credentials = MagicMock()
    # Ensure hasattr(creds, 'fmp_api_key') returns True (MagicMock does this by default)

    if ohlcv_side_effect is not None:
        fake_obb.equity.price.historical.side_effect = ohlcv_side_effect
    elif ohlcv_df is not None:
        fake_obb.equity.price.historical.return_value = _make_obbject(ohlcv_df)

    # profile path (equity.profile)
    if profile_side_effect is not None:
        fake_obb.equity.profile.side_effect = profile_side_effect
    elif profile_df is not None:
        fake_obb.equity.profile.return_value = _make_obbject(profile_df)

    # SEC income path (equity.fundamental.income)
    if income_side_effect is not None:
        fake_obb.equity.fundamental.income.side_effect = income_side_effect
    elif income_df is not None:
        fake_obb.equity.fundamental.income.return_value = _make_obbject(income_df)

    # FMP metrics (optional enrichment)
    if metrics_side_effect is not None:
        fake_obb.equity.fundamental.metrics.side_effect = metrics_side_effect
    elif metrics_df is not None:
        fake_obb.equity.fundamental.metrics.return_value = _make_obbject(metrics_df)

    fake_module = types.ModuleType("openbb")
    fake_module.obb = fake_obb
    return fake_module


def _adapter_with_module(fake_module: types.ModuleType):
    """Import + instantiate OpenBBAdapter with the given fake module in sys.modules."""
    sys.modules.pop("data_vendor_router.vendors.openbb", None)
    with patch.dict(sys.modules, {"openbb": fake_module}):
        from data_vendor_router.vendors.openbb import OpenBBAdapter
        adapter = OpenBBAdapter()
    return adapter, fake_module


# ---------------------------------------------------------------------------
# Tests — OHLCV
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

    def test_get_ohlcv_date_index_happy_path(self):
        """Adapter correctly handles datetime.date index (as returned by yfinance/polygon via OpenBB)."""
        df = _make_ohlcv_df_date_index(rows=1)
        fake = _make_fake_openbb_module(ohlcv_df=df)
        with patch.dict(sys.modules, {"openbb": fake}):
            sys.modules.pop("data_vendor_router.vendors.openbb", None)
            from data_vendor_router.vendors.openbb import OpenBBAdapter
            adapter = OpenBBAdapter()
            with patch.dict(sys.modules, {"openbb": fake}):
                bars = adapter.get_ohlcv("AAPL", date(2026, 4, 1), date(2026, 4, 1))
        assert len(bars) == 1
        assert bars[0].date == date(2026, 4, 1)
        assert bars[0].close == 144.50


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
        with patch.dict(sys.modules, {"openbb": fake}):
            sys.modules.pop("data_vendor_router.vendors.openbb", None)
            with patch("os.getenv", side_effect=lambda k, *a: None):
                from data_vendor_router.vendors.openbb import OpenBBAdapter
                adapter = OpenBBAdapter()  # must not raise
        assert adapter is not None


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


# ---------------------------------------------------------------------------
# Tests — Fundamentals (fixed path: profile + SEC income, NOT metrics+sec)
# ---------------------------------------------------------------------------

class TestGetFundamentalsHappyPath:
    def test_get_fundamentals_happy_path(self):
        """AC-5.1, AC-5.3: fundamentals happy path (profile+income) -> FundamentalsSnapshot."""
        profile_df = _make_profile_df()
        income_df = _make_income_df()
        fake_obb = MagicMock()
        fake_obb.user.credentials = MagicMock()
        fake_obb.equity.profile.return_value = _make_obbject(profile_df)
        fake_obb.equity.fundamental.income.return_value = _make_obbject(income_df)
        # metrics should NOT be called (no FMP key in env)
        fake_obb.equity.fundamental.metrics.side_effect = AssertionError("metrics called unexpectedly")

        fake = types.ModuleType("openbb")
        fake.obb = fake_obb

        with patch.dict(sys.modules, {"openbb": fake}):
            sys.modules.pop("data_vendor_router.vendors.openbb", None)
            from data_vendor_router.vendors.openbb import OpenBBAdapter
            adapter = OpenBBAdapter()
            with patch.dict(sys.modules, {"openbb": fake}):
                with patch("os.getenv", side_effect=lambda k, *a: None):  # no FMP key
                    snap = adapter.get_fundamentals("AAPL")

        assert isinstance(snap, FundamentalsSnapshot)
        assert snap.ticker == "AAPL"
        assert snap.market_cap == 2_800_000_000_000
        assert snap.sector == "Technology"
        assert snap.revenue_ttm == 60_000_000_000
        # OpenBB yfinance profile returns dividend_yield as PERCENT (0.01 = 0.01%).
        # DVR canonical is DECIMAL FRACTION → expect 0.01 / 100 = 0.0001.
        assert snap.dividend_yield == pytest.approx(0.0001, rel=1e-6)
        assert "openbb_profile" in snap.extras
        assert "openbb_sec_income" in snap.extras

    def test_get_fundamentals_profile_only_when_income_fails(self):
        """If SEC income fails but profile succeeds, snap is still returned with profile data."""
        profile_df = _make_profile_df()
        fake_obb = MagicMock()
        fake_obb.user.credentials = MagicMock()
        fake_obb.equity.profile.return_value = _make_obbject(profile_df)
        fake_obb.equity.fundamental.income.side_effect = Exception("SEC network error")

        fake = types.ModuleType("openbb")
        fake.obb = fake_obb

        with patch.dict(sys.modules, {"openbb": fake}):
            sys.modules.pop("data_vendor_router.vendors.openbb", None)
            from data_vendor_router.vendors.openbb import OpenBBAdapter
            adapter = OpenBBAdapter()
            with patch.dict(sys.modules, {"openbb": fake}):
                with patch("os.getenv", side_effect=lambda k, *a: None):
                    snap = adapter.get_fundamentals("AAPL")

        # Profile data is still returned
        assert isinstance(snap, FundamentalsSnapshot)
        assert snap.market_cap == 2_800_000_000_000
        assert snap.revenue_ttm is None  # income failed

    def test_get_fundamentals_fmp_enrichment_when_key_set(self):
        """FMP metrics enrichment runs when FMP_API_KEY is set, adds pe_ratio."""
        profile_df = _make_profile_df()
        income_df = _make_income_df()
        metrics_df = pd.DataFrame([{
            "market_cap": 2_800_000_000_000,
            "pe_ratio": 35.5,
            "net_profit_margin": 0.55,
            "revenue": 60_000_000_000,
        }])

        fake_obb = MagicMock()
        fake_obb.user.credentials = MagicMock()
        fake_obb.equity.profile.return_value = _make_obbject(profile_df)
        fake_obb.equity.fundamental.income.return_value = _make_obbject(income_df)
        fake_obb.equity.fundamental.metrics.return_value = _make_obbject(metrics_df)

        fake = types.ModuleType("openbb")
        fake.obb = fake_obb

        with patch.dict(sys.modules, {"openbb": fake}):
            sys.modules.pop("data_vendor_router.vendors.openbb", None)
            from data_vendor_router.vendors.openbb import OpenBBAdapter
            adapter = OpenBBAdapter()
            with patch.dict(sys.modules, {"openbb": fake}):
                with patch("os.getenv", side_effect=lambda k, *a: "test_fmp_key" if k == "FMP_API_KEY" else None):
                    snap = adapter.get_fundamentals("AAPL")

        assert snap.pe == 35.5
        assert snap.profit_margin == 0.55
        assert "openbb_fmp_metrics" in snap.extras


class TestGetFundamentalsEmptyNotFound:
    def test_get_fundamentals_both_empty_not_found(self):
        """AC-5.2, EC-7: empty df from profile AND income -> _NotFoundError."""
        empty_df = pd.DataFrame()
        fake_obb = MagicMock()
        fake_obb.user.credentials = MagicMock()
        fake_obb.equity.profile.return_value = _make_obbject(empty_df)
        fake_obb.equity.fundamental.income.side_effect = Exception("sec not found")

        fake = types.ModuleType("openbb")
        fake.obb = fake_obb

        with patch.dict(sys.modules, {"openbb": fake}):
            sys.modules.pop("data_vendor_router.vendors.openbb", None)
            from data_vendor_router.vendors.openbb import OpenBBAdapter
            adapter = OpenBBAdapter()
            with patch.dict(sys.modules, {"openbb": fake}):
                with patch("os.getenv", side_effect=lambda k, *a: None):
                    with pytest.raises((_NotFoundError, _NetworkError)):
                        adapter.get_fundamentals("AAPL")


# ---------------------------------------------------------------------------
# Tests — Protocol conformance
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Real-SDK integration test (excluded from default run; mark live_vendor)
# ---------------------------------------------------------------------------

@pytest.mark.live_vendor
class TestOpenBBRealSDK:
    """Exercises the real OpenBB SDK (openbb>=4.7) with yfinance (free, no key).

    Excluded from the default pytest run via addopts = "-m 'not live_vendor'".
    Run explicitly with: pytest -m live_vendor tests/test_vendor_openbb.py

    Purpose: prevent regression to "silently skipped" state caused by broken
    pip pins (e.g. openbb-core>=4.3 which resolves to nothing and allows
    `import openbb` to ImportError silently in register_all_available()).
    """

    def test_real_sdk_ohlcv_bars_parsing(self):
        """Prove adapter._obbject_to_bars() handles the real SDK's OBBject correctly.

        get_ohlcv() routes through fmp→polygon (both need paid keys), so we exercise
        the real SDK at the yfinance level and feed the real OBBject into _obbject_to_bars
        directly — proving the DataFrame index/column mapping works against the real SDK.
        """
        try:
            from openbb import obb
        except ImportError as e:
            pytest.skip(f"openbb extras not installed: {e}")

        # Get a real OBBject from yfinance (free, no key)
        start = date(2026, 1, 6)
        end = date(2026, 1, 9)
        obbject = obb.equity.price.historical(
            symbol="AAPL",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            provider="yfinance",
        )

        sys.modules.pop("data_vendor_router.vendors.openbb", None)
        from data_vendor_router.vendors.openbb import OpenBBAdapter
        adapter = OpenBBAdapter()

        # Feed real OBBject through the adapter's parsing logic
        bars = adapter._obbject_to_bars(obbject, "AAPL")

        assert len(bars) >= 1, "Expected at least 1 OHLCV bar from yfinance"
        bar = bars[0]
        assert isinstance(bar, OHLCBar)
        assert bar.open > 0
        assert bar.high >= bar.low
        assert bar.volume > 0
        assert isinstance(bar.date, date)
        assert start <= bar.date <= end

    def test_real_sdk_fundamentals_yfinance_profile(self):
        """Confirm the real SDK returns fundamentals via yfinance profile path (free)."""
        try:
            import openbb  # noqa: F401
            from openbb import obb  # noqa: F401
        except ImportError as e:
            pytest.skip(f"openbb extras not installed: {e}")

        sys.modules.pop("data_vendor_router.vendors.openbb", None)
        from data_vendor_router.vendors.openbb import OpenBBAdapter
        adapter = OpenBBAdapter()

        snap = adapter.get_fundamentals("AAPL")

        assert isinstance(snap, FundamentalsSnapshot)
        assert snap.ticker == "AAPL"
        assert snap.market_cap is not None and snap.market_cap > 0
        assert snap.sector is not None
        assert "openbb_profile" in snap.extras

    def test_real_sdk_imported_correctly(self):
        """Prove openbb umbrella is installed and obb.equity path exists (no silent skip)."""
        try:
            from openbb import obb
        except ImportError as e:
            pytest.fail(
                f"openbb not importable — the [openbb] extras are broken: {e}. "
                "Likely cause: bad version pin in pyproject.toml [openbb] extras."
            )

        assert hasattr(obb, "equity"), (
            "obb.equity not present — SDK build step failed. "
            "The umbrella `openbb` package (4.x) is required, not just openbb-core (1.x)."
        )
        assert hasattr(obb.equity, "price"), "obb.equity.price missing"
        assert hasattr(obb.equity.price, "historical"), "obb.equity.price.historical missing"
        assert hasattr(obb.equity, "fundamental"), "obb.equity.fundamental missing"
