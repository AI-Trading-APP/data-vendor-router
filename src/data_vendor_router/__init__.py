from .core import get_fundamentals, get_news, get_ohlcv
from .dto import FundamentalsSnapshot, NewsItem, OHLCBar
from .exceptions import (
    AllVendorsFailed,
    BadRequest,
    DataVendorRouterError,
    NoVendorsConfigured,
    NotFound,
    VendorResponseInvalid,
)
from .vendors import register_all_available

# Auto-register every built-in vendor adapter whose SDK / dependency is installed.
# This happens once at package import time. Missing SDKs are skipped silently —
# the chain just won't include those vendors.
register_all_available()

__all__ = [
    "get_ohlcv",
    "get_news",
    "get_fundamentals",
    "OHLCBar",
    "NewsItem",
    "FundamentalsSnapshot",
    "DataVendorRouterError",
    "AllVendorsFailed",
    "BadRequest",
    "NotFound",
    "NoVendorsConfigured",
    "VendorResponseInvalid",
]
__version__ = "0.1.0"
