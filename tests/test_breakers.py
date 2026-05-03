from data_vendor_router import breakers


def test_get_breaker_creates_lazily():
    b = breakers.get_breaker("yfinance")
    assert b.name == "vendor.yfinance"
    assert b.fail_max == 5


def test_get_breaker_returns_same_instance():
    a = breakers.get_breaker("alpaca")
    b = breakers.get_breaker("alpaca")
    assert a is b


def test_is_open_default_false():
    assert breakers.is_open("polygon") is False


def test_force_open_then_is_open_true():
    breakers.force_open("polygon")
    assert breakers.is_open("polygon") is True


def test_reset_all_clears_state():
    breakers.force_open("benzinga")
    assert breakers.is_open("benzinga")
    breakers.reset_all()
    # After reset, breaker is no longer in registry; fresh call creates a new closed breaker
    assert breakers.is_open("benzinga") is False
