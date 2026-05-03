"""Core router tests — exercises GD-DVR-001..014 from the AITradingAPP spec.

Tests use stub adapters (registered via the `make_stub` fixture in conftest)
so no real vendor calls happen.
"""
from datetime import date

import pytest

from data_vendor_router import breakers, get_fundamentals, get_news, get_ohlcv
from data_vendor_router.exceptions import (
    AllVendorsFailed,
    BadRequest,
    NoVendorsConfigured,
    NotFound,
    _BadRequestError,
    _NetworkError,
    _NotFoundError,
    _RateLimitError,
    _ServerError,
)
from tests.conftest import (
    raises,
    returns,
    sample_fundamentals_snapshot,
    sample_news_items,
    sample_ohlc_bars,
)


# ============== GD-DVR-001 — primary vendor success ==============


def test_gd_001_primary_success_no_fallback(make_stub, monkeypatch):
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance,alpaca,polygon")
    yf = make_stub("yfinance")
    yf.program("get_ohlcv", returns(sample_ohlc_bars(2)))

    bars = get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 5))

    assert len(bars) == 2
    assert len(yf.call_log) == 1   # only 1 call
    assert yf.call_log[0][0] == "get_ohlcv"


# ============== GD-DVR-002 — yfinance rate-limited, alpaca succeeds ==============


def test_gd_002_rate_limit_falls_back_to_next(make_stub, monkeypatch):
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance,alpaca,polygon")
    yf = make_stub("yfinance")
    al = make_stub("alpaca")
    yf.program("get_ohlcv", raises(_RateLimitError("429")))
    al.program("get_ohlcv", returns(sample_ohlc_bars(1)))

    bars = get_ohlcv("AAPL", date(2026, 4, 1), date(2026, 4, 5))

    assert len(bars) == 1
    # yfinance only retries on _NetworkError (REQ-DVR-008), not on _RateLimitError, so 1 call:
    assert len(yf.call_log) == 1
    assert len(al.call_log) == 1


# ============== GD-DVR-003 — multi-vendor fallback ==============


def test_gd_003_multi_vendor_fallback(make_stub, monkeypatch):
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance,alpaca,polygon")
    yf = make_stub("yfinance")
    al = make_stub("alpaca")
    pg = make_stub("polygon")
    yf.program("get_ohlcv", raises(_ServerError("503")))
    al.program("get_ohlcv", raises(_NetworkError("timeout")))
    pg.program("get_ohlcv", returns(sample_ohlc_bars(1)))

    bars = get_ohlcv("MSFT", date(2026, 4, 1), date(2026, 4, 2))

    assert len(bars) == 1
    assert len(yf.call_log) == 1
    assert len(al.call_log) == 1
    assert len(pg.call_log) == 1


# ============== GD-DVR-004 — all vendors fail → AllVendorsFailed ==============


def test_gd_004_all_vendors_fail_raises(make_stub, monkeypatch):
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance,alpaca,polygon")
    yf = make_stub("yfinance")
    al = make_stub("alpaca")
    pg = make_stub("polygon")
    yf.program("get_ohlcv", raises(_RateLimitError("429")))
    al.program("get_ohlcv", raises(_ServerError("502")))
    pg.program("get_ohlcv", raises(_NetworkError("timeout")))

    with pytest.raises(AllVendorsFailed) as exc:
        get_ohlcv("GOOGL", date(2026, 4, 1), date(2026, 4, 2))

    assert len(exc.value.attempts) == 3
    reasons = [r for _, r in exc.value.attempts]
    assert reasons == ["rate_limit", "server_error", "timeout"]


# ============== GD-DVR-005 — 404 does NOT fall back, raises NotFound ==============


def test_gd_005_404_does_not_fall_back(make_stub, monkeypatch):
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance,alpaca,polygon")
    yf = make_stub("yfinance")
    al = make_stub("alpaca")
    yf.program("get_ohlcv", raises(_NotFoundError("404")))
    al.program("get_ohlcv", returns(sample_ohlc_bars(1)))   # would succeed but won't be called

    with pytest.raises(NotFound) as exc:
        get_ohlcv("NOTREAL", date(2026, 4, 1), date(2026, 4, 2))

    assert exc.value.ticker == "NOTREAL"
    assert exc.value.attempted_vendor == "yfinance"
    assert len(yf.call_log) == 1
    assert len(al.call_log) == 0   # NOT called — no fallback on 404


# ============== GD-DVR-006 — 4xx other than 404/429 raises BadRequest ==============


def test_gd_006_400_does_not_fall_back(make_stub, monkeypatch):
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance,alpaca,polygon")
    yf = make_stub("yfinance")
    al = make_stub("alpaca")
    yf.program("get_ohlcv", raises(_BadRequestError("end before start", status_code=400)))
    al.program("get_ohlcv", returns(sample_ohlc_bars(1)))

    with pytest.raises(BadRequest) as exc:
        get_ohlcv("NVDA", date(2030, 4, 1), date(2026, 4, 1))

    assert exc.value.status_code == 400
    assert len(al.call_log) == 0


# ============== GD-DVR-007 — News primary success ==============


def test_gd_007_news_primary_success(make_stub, monkeypatch):
    monkeypatch.setenv("DVR_NEWS_PRIORITY", "benzinga,alpha_vantage,yfinance")
    bz = make_stub("benzinga")
    bz.program("get_news", returns(sample_news_items(3)))

    items = get_news("TSLA", lookback_days=7, top_n=3)

    assert len(items) == 3
    assert len(bz.call_log) == 1


# ============== GD-DVR-008 — news rate-limit fallback ==============


def test_gd_008_news_falls_back(make_stub, monkeypatch):
    monkeypatch.setenv("DVR_NEWS_PRIORITY", "benzinga,alpha_vantage,yfinance")
    bz = make_stub("benzinga")
    av = make_stub("alpha_vantage")
    bz.program("get_news", raises(_RateLimitError("429")))
    av.program("get_news", returns(sample_news_items(1)))

    items = get_news("AAPL")

    assert len(items) == 1
    assert len(bz.call_log) == 1
    assert len(av.call_log) == 1


# ============== GD-DVR-009 — empty result is not a fallback trigger ==============


def test_gd_009_empty_result_not_a_fallback(make_stub, monkeypatch):
    monkeypatch.setenv("DVR_NEWS_PRIORITY", "benzinga,alpha_vantage,yfinance")
    bz = make_stub("benzinga")
    av = make_stub("alpha_vantage")
    bz.program("get_news", returns([]))   # empty success
    av.program("get_news", returns(sample_news_items(1)))

    items = get_news("OBSCURE")

    assert items == []
    assert len(bz.call_log) == 1
    assert len(av.call_log) == 0   # NOT called — empty list is success


# ============== GD-DVR-010 — fundamentals returns standardized snapshot ==============


def test_gd_010_fundamentals_returns_snapshot(make_stub, monkeypatch):
    monkeypatch.setenv("DVR_FUNDAMENTALS_PRIORITY", "yfinance,alpha_vantage,polygon")
    yf = make_stub("yfinance")
    yf.program("get_fundamentals", returns(sample_fundamentals_snapshot("JPM")))

    snap = get_fundamentals("JPM")

    assert snap.ticker == "JPM"
    assert snap.market_cap is not None
    assert snap.sector == "Technology"   # from sample


# ============== GD-DVR-011 — circuit breaker open: skip vendor ==============


def test_gd_011_breaker_open_skips_vendor(make_stub, monkeypatch):
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance,alpaca,polygon")
    yf = make_stub("yfinance")
    al = make_stub("alpaca")
    yf.program("get_ohlcv", returns(sample_ohlc_bars(1)))
    al.program("get_ohlcv", returns(sample_ohlc_bars(1)))

    breakers.force_open("yfinance")

    bars = get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 2))

    assert len(bars) == 1
    assert len(yf.call_log) == 0   # NOT called — breaker open
    assert len(al.call_log) == 1


# ============== GD-DVR-012 — all breakers open → AllVendorsFailed ==============


def test_gd_012_all_breakers_open(make_stub, monkeypatch):
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance,alpaca,polygon")
    make_stub("yfinance")
    make_stub("alpaca")
    make_stub("polygon")

    breakers.force_open("yfinance")
    breakers.force_open("alpaca")
    breakers.force_open("polygon")

    with pytest.raises(AllVendorsFailed) as exc:
        get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 2))

    assert exc.value.primary_reason == "circuit_breaker_open"
    reasons = [r for _, r in exc.value.attempts]
    assert all(r == "circuit_breaker_open" for r in reasons)


# ============== GD-DVR-013 — provider_chain override ==============


def test_gd_013_provider_chain_override(make_stub, monkeypatch):
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance,alpaca,polygon")
    yf = make_stub("yfinance")
    al = make_stub("alpaca")
    pg = make_stub("polygon")
    pg.program("get_ohlcv", returns(sample_ohlc_bars(1)))
    yf.program("get_ohlcv", returns(sample_ohlc_bars(5)))   # default-priority would call this
    al.program("get_ohlcv", returns(sample_ohlc_bars(3)))

    # Override: skip yfinance + alpaca, just use polygon (then yfinance as fallback)
    bars = get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 2), provider_chain=["polygon", "yfinance"])

    assert len(bars) == 1   # got polygon's result, not yfinance's
    assert len(pg.call_log) == 1
    assert len(yf.call_log) == 0
    assert len(al.call_log) == 0   # alpaca is NOT in override chain


# ============== Override chain validates against registered adapters (CTO MIN-3) ==============


def test_unknown_vendor_in_provider_chain_raises_value_error(make_stub):
    make_stub("yfinance")
    with pytest.raises(ValueError, match="Unknown vendor"):
        get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 2), provider_chain=["yfinance", "typo_vendor"])


# ============== Empty chain raises NoVendorsConfigured ==============


def test_empty_provider_chain_raises_no_vendors_configured():
    """Explicitly empty provider_chain → NoVendorsConfigured.

    (Note: empty env-var override is treated as "no override; use default" — see test_chains.py.)
    """
    with pytest.raises(NoVendorsConfigured):
        get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 2), provider_chain=[])
