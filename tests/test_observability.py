from data_vendor_router import observability


def test_root_span_records_attributes():
    with observability.root_span("ohlcv", "NVDA") as record:
        record["final_vendor"] = "yfinance"
        record["fallback_count"] = 1
        record["total_latency_ms"] = 150
    # No exception means span was created and attributes written successfully.


def test_vendor_span_records_outcome_and_increments_counter():
    before = observability.calls_total.labels(category="ohlcv", vendor="yfinance", outcome="success")._value.get()
    with observability.vendor_span("yfinance", "ohlcv") as record:
        record["outcome"] = "success"
        record["latency_ms"] = 50
    after = observability.calls_total.labels(category="ohlcv", vendor="yfinance", outcome="success")._value.get()
    assert after == before + 1


def test_record_fallback_increments_counter():
    before = observability.fallback_total.labels(
        category="ohlcv", from_vendor="yfinance", to_vendor="alpaca", reason="rate_limit"
    )._value.get()
    observability.record_fallback("ohlcv", "yfinance", "alpaca", "rate_limit")
    after = observability.fallback_total.labels(
        category="ohlcv", from_vendor="yfinance", to_vendor="alpaca", reason="rate_limit"
    )._value.get()
    assert after == before + 1
