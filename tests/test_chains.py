from data_vendor_router.chains import DEFAULT_CHAINS, get_configured_chain


def test_default_ohlcv_chain():
    """DVR-3 / v0.1.3: polygon is primary; yfinance demoted to last (IP-blocked on VPS)."""
    assert get_configured_chain("ohlcv") == ["polygon", "tiingo", "alpaca", "yfinance"]


def test_default_ohlcv_chain_polygon_first():
    """DVR-3: polygon must be the first OHLCV vendor in the default chain."""
    chain = get_configured_chain("ohlcv")
    assert chain[0] == "polygon", f"Expected polygon first, got {chain[0]!r}"


def test_default_ohlcv_chain_yfinance_last():
    """DVR-3: yfinance must be the last OHLCV vendor in the default chain (inert VPS fallback)."""
    chain = get_configured_chain("ohlcv")
    assert chain[-1] == "yfinance", f"Expected yfinance last, got {chain[-1]!r}"


def test_default_news_chain():
    """v0.1.2: Tiingo slotted right behind NewsAPI as second free-tier news source."""
    assert get_configured_chain("news") == ["newsapi", "tiingo", "benzinga", "alpha_vantage", "yfinance"]


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
