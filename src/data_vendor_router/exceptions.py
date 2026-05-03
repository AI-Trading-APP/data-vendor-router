"""Typed exception hierarchy for the data vendor router."""
from __future__ import annotations

from typing import Any


class DataVendorRouterError(Exception):
    """Base for all router-raised errors."""


class NoVendorsConfigured(DataVendorRouterError):
    """Raised when a category has no vendors configured (empty chain)."""


class AllVendorsFailed(DataVendorRouterError):
    """Every vendor in the chain failed (after fallback). REQ-DVR-002 / REQ-DVR-003."""

    def __init__(
        self,
        message: str,
        *,
        attempts: list[tuple[str, str]],
        primary_reason: str = "unknown",
    ) -> None:
        super().__init__(message)
        self.attempts = attempts  # [(vendor_name, reason), ...]
        self.primary_reason = primary_reason


class NotFound(DataVendorRouterError):
    """Vendor returned 404; ticker doesn't exist. Does NOT trigger fallback. REQ-DVR-003."""

    def __init__(self, message: str, *, ticker: str, attempted_vendor: str) -> None:
        super().__init__(message)
        self.ticker = ticker
        self.attempted_vendor = attempted_vendor


class BadRequest(DataVendorRouterError):
    """Vendor returned 4xx (other than 404 / 429); caller's input is wrong. REQ-DVR-003."""

    def __init__(self, message: str, *, attempted_vendor: str, status_code: int) -> None:
        super().__init__(message)
        self.attempted_vendor = attempted_vendor
        self.status_code = status_code


class VendorResponseInvalid(DataVendorRouterError):
    """Vendor returned malformed data (DTO validation failed). Does NOT trigger fallback.

    REQ-DVR-003 / REQ-DVR-005. Raising rather than falling back preserves bug visibility —
    if a vendor's contract changes, we want to know, not silently rotate to the next.
    """

    def __init__(
        self,
        message: str,
        *,
        vendor: str,
        raw_response: Any,
        validation_errors: list[dict],
    ) -> None:
        super().__init__(message)
        self.vendor = vendor
        self.raw_response = raw_response
        self.validation_errors = validation_errors


# ---------- Internal vendor-side exceptions (router translates to public types) ----------


class _RateLimitError(Exception):
    """Adapter raises this on HTTP 429."""


class _ServerError(Exception):
    """Adapter raises this on HTTP 5xx."""


class _NetworkError(Exception):
    """Adapter raises this on connection errors / timeouts."""


class _NotFoundError(Exception):
    """Adapter raises this on HTTP 404."""


class _BadRequestError(Exception):
    """Adapter raises this on HTTP 4xx other than 429 / 404."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code
