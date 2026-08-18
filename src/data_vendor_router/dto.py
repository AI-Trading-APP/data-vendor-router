"""Pydantic DTOs returned by the router. REQ-DVR-005.

All DTOs are `frozen=True` for caching-friendliness (hashable). The
`extras: dict` escape hatch on FundamentalsSnapshot lets vendor-specific
fields survive normalization without polluting the common shape.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class OHLCBar(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: int = Field(ge=0)


class NewsItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    url: str
    published_at: datetime
    source: str
    summary: Optional[str] = None
    sentiment: Optional[float] = Field(default=None, ge=-1.0, le=1.0)
    tickers: tuple[str, ...] = Field(default_factory=tuple)


class Quote(BaseModel):
    """Single-symbol bid/ask/last quote. WL-004-DVR-1.

    All price fields are nullable — MVP $0 default has no quote vendor
    configured, so `get_quote()` returns `None` and callers render nulls
    (see specs/watchlist-mvp/contracts/quote-bidask.md).
    """

    model_config = ConfigDict(frozen=True)

    ticker: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None


class FundamentalsSnapshot(BaseModel):
    """Superset of common fundamentals fields. Vendor-specific extras via `extras` dict.

    `extras` is namespaced by vendor name (e.g. `extras={"yfinance": {...}, "polygon": {...}}`)
    to avoid silent collisions per CTO MIN-2 carry-forward.
    """

    model_config = ConfigDict(frozen=True)

    ticker: str
    market_cap: Optional[float] = None
    pe: Optional[float] = None
    dividend_yield: Optional[float] = None
    profit_margin: Optional[float] = None
    revenue_ttm: Optional[float] = None
    sector: Optional[str] = None
    extras: dict[str, dict[str, Any]] = Field(default_factory=dict)
