"""Tiingo adapter — News + OHLCV.

Added in v0.1.2 to give NewsService and PE a second free-tier vendor that
covers BOTH news and EOD bars. Helps when NewsAPI hits its 100/day cap or
Alpaca free-tier IEX has gaps. Tiingo free tier is 1000 req/day.

Auth: `Authorization: Token <key>` header (preferred over query string).
Requires TIINGO_API_KEY env var.

Endpoints:
  News:  GET https://api.tiingo.com/tiingo/news?tickers=AAPL&limit=10
  OHLCV: GET https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate=...&endDate=...
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone

import httpx

from ..dto import NewsItem, OHLCBar
from ..exceptions import (
    VendorResponseInvalid,
    _BadRequestError,
    _NetworkError,
    _NotFoundError,
    _RateLimitError,
    _ServerError,
)
from . import register_adapter

VENDOR = "tiingo"

TIINGO_BASE_URL = os.getenv("TIINGO_BASE_URL", "https://api.tiingo.com")
TIINGO_TIMEOUT = float(os.getenv("TIINGO_TIMEOUT", "5.0"))


class TiingoAdapter:
    name = VENDOR

    # ---------- News ----------
    def get_news(self, ticker: str, lookback_days: int, top_n: int) -> list[NewsItem]:
        api_key = os.getenv("TIINGO_API_KEY", "")
        params = {
            "tickers": ticker.lower(),  # Tiingo expects lowercase
            "limit": min(top_n, 100),  # API max 100
            "sortBy": "publishedDate",
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Token {api_key}",
        }
        url = f"{TIINGO_BASE_URL}/tiingo/news"
        try:
            with httpx.Client(timeout=TIINGO_TIMEOUT) as client:
                resp = client.get(url, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise _NetworkError(f"tiingo network error: {e}") from e

        self._classify_status(resp.status_code)
        try:
            payload = resp.json()
        except ValueError as e:
            raise VendorResponseInvalid(
                f"tiingo returned non-JSON: {e}",
                vendor=VENDOR, raw_response=resp.text[:500],
                validation_errors=[{"msg": str(e)}],
            ) from e

        # Tiingo News returns a JSON array, NOT a dict. An error becomes a 4xx
        # status (handled above) or a dict with "detail" / "message".
        if isinstance(payload, dict):
            msg = payload.get("detail") or payload.get("message") or str(payload)[:200]
            raise VendorResponseInvalid(
                f"tiingo news returned dict instead of array: {msg}",
                vendor=VENDOR, raw_response=payload,
                validation_errors=[{"msg": msg}],
            )
        if not isinstance(payload, list):
            raise VendorResponseInvalid(
                "tiingo news response not a list",
                vendor=VENDOR, raw_response=str(payload)[:500],
                validation_errors=[{"msg": "expected JSON array"}],
            )

        items: list[NewsItem] = []
        for raw in payload[:top_n]:
            try:
                published_str = raw.get("publishedDate") or raw.get("crawlDate") or ""
                published_at = self._parse_iso8601(published_str) if published_str else datetime.now(timezone.utc)
                tickers_raw = raw.get("tickers") or [ticker.upper()]
                tickers_tup = tuple(t.upper() for t in tickers_raw) if tickers_raw else (ticker.upper(),)
                items.append(NewsItem(
                    title=raw.get("title", ""),
                    url=raw.get("url", ""),
                    published_at=published_at,
                    source=raw.get("source") or "Tiingo",
                    summary=raw.get("description"),
                    sentiment=None,  # Tiingo doesn't expose sentiment on free tier
                    tickers=tickers_tup,
                ))
            except Exception as e:  # noqa: BLE001
                raise VendorResponseInvalid(
                    f"tiingo article failed validation: {e}",
                    vendor=VENDOR, raw_response=raw,
                    validation_errors=[{"msg": str(e)}],
                ) from e
        return items

    # ---------- OHLCV ----------
    def get_ohlcv(self, ticker: str, start: date, end: date) -> list[OHLCBar]:
        api_key = os.getenv("TIINGO_API_KEY", "")
        params = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "format": "json",
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Token {api_key}",
        }
        url = f"{TIINGO_BASE_URL}/tiingo/daily/{ticker.upper()}/prices"
        try:
            with httpx.Client(timeout=TIINGO_TIMEOUT) as client:
                resp = client.get(url, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise _NetworkError(f"tiingo network error: {e}") from e

        self._classify_status(resp.status_code)
        try:
            payload = resp.json()
        except ValueError as e:
            raise VendorResponseInvalid(
                f"tiingo returned non-JSON: {e}",
                vendor=VENDOR, raw_response=resp.text[:500],
                validation_errors=[{"msg": str(e)}],
            ) from e

        if isinstance(payload, dict):
            # Tiingo returns {"detail": "Error: ..."} on unknown ticker on some paths
            msg = payload.get("detail") or payload.get("message") or str(payload)[:200]
            raise _NotFoundError(f"tiingo OHLCV: {msg}")
        if not isinstance(payload, list) or not payload:
            raise _NotFoundError(f"tiingo has no OHLCV for {ticker} in [{start}, {end}]")

        bars: list[OHLCBar] = []
        for raw in payload:
            try:
                bar_date_str = raw.get("date", "")
                # Tiingo returns "2026-05-29T00:00:00.000Z"
                bar_date = self._parse_iso8601(bar_date_str).date() if bar_date_str else None
                if bar_date is None:
                    raise ValueError(f"missing date in bar: {raw}")
                bars.append(OHLCBar(
                    date=bar_date,
                    open=float(raw.get("adjOpen") or raw["open"]),
                    high=float(raw.get("adjHigh") or raw["high"]),
                    low=float(raw.get("adjLow") or raw["low"]),
                    close=float(raw.get("adjClose") or raw["close"]),
                    volume=int(raw.get("adjVolume") or raw.get("volume", 0)),
                ))
            except Exception as e:  # noqa: BLE001
                raise VendorResponseInvalid(
                    f"tiingo OHLCV bar failed validation: {e}",
                    vendor=VENDOR, raw_response=raw,
                    validation_errors=[{"msg": str(e)}],
                ) from e
        return bars

    # ---------- Helpers ----------
    @staticmethod
    def _parse_iso8601(value: str) -> datetime:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)

    @staticmethod
    def _classify_status(status_code: int) -> None:
        if status_code == 429:
            raise _RateLimitError("tiingo 429 rate-limited")
        if status_code == 404:
            raise _NotFoundError("tiingo 404")
        if status_code in (401, 403):
            raise _BadRequestError(f"tiingo {status_code} auth", status_code=status_code)
        if 400 <= status_code < 500:
            raise _BadRequestError(f"tiingo {status_code}", status_code=status_code)
        if status_code >= 500:
            raise _ServerError(f"tiingo {status_code}")


register_adapter(VENDOR, TiingoAdapter())
