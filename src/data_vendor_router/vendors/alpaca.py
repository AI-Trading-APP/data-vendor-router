"""Alpaca adapter — OHLCV only.

Paid vendor (no retry on transient failures — falls back to next vendor in
the chain on first failure per REQ-DVR-008).

Requires `alpaca-py` package + ALPACA_API_KEY + ALPACA_API_SECRET env vars.
"""
from __future__ import annotations

import os
from datetime import date

from ..dto import OHLCBar
from ..exceptions import (
    VendorResponseInvalid,
    _NetworkError,
    _NotFoundError,
    _RateLimitError,
    _ServerError,
)
from . import register_adapter

# Heavy import — only when adapter is in use.
from alpaca.data import TimeFrame  # noqa: E402
from alpaca.data.historical import StockHistoricalDataClient  # noqa: E402
from alpaca.data.requests import StockBarsRequest  # noqa: E402

VENDOR = "alpaca"


class AlpacaAdapter:
    name = VENDOR

    def __init__(self):
        # Lazy-init client to avoid auth errors at import time
        self._client: StockHistoricalDataClient | None = None

    def _get_client(self) -> StockHistoricalDataClient:
        if self._client is None:
            api_key = os.getenv("ALPACA_API_KEY", "")
            api_secret = os.getenv("ALPACA_API_SECRET", "")
            self._client = StockHistoricalDataClient(api_key, api_secret)
        return self._client

    def get_ohlcv(self, ticker: str, start: date, end: date) -> list[OHLCBar]:
        req = StockBarsRequest(
            symbol_or_symbols=[ticker.upper()],
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
        )
        try:
            client = self._get_client()
            response = client.get_stock_bars(req)
        except Exception as e:  # noqa: BLE001
            # alpaca-py raises various; classify by message / type
            self._classify_and_raise(e)

        # Response shape: {ticker: [Bar, Bar, ...]}
        bars_dict = response.data if hasattr(response, "data") else response
        raw_bars = bars_dict.get(ticker.upper(), [])
        if not raw_bars:
            raise _NotFoundError(f"alpaca has no OHLCV for {ticker} in [{start}, {end}]")

        bars: list[OHLCBar] = []
        for raw in raw_bars:
            try:
                bars.append(OHLCBar(
                    date=raw.timestamp.date() if hasattr(raw.timestamp, "date") else raw.timestamp,
                    open=float(raw.open),
                    high=float(raw.high),
                    low=float(raw.low),
                    close=float(raw.close),
                    volume=int(raw.volume),
                ))
            except Exception as e:  # noqa: BLE001
                raise VendorResponseInvalid(
                    f"alpaca OHLCV bar failed validation: {e}",
                    vendor=VENDOR,
                    raw_response={"timestamp": str(raw.timestamp)},
                    validation_errors=[{"msg": str(e)}],
                ) from e
        return bars

    def _classify_and_raise(self, exc: Exception) -> None:
        msg = str(exc).lower()
        if "429" in msg or "rate" in msg:
            raise _RateLimitError(f"alpaca rate-limited: {exc}") from exc
        if "404" in msg or "not found" in msg:
            raise _NotFoundError(f"alpaca returned 404: {exc}") from exc
        if "5" in str(exc)[:1] and any(s in msg for s in ("500", "502", "503", "504")):
            raise _ServerError(f"alpaca server error: {exc}") from exc
        # Default: treat unknown errors as network (transient → fall back)
        raise _NetworkError(f"alpaca call failed: {exc}") from exc


register_adapter(VENDOR, AlpacaAdapter())
