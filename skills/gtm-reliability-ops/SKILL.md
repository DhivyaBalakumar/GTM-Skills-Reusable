---
name: gtm-reliability-ops
description: Keep GTM pipelines and automations reliable — scheduling (cron, GitHub Actions), locks, retries, dead-letter queues, structured logging, freshness SLAs, health checks, SLA-breach and failure alerts to Slack, and replay after fixes. Use when scheduling a job, adding monitoring/alerting, investigating a failed or stale job, or hardening scripts for 10x volume.
---

# GTM reliability & ops

Reps stop trusting a system the first morning the call list is wrong. Everything scheduled runs through these pieces:

| Piece | Where | What it gives you |
|---|---|---|
| `run_job(name, fn)` | `gtm_core/jobs.py` | lock (no overlap), retries w/ backoff, `job_runs` row, dead-letter, fail-over-threshold, Slack alert |
| JSON logs | `setup_logging()` | grep-able / shippable to Datadog, Logtail, CloudWatch |
| `health_check.py` | `scripts/` | stale jobs, failures (24 h), dead-letter backlog, inbound SLA breaches, data-quality counts; exit 1 = red |
| `replay_dead_letter.py` | `scripts/` | group errors, export payloads, mark replayed after the fix |

## Scheduling
- GitHub Actions: `.github/workflows/daily-gtm.yml` (example in repo) — secrets in repo settings, artifacts for outputs.
- Or cron: `15 6 * * * cd /srv/gtm && make daily >> logs/daily.log 2>&1` and `*/15 * * * * make health`.
- Give every job a freshness SLA in the health check (`--slas '{"account_pipeline": 26}'`).

## Making a script production-grade (checklist)
- [ ] Idempotent: safe to re-run (upserts on natural keys, dedupe hashes)
- [ ] Bounded: pagination + rate limit; no "load everything into memory" on unbounded tables
- [ ] Per-record errors dead-lettered, run fails if error ratio > threshold
- [ ] Retries only on transient errors (429/5xx/network), never on 4xx validation errors
- [ ] Logs a start/finish line with counts; alerts on failure
- [ ] Has a `--dry-run`
- [ ] Freshness SLA + health check entry
- [ ] Runbook entry (`gtm-incident-rca/templates/runbook.md`)

## Alert hygiene
Alert on things a human must act on (failed run, stale data, SLA breach). Everything else is a dashboard. One alert channel (`#gtm-alerts`) with an owner; every alert links to its runbook section.

## 10x volume thinking
Batch API calls (100–200 records), stream files instead of loading them, index the join keys (`domain`, `email`, `occurred_at`), move SQLite → Postgres/warehouse when concurrent writers appear (webhooks + batch jobs), and queue (SQS/Redis) webhook processing when bursts exceed what one process handles.
