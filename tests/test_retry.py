import pytest

from data_vendor_router.exceptions import _NetworkError, _RateLimitError, _ServerError
from data_vendor_router.retry import RETRY_ON_TRANSIENT_VENDORS, with_retry


def test_yfinance_is_in_retry_list():
    assert "yfinance" in RETRY_ON_TRANSIENT_VENDORS


def test_yfinance_retries_on_network_error():
    """yfinance gets one retry on _NetworkError."""
    calls = {"n": 0}

    @with_retry("yfinance")
    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _NetworkError("transient")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 2


def test_yfinance_does_NOT_retry_on_rate_limit():
    """REQ-DVR-008: retries are only for network/timeout, never rate-limit."""
    calls = {"n": 0}

    @with_retry("yfinance")
    def rate_limited():
        calls["n"] += 1
        raise _RateLimitError("429")

    with pytest.raises(_RateLimitError):
        rate_limited()
    assert calls["n"] == 1


def test_yfinance_does_NOT_retry_on_server_error():
    calls = {"n": 0}

    @with_retry("yfinance")
    def server_err():
        calls["n"] += 1
        raise _ServerError("500")

    with pytest.raises(_ServerError):
        server_err()
    assert calls["n"] == 1


def test_alpaca_does_NOT_retry():
    """Paid vendors fall back on first transient failure."""
    calls = {"n": 0}

    @with_retry("alpaca")
    def transient():
        calls["n"] += 1
        raise _NetworkError("timeout")

    with pytest.raises(_NetworkError):
        transient()
    assert calls["n"] == 1


def test_yfinance_retry_exhausts_after_one():
    """Two consecutive failures → second propagates."""
    calls = {"n": 0}

    @with_retry("yfinance")
    def always_fails():
        calls["n"] += 1
        raise _NetworkError(f"attempt {calls['n']}")

    with pytest.raises(_NetworkError, match="attempt 2"):
        always_fails()
    assert calls["n"] == 2
