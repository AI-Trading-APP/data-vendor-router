"""Per-category vendor fallback chains. REQ-DVR-002.

Defaults:
  ohlcv:        polygon → tiingo → alpaca → yfinance
  news:         newsapi → tiingo → benzinga → alpha_vantage → yfinance
  fundamentals: yfinance → alpha_vantage → polygon

Override via env var:
  DVR_OHLCV_PRIORITY="alpaca,polygon,yfinance"
  DVR_NEWS_PRIORITY="..."
  DVR_FUNDAMENTALS_PRIORITY="..."

DVR-3: polygon is now the primary OHLCV vendor by default. yfinance moved to
last position — it is IP-blocked on the VPS (Yahoo throttles datacenter IPs)
and should only ever be an inert final fallback. The env-var override
(DVR_OHLCV_PRIORITY) still takes full precedence over this default.
"""
from __future__ import annotations

import os

DEFAULT_CHAINS: dict[str, list[str]] = {
    # DVR-3 (v0.1.3): polygon promoted to primary OHLCV vendor.
    # yfinance demoted to last fallback — IP-blocked on VPS datacenter IPs.
    # Tiingo stays as second free-tier option; Alpaca requires SIP key.
    "ohlcv":         ["polygon", "tiingo", "alpaca", "yfinance"],
    # NewsAPI added as primary in v0.1.1 — NewsService's actual primary today.
    # Tiingo added in v0.1.2 right behind NewsAPI: another free 1000/day source
    # with ticker-tagged articles, useful when NewsAPI hits its 100/day cap.
    # Benzinga/Alpha Vantage stay as fallbacks for deployments with their keys;
    # yfinance scrape is last resort (free, but lowest data quality).
    "news":          ["newsapi", "tiingo", "benzinga", "alpha_vantage", "yfinance"],
    "fundamentals":  ["yfinance", "alpha_vantage", "polygon"],
}


def get_configured_chain(category: str) -> list[str]:
    """Return the chain for a category, with env-var override taking priority."""
    env_var = f"DVR_{category.upper()}_PRIORITY"
    override = os.getenv(env_var)
    if override:
        return [v.strip() for v in override.split(",") if v.strip()]
    return list(DEFAULT_CHAINS.get(category, []))
