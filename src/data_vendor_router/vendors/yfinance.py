"""yfinance adapter — OHLCV + News + Fundamentals.

Free vendor; flaky on transient failures (REQ-DVR-008 puts it in
RETRY_ON_TRANSIENT_VENDORS for one-immediate-retry on _NetworkError).

Requires `yfinance` package (install via the [vendors] extra).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from ..dto import FundamentalsSnapshot, NewsItem, OHLCBar
from ..exceptions import (
    VendorResponseInvalid,
    _NetworkError,
    _NotFoundError,
    _RateLimitError,
)
from . import register_adapter

# Heavy import — only needed when this adapter is in use.
import yfinance as yf  # noqa: E402

if TYPE_CHECKING:
    pass

VENDOR = "yfinance"


class YFinanceAdapter:
    name = VENDOR

    def get_ohlcv(self, ticker: str, start: date, end: date) -> list[OHLCBar]:
        try:
            tkr = yf.Ticker(ticker)
            df = tkr.history(start=start, end=end, auto_adjust=True)
        except Exception as e:  # noqa: BLE001
            # yfinance raises a wide variety of exceptions; treat all as transient
            raise _NetworkError(f"yfinance.history failed for {ticker}: {e}") from e

        if df is None or df.empty:
            raise _NotFoundError(f"yfinance has no OHLCV for {ticker} in [{start}, {end}]")

        bars: list[OHLCBar] = []
        for ts, row in df.iterrows():
            try:
                bars.append(OHLCBar(
                    date=ts.date() if hasattr(ts, "date") else ts,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]),
                ))
            except Exception as e:  # noqa: BLE001 — DTO validation failure
                raise VendorResponseInvalid(
                    f"yfinance OHLCV row failed validation: {e}",
                    vendor=VENDOR,
                    raw_response={"row_index": str(ts), "row_keys": list(row.keys())},
                    validation_errors=[{"msg": str(e)}],
                ) from e
        return bars

    def get_news(self, ticker: str, lookback_days: int, top_n: int) -> list[NewsItem]:
        try:
            tkr = yf.Ticker(ticker)
            raw_items = tkr.news or []
        except Exception as e:  # noqa: BLE001
            raise _NetworkError(f"yfinance.news failed for {ticker}: {e}") from e

        items: list[NewsItem] = []
        for raw in raw_items[:top_n]:
            # yfinance news shape: {"title", "link", "providerPublishTime" (epoch), "publisher", ...}
            try:
                published_ts = raw.get("providerPublishTime")
                published_at = (
                    datetime.fromtimestamp(published_ts, tz=timezone.utc)
                    if published_ts else datetime.now(timezone.utc)
                )
                items.append(NewsItem(
                    title=raw.get("title", ""),
                    url=raw.get("link", ""),
                    published_at=published_at,
                    source=raw.get("publisher", VENDOR),
                    summary=raw.get("summary"),
                    sentiment=None,  # yfinance doesn't provide sentiment
                    tickers=tuple(raw.get("relatedTickers", [ticker])),
                ))
            except Exception as e:  # noqa: BLE001
                raise VendorResponseInvalid(
                    f"yfinance news item failed validation: {e}",
                    vendor=VENDOR, raw_response=raw, validation_errors=[{"msg": str(e)}],
                ) from e
        return items

    def get_fundamentals(self, ticker: str) -> FundamentalsSnapshot:
        try:
            tkr = yf.Ticker(ticker)
            info = tkr.info or {}
        except Exception as e:  # noqa: BLE001
            raise _NetworkError(f"yfinance.info failed for {ticker}: {e}") from e

        if not info or not info.get("symbol"):
            raise _NotFoundError(f"yfinance has no fundamentals for {ticker}")

        try:
            return FundamentalsSnapshot(
                ticker=ticker.upper(),
                market_cap=info.get("marketCap"),
                pe=info.get("trailingPE"),
                dividend_yield=info.get("dividendYield"),
                profit_margin=info.get("profitMargins"),
                revenue_ttm=info.get("totalRevenue"),
                sector=info.get("sector"),
                extras={"yfinance": {
                    "shares_outstanding": info.get("sharesOutstanding"),
                    "beta": info.get("beta"),
                    "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                    "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                }},
            )
        except Exception as e:  # noqa: BLE001
            raise VendorResponseInvalid(
                f"yfinance fundamentals failed validation: {e}",
                vendor=VENDOR, raw_response={"info_keys": list(info.keys())},
                validation_errors=[{"msg": str(e)}],
            ) from e


register_adapter(VENDOR, YFinanceAdapter())
