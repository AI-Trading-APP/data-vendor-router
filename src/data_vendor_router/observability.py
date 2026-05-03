"""OpenTelemetry + Prometheus instrumentation. REQ-DVR-007."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import trace
from prometheus_client import Counter, Gauge, Histogram

# ---------- Prometheus metrics ----------

calls_total = Counter(
    "data_vendor_router_calls_total",
    "Per-vendor call outcomes",
    labelnames=("category", "vendor", "outcome"),
)

fallback_total = Counter(
    "data_vendor_router_fallback_total",
    "Fallback events (vendor[i] failed → tried vendor[i+1])",
    labelnames=("category", "from_vendor", "to_vendor", "reason"),
)

latency_seconds = Histogram(
    "data_vendor_router_latency_seconds",
    "Per-vendor call latency",
    labelnames=("category", "vendor"),
)

breaker_state = Gauge(
    "data_vendor_circuit_breaker_state",
    "Per-vendor circuit breaker state (0=closed, 1=half_open, 2=open)",
    labelnames=("vendor",),
)

breaker_state_changes_total = Counter(
    "data_vendor_circuit_breaker_state_changes_total",
    "Per-vendor breaker state transitions",
    labelnames=("vendor", "new_state"),
)


# ---------- OTel root + child span helpers ----------


@contextmanager
def root_span(category: str, ticker: str) -> Iterator[dict[str, Any]]:
    """Open the root `dvr.get_{category}` span.

    Yields a mutable record the caller fills in. On exit, attributes are written.
    """
    tracer = trace.get_tracer("data_vendor_router", "0.1.0")
    with tracer.start_as_current_span(f"dvr.get_{category}") as span:
        record: dict[str, Any] = {
            "final_vendor": None,
            "fallback_count": 0,
            "skip_count": 0,
            "total_latency_ms": 0,
        }
        span.set_attribute("dvr.category", category)
        span.set_attribute("dvr.ticker", ticker.upper())
        try:
            yield record
        finally:
            if record["final_vendor"] is not None:
                span.set_attribute("dvr.final_vendor", record["final_vendor"])
            span.set_attribute("dvr.fallback_count", record["fallback_count"])
            span.set_attribute("dvr.skip_count", record["skip_count"])
            span.set_attribute("dvr.total_latency_ms", record["total_latency_ms"])


@contextmanager
def vendor_span(vendor_name: str, category: str) -> Iterator[dict[str, Any]]:
    """Open a `dvr.vendor.{name}` child span for one vendor attempt."""
    tracer = trace.get_tracer("data_vendor_router", "0.1.0")
    with tracer.start_as_current_span(f"dvr.vendor.{vendor_name}") as span:
        record: dict[str, Any] = {"outcome": "pending", "latency_ms": 0}
        span.set_attribute("dvr.vendor.name", vendor_name)
        try:
            yield record
        finally:
            span.set_attribute("dvr.vendor.outcome", record["outcome"])
            span.set_attribute("dvr.vendor.latency_ms", record["latency_ms"])
            calls_total.labels(category=category, vendor=vendor_name, outcome=record["outcome"]).inc()


def record_fallback(category: str, from_vendor: str, to_vendor: str, reason: str) -> None:
    fallback_total.labels(
        category=category, from_vendor=from_vendor, to_vendor=to_vendor, reason=reason
    ).inc()
