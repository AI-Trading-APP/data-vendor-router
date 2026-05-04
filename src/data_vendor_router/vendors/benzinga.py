"""Benzinga adapter — News only.

Paid vendor; HTTP-based (no official Python SDK).
Requires BENZINGA_API_KEY env var. Endpoint: api.benzinga.com/api/v2/news.

Per BB3 spec REQ-DVR-010 / CTO M5 carry-forward: confirmed against
NewsService's existing Benzinga usage pattern (token query param + standard
news shape with title/url/created/teaser/stocks fields).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import httpx

from ..dto import NewsItem
from ..exceptions import (
    VendorResponseInvalid,
    _BadRequestError,
    _NetworkError,
    _NotFoundError,
    _RateLimitError,
    _ServerError,
)
from . import register_adapter

VENDOR = "benzinga"

BENZINGA_BASE_URL = os.getenv("BENZINGA_BASE_URL", "https://api.benzinga.com/api/v2")
BENZINGA_TIMEOUT = float(os.getenv("BENZINGA_TIMEOUT", "5.0"))


class BenzingaAdapter:
    name = VENDOR

    def get_news(self, ticker: str, lookback_days: int, top_n: int) -> list[NewsItem]:
        api_key = os.getenv("BENZINGA_API_KEY", "")
        date_from = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        params = {
            "token": api_key,
            "tickers": ticker.upper(),
            "dateFrom": date_from,
            "pageSize": top_n,
            "displayOutput": "full",
        }
        url = f"{BENZINGA_BASE_URL}/news"
        try:
            with httpx.Client(timeout=BENZINGA_TIMEOUT) as client:
                resp = client.get(url, params=params, headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            raise _NetworkError(f"benzinga network error: {e}") from e

        self._classify_status(resp.status_code)
        try:
            payload = resp.json()
        except ValueError as e:
            raise VendorResponseInvalid(
                f"benzinga returned non-JSON: {e}",
                vendor=VENDOR, raw_response=resp.text[:500], validation_errors=[{"msg": str(e)}],
            ) from e

        # Benzinga shape: list of {id, title, url, teaser, created, stocks: [{name}, ...], ...}
        if not isinstance(payload, list):
            raise VendorResponseInvalid(
                "benzinga response is not a list",
                vendor=VENDOR, raw_response=str(payload)[:500],
                validation_errors=[{"msg": "expected JSON array"}],
            )

        items: list[NewsItem] = []
        for raw in payload[:top_n]:
            try:
                created = raw.get("created")
                published_at = self._parse_created(created) if created else datetime.now(timezone.utc)
                stocks = raw.get("stocks") or []
                tickers = tuple(s.get("name", "") for s in stocks if isinstance(s, dict))
                items.append(NewsItem(
                    title=raw.get("title", ""),
                    url=raw.get("url", ""),
                    published_at=published_at,
                    source="Benzinga",
                    summary=raw.get("teaser"),
                    sentiment=None,
                    tickers=tickers or (ticker.upper(),),
                ))
            except Exception as e:  # noqa: BLE001
                raise VendorResponseInvalid(
                    f"benzinga news item failed validation: {e}",
                    vendor=VENDOR, raw_response=raw, validation_errors=[{"msg": str(e)}],
                ) from e
        return items

    @staticmethod
    def _parse_created(value: str) -> datetime:
        # Benzinga returns RFC1123-style timestamps like "Fri, 02 May 2026 14:00:00 -0400"
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(value)
        except Exception:  # noqa: BLE001
            return datetime.now(timezone.utc)

    @staticmethod
    def _classify_status(status_code: int) -> None:
        if status_code == 429:
            raise _RateLimitError("benzinga 429 rate-limited")
        if status_code == 404:
            raise _NotFoundError("benzinga 404")
        if 400 <= status_code < 500:
            raise _BadRequestError(f"benzinga {status_code}", status_code=status_code)
        if status_code >= 500:
            raise _ServerError(f"benzinga {status_code}")


register_adapter(VENDOR, BenzingaAdapter())
