"""Per-category vendor fallback chains. REQ-DVR-002.

Defaults:
  ohlcv:        yfinance → alpaca → polygon
  news:         benzinga → alpha_vantage → yfinance
  fundamentals: yfinance → alpha_vantage → polygon

Override via env var:
  DVR_OHLCV_PRIORITY="alpaca,polygon,yfinance"
  DVR_NEWS_PRIORITY="..."
  DVR_FUNDAMENTALS_PRIORITY="..."

CPO M1 carry-forward: defaults are sensible based on cost (yfinance free,
paid vendors as fallback). Production reliability data should drive v0.2
default reordering. Until then, env-var override is the escape hatch.
"""
from __future__ import annotations

import os

DEFAULT_CHAINS: dict[str, list[str]] = {
    "ohlcv":         ["yfinance", "alpaca", "polygon"],
    "news":          ["benzinga", "alpha_vantage", "yfinance"],
    "fundamentals":  ["yfinance", "alpha_vantage", "polygon"],
}


def get_configured_chain(category: str) -> list[str]:
    """Return the chain for a category, with env-var override taking priority."""
    env_var = f"DVR_{category.upper()}_PRIORITY"
    override = os.getenv(env_var)
    if override:
        return [v.strip() for v in override.split(",") if v.strip()]
    return list(DEFAULT_CHAINS.get(category, []))
