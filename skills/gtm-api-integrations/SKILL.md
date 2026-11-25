---
name: gtm-api-integrations
description: Integrate GTM tools via APIs and webhooks — CRMs (HubSpot, Salesforce), enrichment (Clay, Apollo, ZoomInfo), sequencers, Slack, forms, call recorders — with retries, rate limits, pagination, idempotency, incremental sync and signed webhooks. Use when connecting a new tool, building a connector or webhook endpoint, or fixing a flaky/rate-limited integration.
---

# GTM API & webhook integrations

## Building blocks
- `gtm_core/http.py` — `Client`: exponential backoff + jitter on 408/425/429/5xx and network errors, honours `Retry-After`, token-bucket rate limit, `Idempotency-Key` on writes, JSON logs. `paginate()` for cursor APIs.
- `gtm_core/crm.py` — batched upserts for HubSpot (100/batch) and Salesforce composite (200/batch) on external IDs.
- `scripts/connector_template.py` — copy for every new pull source.
- `scripts/webhook_receiver.py` — push sources (forms, CRM, sequencer, call recorder).

## New pull connector (checklist)
1. Copy the template; set base URL, auth env var, endpoint, cursor shape, field mapping.
2. **Incremental** by watermark (`updated_at`/cursor) stored in `out/state/<name>.json`; advance it only after the batch is written (atomic file replace).
3. Land raw rows to `out/landing/<name>/*.jsonl` — replayable, auditable — then the pipeline ingests them.
4. Set `rate_per_sec` below the vendor limit (shared across all jobs using that key!).
5. Wrap in `run_job`, add freshness SLA, add a test with a fake opener (see `tests/test_core.py::TestHttp`).

## Webhook endpoint (checklist)
- Verify HMAC signature + timestamp (≤ 5 min) before parsing. Use the provider's exact signing scheme (HubSpot v3, Stripe, Slack each differ — adapt `verify()`).
- Idempotency on provider event id (`webhook_events`). Providers retry; duplicates must be no-ops.
- Persist first, process second; ack quickly (< 3 s). Processing failures return 202 and keep the event (`processed_at IS NULL`) for replay; a redelivery of an unprocessed event is processed again.
- Health endpoint `/healthz` for uptime monitoring.

```bash
WEBHOOK_SECRET=dev python skills/gtm-api-integrations/scripts/webhook_receiver.py --port 8787
```

## Common failure modes → fix
| Symptom | Likely cause | Fix |
|---|---|---|
| 429 storms at :00 | many cron jobs share one API key | stagger schedules, shared rate limiter |
| missing records after sync | watermark advanced before write / clock skew | advance after commit, overlap window of a few minutes |
| duplicate CRM records | create instead of upsert, no idempotency key | upsert on external ID |
| silent data loss | errors swallowed in loops | dead-letter per record, fail run over threshold |
| token expired at 3 am | OAuth refresh not handled | refresh on 401 once, then alert |
