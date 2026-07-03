"""OpenBB Platform adapter — OHLCV + Fundamentals (P1), Macro + News (P2).

Free MIT SDK. OHLCV via FMP/Polygon keys we hold; fundamentals via SEC EDGAR (free)
combined with yfinance profile data (free). Credentials injected from env (NO
~/.openbb_platform/user_settings.json — VPS headless). `obb` is lazy-imported inside
methods (NFR-1 cold-start). Module import is guarded so register_all_available()
silent-skips when the [openbb] extras are absent (NFR-4 / US-4).

Real SDK behaviour (verified 2026-06-30 against openbb==4.7.2 / openbb-core==1.6.13):
  - Umbrella package `openbb>=4.7` required to trigger the SDK build step that wires
    providers into obb.equity.* etc. Provider sub-packages (openbb-core, openbb-sec, …)
    are versioned 1.x, NOT 4.x (the prior pin of openbb-core>=4.3 was impossible).
  - OHLCV: obb.equity.price.historical(symbol, start_date, end_date, provider=…).
    DataFrame index is datetime.date (no .date() method); use str(idx)[:10] path.
  - Fundamentals: obb.equity.fundamental.metrics() does NOT support provider="sec".
    Free fundamentals path = equity.profile(provider="yfinance") for market_cap /
    sector / dividend_yield, plus equity.fundamental.income(provider="sec") for revenue.
  - polygon_api_key IS present on credentials when openbb-polygon is installed.
  - Credential injection via setattr(obb.user.credentials, attr, val) works correctly.
"""
from __future__ import annotations

import os
from datetime import date

from ..dto import FundamentalsSnapshot, OHLCBar
from ..exceptions import (
    VendorResponseInvalid,
    _NetworkError,
    _NotFoundError,
    _RateLimitError,
    _ServerError,
)
from . import register_adapter

VENDOR = "openbb"
_EXPECTED_OHLC_COLS = {"open", "high", "low", "close", "volume"}  # schema canary (NFR-3)

# Module-level guard: if openbb umbrella package is NOT installed, raise ImportError so
# register_all_available() skips this module silently (matches existing pattern).
try:
    import openbb  # noqa: F401  (presence probe only; real obj lazy-imported per call)
except ImportError:  # pragma: no cover
    raise  # re-raise -> register_all_available() catches ImportError and skips


class OpenBBAdapter:
    name = VENDOR

    def __init__(self) -> None:
        # Inject creds ONCE at init (thread-safe re: EC-3 — never mutated per call).
        from openbb import obb
        for cred_attr, env_var in (
            ("fmp_api_key",     "FMP_API_KEY"),
            ("polygon_api_key", "POLYGON_API_KEY"),
            ("fred_api_key",    "FRED_API_KEY"),
        ):
            val = os.getenv(env_var)
            if val:  # AC-2.2: unset env -> no error, skip
                # Only set if the credential field exists on the model
                # (polygon_api_key requires openbb-polygon to be installed)
                if hasattr(obb.user.credentials, cred_attr):
                    setattr(obb.user.credentials, cred_attr, val)

    def get_ohlcv(self, ticker: str, start: date, end: date) -> list[OHLCBar]:
        from openbb import obb
        last_exc = None
        for provider in ("fmp", "polygon"):  # spec: fmp then polygon
            try:
                obbject = obb.equity.price.historical(
                    symbol=ticker,          # EC-6: pass as-is, no reformat
                    start_date=start.isoformat(),
                    end_date=end.isoformat(),
                    provider=provider,
                )
                return self._obbject_to_bars(obbject, ticker)
            except (_NotFoundError, VendorResponseInvalid):
                raise  # terminal — don't try next provider
            except Exception as exc:  # noqa: BLE001
                last_exc = self._translate(exc, ticker)
                if isinstance(last_exc, _NotFoundError):
                    raise last_exc
                continue  # EC-2: try polygon
        raise last_exc or _NetworkError(f"openbb: both providers failed for {ticker}")

    def _obbject_to_bars(self, obbject, ticker: str) -> list[OHLCBar]:
        try:
            df = obbject.to_df()
        except Exception as exc:  # noqa: BLE001
            raise _ServerError(f"openbb to_df failed: {exc}") from exc
        if df is None or df.empty:
            raise _NotFoundError(f"openbb returned no OHLCV for {ticker}")  # AC-1.7 / EC-1
        cols = {c.lower() for c in df.columns}
        if not _EXPECTED_OHLC_COLS.issubset(cols):  # AC-1.8 / NFR-3 / EC-5 schema canary
            raise VendorResponseInvalid(
                f"openbb OHLC schema drift: have {sorted(cols)}",
                vendor=VENDOR,
                raw_response=sorted(cols),
                validation_errors=[{"msg": "missing OHLC columns"}],
            )
        df = df.rename(columns=str.lower)
        bars: list[OHLCBar] = []
        for idx, row in df.iterrows():
            # Index is datetime.date (yfinance/polygon) or datetime (fmp).
            # datetime.date has no .date() method; datetime does. Handle both.
            try:
                if hasattr(idx, "date") and callable(idx.date):
                    bar_date = idx.date()
                else:
                    bar_date = date.fromisoformat(str(idx)[:10])
            except Exception:  # noqa: BLE001
                bar_date = date.fromisoformat(str(idx)[:10])
            try:
                bars.append(OHLCBar(
                    date=bar_date,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row["volume"]),
                ))
            except Exception as exc:  # noqa: BLE001
                raise VendorResponseInvalid(
                    f"openbb bar validation failed: {exc}",
                    vendor=VENDOR,
                    raw_response=str(row)[:500],
                    validation_errors=[{"msg": str(exc)}],
                ) from exc
        return bars

    def get_fundamentals(self, ticker: str) -> FundamentalsSnapshot:
        """Return FundamentalsSnapshot for ticker.

        Free path (no keys required):
          1. obb.equity.profile(provider="yfinance")  → market_cap, sector, dividend_yield
          2. obb.equity.fundamental.income(provider="sec", period="annual", limit=1) → revenue

        NOTE: obb.equity.fundamental.metrics() does NOT accept provider="sec" in the
        real OpenBB v4 SDK (only fmp/intrinio). We use the free endpoints above instead.
        If an FMP key is available, the metrics() call is attempted as a richer fallback
        to fill in pe_ratio and profit_margin.
        """
        from openbb import obb
        snap: FundamentalsSnapshot | None = None

        # --- Step 1: profile via yfinance (free, no key) ---
        try:
            obbject = obb.equity.profile(symbol=ticker, provider="yfinance")
            df = obbject.to_df()
            if df is not None and not df.empty:
                rec = df.iloc[0].to_dict()
                # OpenBB equity.profile(provider="yfinance") returns dividend_yield as
                # a PERCENT value (e.g. 0.38 for 0.38%).  DVR canonical unit is DECIMAL
                # FRACTION (0.0038).  Divide by 100 to normalise; None passes through.
                raw_div_yield = rec.get("dividend_yield")
                div_yield = raw_div_yield / 100.0 if raw_div_yield is not None else None
                snap = FundamentalsSnapshot(
                    ticker=ticker.upper(),
                    market_cap=rec.get("market_cap"),
                    pe=None,              # not available from profile
                    dividend_yield=div_yield,
                    profit_margin=None,   # not available from profile
                    revenue_ttm=None,     # filled below from SEC income
                    sector=rec.get("sector"),
                    extras={"openbb_profile": rec},
                )
        except Exception as exc:  # noqa: BLE001
            translated = self._translate(exc, ticker)
            if isinstance(translated, _NotFoundError):
                raise translated

        # --- Step 2: SEC income statement for revenue (free, no key) ---
        try:
            obbject = obb.equity.fundamental.income(
                symbol=ticker, provider="sec", period="annual", limit=1
            )
            df = obbject.to_df()
            if df is not None and not df.empty:
                rec = df.iloc[0].to_dict()
                revenue = rec.get("total_revenue") or rec.get("operating_revenue")
                if snap is not None:
                    # Enrich the existing snap with revenue
                    snap = FundamentalsSnapshot(
                        ticker=snap.ticker,
                        market_cap=snap.market_cap,
                        pe=snap.pe,
                        dividend_yield=snap.dividend_yield,
                        profit_margin=snap.profit_margin,
                        revenue_ttm=revenue,
                        sector=snap.sector,
                        extras={**snap.extras, "openbb_sec_income": rec},
                    )
                else:
                    snap = FundamentalsSnapshot(
                        ticker=ticker.upper(),
                        market_cap=None,
                        pe=None,
                        dividend_yield=None,
                        profit_margin=None,
                        revenue_ttm=revenue,
                        sector=None,
                        extras={"openbb_sec_income": rec},
                    )
        except Exception as exc:  # noqa: BLE001
            # SEC income is best-effort; don't fail if step 1 succeeded
            if snap is None:
                translated = self._translate(exc, ticker)
                raise translated

        # --- Step 3 (optional): FMP metrics for pe/profit_margin if key available ---
        if os.getenv("FMP_API_KEY") and snap is not None:
            try:
                obbject = obb.equity.fundamental.metrics(symbol=ticker, provider="fmp")
                df = obbject.to_df()
                if df is not None and not df.empty:
                    rec = df.iloc[0].to_dict()
                    snap = FundamentalsSnapshot(
                        ticker=snap.ticker,
                        market_cap=snap.market_cap or rec.get("market_cap"),
                        pe=rec.get("pe_ratio") or rec.get("pe"),
                        dividend_yield=snap.dividend_yield,
                        profit_margin=rec.get("net_profit_margin") or rec.get("profit_margin"),
                        revenue_ttm=snap.revenue_ttm or rec.get("revenue"),
                        sector=snap.sector,
                        extras={**snap.extras, "openbb_fmp_metrics": rec},
                    )
            except Exception:  # noqa: BLE001
                pass  # FMP enrichment is optional — proceed without

        if snap is None:
            raise _NotFoundError(f"openbb fundamentals unavailable for {ticker}")

        return snap

    @staticmethod
    def _translate(exc: Exception, ticker: str) -> Exception:
        name = type(exc).__name__.lower()
        msg = str(exc).lower()
        if "429" in msg or ("rate" in msg and "limit" in msg) or "ratelimit" in name:
            return _RateLimitError(f"openbb rate-limited: {exc}")
        if any(k in msg for k in ("404", "not found", "no data", "empty")):
            return _NotFoundError(f"openbb not found for {ticker}: {exc}")
        if any(k in msg for k in ("timeout", "connection", "network", "ssl", "dns")) \
                or name in ("connecterror", "timeout", "connectionerror", "readtimeout"):
            return _NetworkError(f"openbb network error: {exc}")
        if "500" in msg or "502" in msg or "503" in msg or "server" in msg:
            return _ServerError(f"openbb server error: {exc}")
        return _NetworkError(f"openbb transient error: {exc}")  # default → fallback-safe


import logging  # noqa: E402
register_adapter(VENDOR, OpenBBAdapter())
logging.getLogger(__name__).info("openbb adapter registered")  # AC-4.2
