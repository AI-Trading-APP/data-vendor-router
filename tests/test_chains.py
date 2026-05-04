import os

import pytest

from data_vendor_router.chains import DEFAULT_CHAINS, get_configured_chain


def test_default_ohlcv_chain():
    assert get_configured_chain("ohlcv") == ["yfinance", "alpaca", "polygon"]


def test_default_news_chain():
    """v0.1.1: NewsAPI promoted to primary; Benzinga / Alpha Vantage / yfinance fall back."""
    assert get_configured_chain("news") == ["newsapi", "benzinga", "alpha_vantage", "yfinance"]


def test_default_fundamentals_chain():
    assert get_configured_chain("fundamentals") == ["yfinance", "alpha_vantage", "polygon"]


def test_unknown_category_returns_empty_list():
    assert get_configured_chain("unknown_category") == []


def test_env_var_override(monkeypatch):
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "polygon,alpaca,yfinance")
    assert get_configured_chain("ohlcv") == ["polygon", "alpaca", "yfinance"]


def test_env_var_override_strips_whitespace_and_filters_empties(monkeypatch):
    monkeypatch.setenv("DVR_NEWS_PRIORITY", "  alpha_vantage , , benzinga  ")
    assert get_configured_chain("news") == ["alpha_vantage", "benzinga"]


def test_default_chains_dict_contains_all_three_categories():
    assert set(DEFAULT_CHAINS) == {"ohlcv", "news", "fundamentals"}
