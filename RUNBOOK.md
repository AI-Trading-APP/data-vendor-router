# Runbook — data-vendor-router

Operational guide for consumer services using `data-vendor-router`.

## Health check (production / test)

The library has no service of its own — health is the consumer service's concern. To verify the lib is working from a consumer:

```python
from datetime import date, timedelta
from data_vendor_router import get_ohlcv

today = date.today()
bars = get_ohlcv("AAPL", start=today - timedelta(days=5), end=today)
assert len(bars) >= 1
```

If this fails, troubleshooting tree below.

## Vendor outage / chronic failure

**Symptom**: One vendor consistently fails (rate-limit, 5xx, timeout). Router falls back per chain config; fallback rate metric spikes.

**Action**:
1. Check the vendor's status page:
   - yfinance: <https://github.com/ranaroussi/yfinance/issues> (no formal status page)
   - Alpaca: <https://status.alpaca.markets/>
   - Benzinga: support contact
   - Polygon: <https://status.polygon.io/>
   - Alpha Vantage: <https://www.alphavantage.co/support/>
2. If sustained, override the chain via env var to demote the failing vendor:
   ```bash
   export DVR_OHLCV_PRIORITY="alpaca,polygon,yfinance"   # demote yfinance
   ```
3. Restart the consumer service for the env var to take effect.

## Circuit breaker stuck open

**Symptom**: `data_vendor_circuit_breaker_state{vendor="..."}` = 2 (open) for > 1 hour.

**Action**:
1. Check the vendor's recent OTel spans for the actual error pattern. Common culprit: auth token expired / API key rotated.
2. Verify required env vars are set in the consumer:
   - `ALPACA_API_KEY` + `ALPACA_API_SECRET`
   - `BENZINGA_API_KEY`
   - `POLYGON_API_KEY`
   - `ALPHA_VANTAGE_KEY`
3. yfinance has no API key — failures are usually scrape-related (HTML structure changed). File an issue against yfinance project; demote in chain in the meantime.
4. To force-close a stuck breaker without restart, the consumer must run:
   ```python
   from data_vendor_router import breakers
   breakers.reset_all()  # closes ALL vendor breakers, not just the stuck one
   ```
5. If chronic, the breaker config (5 failures in 60s, 30s reset) may need tuning. File a follow-up to expose these knobs via env var.

## Rate-limit storm

**Symptom**: persistent `data_vendor_router_calls_total{outcome="rate_limit"}` from one vendor.

**Action**:
1. The router's automatic fallback handles this transparently (yfinance 429 → Alpaca → Polygon).
2. If fallback rate is uncomfortably high, request a vendor rate-limit increase OR shift the primary in the chain.
3. Per-call rate limiting (e.g., per-user quota) is the **consumer's** responsibility — see [`design.md` §10](https://github.com/AI-Trading-APP/AITradingAPP/blob/development/specs/data-vendor-router/design.md).

## Schema-drift regression

**Symptom**: `VendorResponseInvalid` exceptions starting suddenly for one vendor + category.

**Action**:
1. Check the actual vendor response — the exception carries `raw_response` for debugging.
2. Vendor likely changed their response shape. Update the adapter in the next release; tag a v0.1.x patch.
3. **Never** silently relax the DTO validation to accept the new shape — that converts a hard failure into silent data corruption. Always pin the schema and update the adapter to normalize.

## Rotation of vendor API keys

**Symptom**: Vendor authentication fails after key rotation.

**Action**:
1. Update env vars in the consumer service's secret store.
2. Restart the consumer (clients are lazy-init but already-instantiated SDK clients cache the key).
3. Some adapters (alpaca) lazy-init the client on first call, so a fresh process picks up the new key without code changes.

## OTel exporter offline

**Symptom**: Grafana shows no data for `dvr.*` spans, but service is otherwise healthy.

**Action**:
1. The library only depends on `opentelemetry-api`. If the consumer hasn't initialized the OTel **SDK**, spans become no-ops.
2. Check `OTEL_EXPORTER_OTLP_ENDPOINT` env var on the consumer.
3. Library calls continue to work even if OTel export fails — there is no hard dependency.

## Disabling the router entirely (kill switch)

There is no library-level kill switch. Each consumer should:
1. Wrap router calls in a feature flag.
2. On flag-off, fall back to the consumer's pre-existing vendor calls (whatever existed before adoption).

For the BB3 program: NewsService consumer migration (deferred to v0.2.x; see CHANGELOG) keeps its existing vendor selection so disabling the router is just removing the import.

## Versioning & upgrade

[SemVer](https://semver.org). Bump rules:

| Change | Bump |
|---|---|
| New vendor adapter, new optional kwarg, new exception field | minor (0.1.x → 0.2.0) |
| Breaking signature change, removing a public name, renaming an exception | major (0.x → 1.0) |
| Bug fix, adapter fix for schema drift | patch (0.1.0 → 0.1.1) |

Consumers pin to a specific tag in `requirements.txt`:

```
data-vendor-router @ git+https://github.com/AI-Trading-APP/data-vendor-router.git@v0.1.0
```

To upgrade: change the tag, rebuild the consumer's Docker image / re-pip-install.

## Where to file issues

- Bugs / behavior questions → [data-vendor-router issues](https://github.com/AI-Trading-APP/data-vendor-router/issues)
- Architecture / cross-program concerns → [AITradingAPP issues](https://github.com/AI-Trading-APP/AITradingAPP/issues) tagged `bb3-program`
