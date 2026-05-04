"""Alpha Vantage adapter — News + Fundamentals.

Paid vendor (free tier exists but heavily rate-limited); HTTP-based.
Requires ALPHA_VANTAGE_API_KEY env var.
Endpoints:
  - GET /query?function=NEWS_SENTIMENT&tickers={ticker}&...
  - GET /query?function=OVERVIEW&symbol={ticker}
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx

from ..dto import FundamentalsSnapshot, NewsItem
from ..exceptions import (
    VendorResponseInvalid,
    _BadRequestError,
    _NetworkError,
    _NotFoundError,
    _RateLimitError,
    _ServerError,
)
from . import register_adapter

VENDOR = "alpha_vantage"

AV_BASE_URL = os.getenv("ALPHA_VANTAGE_BASE_URL", "https://www.alphavantage.co")
AV_TIMEOUT = float(os.getenv("ALPHA_VANTAGE_TIMEOUT", "5.0"))


class AlphaVantageAdapter:
    name = VENDOR

    def get_news(self, ticker: str, lookback_days: int, top_n: int) -> list[NewsItem]:
        api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
        url = f"{AV_BASE_URL}/query"
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": ticker.upper(),
            "limit": min(top_n, 1000),
            "apikey": api_key,
        }
        try:
            with httpx.Client(timeout=AV_TIMEOUT) as client:
                resp = client.get(url, params=params)
        except httpx.HTTPError as e:
            raise _NetworkError(f"alpha_vantage network error: {e}") from e

        self._classify_status(resp.status_code)
        try:
            payload = resp.json()
        except ValueError as e:
            raise VendorResponseInvalid(
                f"alpha_vantage returned non-JSON: {e}",
                vendor=VENDOR, raw_response=resp.text[:500], validation_errors=[{"msg": str(e)}],
            ) from e

        # Alpha Vantage signals rate-limit / quota at HTTP 200 with a "Note" or "Information" key
        if "Note" in payload or "Information" in payload:
            raise _RateLimitError(
                f"alpha_vantage soft rate-limit: {payload.get('Note') or payload.get('Information')}"
            )

        feed = payload.get("feed") or []
        items: list[NewsItem] = []
        for raw in feed[:top_n]:
            try:
                published_at = self._parse_av_time(raw.get("time_published", ""))
                ticker_sentiments = raw.get("ticker_sentiment") or []
                tickers = tuple(t.get("ticker", "") for t in ticker_sentiments if isinstance(t, dict))
                # Pick the sentiment for the requested ticker
                sentiment = None
                for ts in ticker_sentiments:
                    if isinstance(ts, dict) and ts.get("ticker", "").upper() == ticker.upper():
                        try:
                            score = float(ts.get("ticker_sentiment_score", 0))
                            sentiment = max(-1.0, min(1.0, score))
                        except (TypeError, ValueError):
                            pass
                        break
                items.append(NewsItem(
                    title=raw.get("title", ""),
                    url=raw.get("url", ""),
                    published_at=published_at,
                    source=raw.get("source", "AlphaVantage"),
                    summary=raw.get("summary"),
                    sentiment=sentiment,
                    tickers=tickers or (ticker.upper(),),
                ))
            except Exception as e:  # noqa: BLE001
                raise VendorResponseInvalid(
                    f"alpha_vantage news item failed validation: {e}",
                    vendor=VENDOR, raw_response=raw, validation_errors=[{"msg": str(e)}],
                ) from e
        return items

    def get_fundamentals(self, ticker: str) -> FundamentalsSnapshot:
        api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
        url = f"{AV_BASE_URL}/query"
        params = {
            "function": "OVERVIEW",
            "symbol": ticker.upper(),
            "apikey": api_key,
        }
        try:
            with httpx.Client(timeout=AV_TIMEOUT) as client:
                resp = client.get(url, params=params)
        except httpx.HTTPError as e:
            raise _NetworkError(f"alpha_vantage network error: {e}") from e

        self._classify_status(resp.status_code)
        try:
            payload = resp.json()
        except ValueError as e:
            raise VendorResponseInvalid(
                f"alpha_vantage returned non-JSON: {e}",
                vendor=VENDOR, raw_response=resp.text[:500], validation_errors=[{"msg": str(e)}],
            ) from e

        if "Note" in payload or "Information" in payload:
            raise _RateLimitError(
                f"alpha_vantage soft rate-limit: {payload.get('Note') or payload.get('Information')}"
            )
        # Empty/malformed → no overview for this symbol
        if not payload or not payload.get("Symbol"):
            raise _NotFoundError(f"alpha_vantage has no overview for {ticker}")

        try:
            return FundamentalsSnapshot(
                ticker=ticker.upper(),
                market_cap=self._maybe_float(payload.get("MarketCapitalization")),
                pe=self._maybe_float(payload.get("PERatio")),
                dividend_yield=self._maybe_float(payload.get("DividendYield")),
                profit_margin=self._maybe_float(payload.get("ProfitMargin")),
                revenue_ttm=self._maybe_float(payload.get("RevenueTTM")),
                sector=payload.get("Sector"),
                extras={"alpha_vantage": {
                    "industry": payload.get("Industry"),
                    "exchange": payload.get("Exchange"),
                    "country": payload.get("Country"),
                    "fifty_two_week_high": self._maybe_float(payload.get("52WeekHigh")),
                    "fifty_two_week_low": self._maybe_float(payload.get("52WeekLow")),
                }},
            )
        except Exception as e:  # noqa: BLE001
            raise VendorResponseInvalid(
                f"alpha_vantage fundamentals failed validation: {e}",
                vendor=VENDOR,
                raw_response={"keys": list(payload.keys())},
                validation_errors=[{"msg": str(e)}],
            ) from e

    @staticmethod
    def _maybe_float(value):
        """Alpha Vantage returns numeric strings; convert or return None."""
        if value is None or value == "None" or value == "-":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_av_time(value: str) -> datetime:
        # AV format: "20260502T140000"
        if len(value) >= 15:
            try:
                return datetime.strptime(value[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return datetime.now(timezone.utc)

    @staticmethod
    def _classify_status(status_code: int) -> None:
        if status_code == 429:
            raise _RateLimitError("alpha_vantage 429 rate-limited")
        if status_code == 404:
            raise _NotFoundError("alpha_vantage 404")
        if 400 <= status_code < 500:
            raise _BadRequestError(f"alpha_vantage {status_code}", status_code=status_code)
        if status_code >= 500:
            raise _ServerError(f"alpha_vantage {status_code}")


register_adapter(VENDOR, AlphaVantageAdapter())
