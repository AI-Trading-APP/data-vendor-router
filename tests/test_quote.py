"""Tests for the get_quote() seam (WL-004-DVR-1).

Contract: specs/watchlist-mvp/contracts/quote-bidask.md
  - MVP $0 default: no quote provider configured -> get_quote() returns None
    cleanly, never raises.
  - A registered quote provider is used when configured via provider_chain
    (or DVR_QUOTE_PRIORITY env var — mirrors the other categories' chains).
  - reset_registry() clears the quote provider registry too.
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from data_vendor_router import get_quote  # noqa: E402
from data_vendor_router import vendors  # noqa: E402
from data_vendor_router.dto import Quote  # noqa: E402


class StubQuoteProvider:
    def __init__(self, name: str, quote: Quote):
        self.name = name
        self._quote = quote
        self.call_log: list[str] = []

    def get_quote(self, ticker: str) -> Quote | None:
        self.call_log.append(ticker)
        return self._quote


def test_no_quote_provider_configured_returns_none():
    """MVP $0 default: no quote provider registered, no chain configured -> None, no exception."""
    assert get_quote("AAPL") is None


def test_registered_quote_provider_returns_its_quote():
    q = Quote(ticker="AAPL", bid=228.35, ask=228.45, last=228.40)
    stub = StubQuoteProvider("stubvendor", q)
    vendors.register_quote_provider("stubvendor", stub)

    result = get_quote("AAPL", provider_chain=["stubvendor"])

    assert result == q
    assert stub.call_log == ["AAPL"]


def test_provider_chain_skips_unregistered_and_uses_next():
    q = Quote(ticker="MSFT", bid=1.0, ask=1.1, last=1.05)
    stub = StubQuoteProvider("real", q)
    vendors.register_quote_provider("real", stub)

    result = get_quote("MSFT", provider_chain=["ghost", "real"])

    assert result == q


def test_reset_registry_clears_quote_provider():
    q = Quote(ticker="NVDA")
    vendors.register_quote_provider("stubvendor", StubQuoteProvider("stubvendor", q))
    assert vendors.is_quote_registered("stubvendor")

    vendors.reset_registry()

    assert not vendors.is_quote_registered("stubvendor")
    assert get_quote("NVDA", provider_chain=["stubvendor"]) is None
