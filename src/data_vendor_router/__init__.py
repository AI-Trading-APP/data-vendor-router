from .core import get_fundamentals, get_news, get_ohlcv, get_quote
from .dto import FundamentalsSnapshot, NewsItem, OHLCBar, Quote
from .exceptions import (
    AllVendorsFailed,
    BadRequest,
    DataVendorRouterError,
    NoVendorsConfigured,
    NotFound,
    VendorResponseInvalid,
)
from .vendors import QuoteProvider, register_all_available

# Auto-register every built-in vendor adapter whose SDK / dependency is installed.
# This happens once at package import time. Missing SDKs are skipped silently —
# the chain just won't include those vendors.
register_all_available()

__all__ = [
    "get_ohlcv",
    "get_news",
    "get_fundamentals",
    "get_quote",
    "OHLCBar",
    "NewsItem",
    "FundamentalsSnapshot",
    "Quote",
    "QuoteProvider",
    "DataVendorRouterError",
    "AllVendorsFailed",
    "BadRequest",
    "NotFound",
    "NoVendorsConfigured",
    "VendorResponseInvalid",
]
__version__ = "0.2.2"
