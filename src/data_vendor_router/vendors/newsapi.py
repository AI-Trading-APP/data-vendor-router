"""NewsAPI adapter — News only.

Added in v0.1.1 to enable NewsService consumer migration. NewsService is
the platform's primary news consumer and uses NewsAPI today (the BB3 spec
incorrectly assumed Benzinga; surfaced during PR-C scoping).

Free tier: 100 req/day; paid tiers higher. Requires NEWSAPI_KEY env var.
Endpoint: https://newsapi.org/v2/everything
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

VENDOR = "newsapi"

NEWSAPI_BASE_URL = os.getenv("NEWSAPI_BASE_URL", "https://newsapi.org/v2")
NEWSAPI_TIMEOUT = float(os.getenv("NEWSAPI_TIMEOUT", "5.0"))


class NewsAPIAdapter:
    name = VENDOR

    def get_news(self, ticker: str, lookback_days: int, top_n: int) -> list[NewsItem]:
        api_key = os.getenv("NEWSAPI_KEY", "")
        from_date = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        params = {
            "apiKey": api_key,
            "q": f"{ticker} stock",
            "from": from_date,
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": min(top_n, 100),  # NewsAPI max is 100/page
        }
        url = f"{NEWSAPI_BASE_URL}/everything"
        try:
            with httpx.Client(timeout=NEWSAPI_TIMEOUT) as client:
                resp = client.get(url, params=params, headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            raise _NetworkError(f"newsapi network error: {e}") from e

        self._classify_status(resp.status_code)
        try:
            payload = resp.json()
        except ValueError as e:
            raise VendorResponseInvalid(
                f"newsapi returned non-JSON: {e}",
                vendor=VENDOR, raw_response=resp.text[:500], validation_errors=[{"msg": str(e)}],
            ) from e

        # NewsAPI also signals errors via 200-status with status="error" body
        if isinstance(payload, dict) and payload.get("status") == "error":
            code = payload.get("code", "")
            message = payload.get("message", "")
            if code == "rateLimited":
                raise _RateLimitError(f"newsapi rate-limited: {message}")
            if code == "apiKeyInvalid":
                raise _BadRequestError(f"newsapi {code}: {message}", status_code=401)
            raise VendorResponseInvalid(
                f"newsapi error: {code}: {message}",
                vendor=VENDOR, raw_response=payload, validation_errors=[{"msg": message}],
            )

        articles = payload.get("articles") if isinstance(payload, dict) else None
        if articles is None:
            raise VendorResponseInvalid(
                "newsapi response missing 'articles' field",
                vendor=VENDOR, raw_response=str(payload)[:500],
                validation_errors=[{"msg": "expected dict with 'articles' key"}],
            )

        items: list[NewsItem] = []
        for raw in articles[:top_n]:
            try:
                published_str = raw.get("publishedAt") or ""
                published_at = self._parse_iso8601(published_str) if published_str else datetime.now(timezone.utc)
                source_obj = raw.get("source") or {}
                source_name = source_obj.get("name") if isinstance(source_obj, dict) else "NewsAPI"
                items.append(NewsItem(
                    title=raw.get("title", ""),
                    url=raw.get("url", ""),
                    published_at=published_at,
                    source=source_name or "NewsAPI",
                    summary=raw.get("description"),
                    sentiment=None,  # NewsAPI doesn't provide sentiment
                    tickers=(ticker.upper(),),
                ))
            except Exception as e:  # noqa: BLE001
                raise VendorResponseInvalid(
                    f"newsapi article failed validation: {e}",
                    vendor=VENDOR, raw_response=raw, validation_errors=[{"msg": str(e)}],
                ) from e
        return items

    @staticmethod
    def _parse_iso8601(value: str) -> datetime:
        # NewsAPI returns ISO 8601 with Z suffix or +00:00 offset
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)

    @staticmethod
    def _classify_status(status_code: int) -> None:
        if status_code == 429:
            raise _RateLimitError("newsapi 429 rate-limited")
        if status_code == 404:
            raise _NotFoundError("newsapi 404")
        if 400 <= status_code < 500:
            raise _BadRequestError(f"newsapi {status_code}", status_code=status_code)
        if status_code >= 500:
            raise _ServerError(f"newsapi {status_code}")


register_adapter(VENDOR, NewsAPIAdapter())
