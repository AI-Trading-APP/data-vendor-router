"""Polygon adapter — OHLCV + Fundamentals.

Paid vendor; HTTP-based (uses httpx rather than `polygon-api-client` SDK
to keep deps minimal and error-handling consistent with other adapters).

Requires POLYGON_API_KEY env var.
Endpoints:
  - GET /v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}
  - GET /v3/reference/tickers/{ticker}
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone

import httpx

from ..dto import FundamentalsSnapshot, OHLCBar
from ..exceptions import (
    VendorResponseInvalid,
    _BadRequestError,
    _NetworkError,
    _NotFoundError,
    _RateLimitError,
    _ServerError,
)
from . import register_adapter

VENDOR = "polygon"

POLYGON_BASE_URL = os.getenv("POLYGON_BASE_URL", "https://api.polygon.io")
POLYGON_TIMEOUT = float(os.getenv("POLYGON_TIMEOUT", "5.0"))


class PolygonAdapter:
    name = VENDOR

    def get_ohlcv(self, ticker: str, start: date, end: date) -> list[OHLCBar]:
        api_key = os.getenv("POLYGON_API_KEY", "")
        url = f"{POLYGON_BASE_URL}/v2/aggs/ticker/{ticker.upper()}/range/1/day/{start.isoformat()}/{end.isoformat()}"
        params = {"apiKey": api_key, "adjusted": "true", "sort": "asc"}
        try:
            with httpx.Client(timeout=POLYGON_TIMEOUT) as client:
                resp = client.get(url, params=params)
        except httpx.HTTPError as e:
            raise _NetworkError(f"polygon network error: {e}") from e

        self._classify_status(resp.status_code)
        try:
            payload = resp.json()
        except ValueError as e:
            raise VendorResponseInvalid(
                f"polygon returned non-JSON: {e}",
                vendor=VENDOR, raw_response=resp.text[:500], validation_errors=[{"msg": str(e)}],
            ) from e

        results = payload.get("results") or []
        if not results:
            raise _NotFoundError(f"polygon has no OHLCV for {ticker} in [{start}, {end}]")

        bars: list[OHLCBar] = []
        for raw in results:
            try:
                # Polygon timestamp `t` is unix-ms
                ts_ms = raw["t"]
                bar_date = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date()
                bars.append(OHLCBar(
                    date=bar_date,
                    open=float(raw["o"]),
                    high=float(raw["h"]),
                    low=float(raw["l"]),
                    close=float(raw["c"]),
                    volume=int(raw["v"]),
                ))
            except Exception as e:  # noqa: BLE001
                raise VendorResponseInvalid(
                    f"polygon OHLCV bar failed validation: {e}",
                    vendor=VENDOR, raw_response=raw, validation_errors=[{"msg": str(e)}],
                ) from e
        return bars

    def get_fundamentals(self, ticker: str) -> FundamentalsSnapshot:
        api_key = os.getenv("POLYGON_API_KEY", "")
        url = f"{POLYGON_BASE_URL}/v3/reference/tickers/{ticker.upper()}"
        params = {"apiKey": api_key}
        try:
            with httpx.Client(timeout=POLYGON_TIMEOUT) as client:
                resp = client.get(url, params=params)
        except httpx.HTTPError as e:
            raise _NetworkError(f"polygon network error: {e}") from e

        self._classify_status(resp.status_code)
        try:
            payload = resp.json()
        except ValueError as e:
            raise VendorResponseInvalid(
                f"polygon returned non-JSON: {e}",
                vendor=VENDOR, raw_response=resp.text[:500], validation_errors=[{"msg": str(e)}],
            ) from e

        results = payload.get("results")
        if not results:
            raise _NotFoundError(f"polygon has no ticker details for {ticker}")

        try:
            return FundamentalsSnapshot(
                ticker=ticker.upper(),
                market_cap=results.get("market_cap"),
                pe=None,  # Polygon ticker-details doesn't expose PE directly
                dividend_yield=None,
                profit_margin=None,
                revenue_ttm=None,
                sector=results.get("sic_description"),
                extras={"polygon": {
                    "share_class_shares_outstanding": results.get("share_class_shares_outstanding"),
                    "weighted_shares_outstanding": results.get("weighted_shares_outstanding"),
                    "primary_exchange": results.get("primary_exchange"),
                    "homepage_url": results.get("homepage_url"),
                }},
            )
        except Exception as e:  # noqa: BLE001
            raise VendorResponseInvalid(
                f"polygon fundamentals failed validation: {e}",
                vendor=VENDOR, raw_response=results, validation_errors=[{"msg": str(e)}],
            ) from e

    @staticmethod
    def _classify_status(status_code: int) -> None:
        if status_code == 429:
            raise _RateLimitError("polygon 429 rate-limited")
        if status_code == 404:
            raise _NotFoundError("polygon 404")
        if 400 <= status_code < 500:
            raise _BadRequestError(f"polygon {status_code}", status_code=status_code)
        if status_code >= 500:
            raise _ServerError(f"polygon {status_code}")


register_adapter(VENDOR, PolygonAdapter())
