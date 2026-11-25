# GTM systems runbook

> One section per job/integration. Every alert links here. Written so anyone on the team can act without the author.

## Job: account_pipeline
- **What:** nightly ingest → dedupe → score → CRM write-back
- **Schedule / SLA:** 06:15 UTC daily · must succeed every 26 h
- **Owner:** {{name}} · backup: {{name}}
- **Inputs:** CRM export, enrichment landing files, signals
- **Outputs:** accounts/contacts/scores in DB, CRM properties `gtm_score`, `gtm_tier`, `gtm_score_reasons`
- **Dashboards / logs:** {{link}} · filter `job=account_pipeline`

### Alert: "job failed after N attempts"
1. Check the error in the alert and `SELECT error FROM job_runs WHERE job_name='account_pipeline' ORDER BY started_at DESC LIMIT 1`.
2. `HTTP 401/403` → token expired/rotated: refresh secret `HUBSPOT_TOKEN`, re-run.
3. `HTTP 429` repeatedly → another job is sharing the key; check schedules, lower `rate_per_sec`.
4. `> 20 % records dead-lettered` → a source changed format: `replay_dead_letter.py --list`, compare columns with `sources.json` mapping, fix mapping, re-run, replay.
5. Re-run manually: `make pipeline`. Safe — idempotent.

### Alert: "stale job"
Scheduler didn't run or a lock is stuck. Check the scheduler; if `.locks/account_pipeline.lock` is older than 1 h and no process is running, delete it and re-run.

## Job: inbound routing / webhook receiver
- **SLA:** form → assignment < 1 min; tier A first touch < 5 min
- **Health:** `GET /healthz`
### Alert: "inbound lead(s) past SLA"
1. Open the leads listed; confirm the assigned rep is working (OOO?).
2. Reassign in CRM; if a rep is OOO, remove them from `routing.territories[].reps` until back.
3. If no leads are arriving at all: check `webhook_events` latest `received_at`, form provider webhook delivery logs, and signature secret.

## Integration: {{name}}
- Auth: · Rate limit: · Endpoint docs: · Watermark file: · Known quirks:
