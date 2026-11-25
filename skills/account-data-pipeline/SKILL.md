---
name: account-data-pipeline
description: Build or run the automated multi-source account pipeline — ingest CRM, enrichment (Clay, Apollo, ZoomInfo, CSV exports) and signal data, normalise, deduplicate into golden records, score, and write back to HubSpot or Salesforce. Use for CRM cleanup, dedupe, enrichment syncs, adding a new data source, or "make the CRM the single source of truth".
---

# Account data pipeline

`ingest → normalise → dedupe (survivorship + lineage) → load central DB → score → CRM write-back`

```bash
python skills/account-data-pipeline/scripts/run_pipeline.py \
  --sources skills/account-data-pipeline/sources.example.json \
  --db out/gtm.db --crm dryrun          # dryrun | hubspot | salesforce
```
Dry-run writes the exact CRM payloads to `out/crm_writeback.jsonl` — always review that before the first live run.

## Adding a source
1. Land the raw data as CSV/JSONL (or write a connector with `gtm-api-integrations/scripts/connector_template.py`).
2. Add an entry to `sources.json`: `source`, `path`, `priority` (higher wins conflicts), and `mapping` canonical→source column.
3. Run in dry-run, check `out/scored_accounts.json` lineage (`_lineage`) shows the merges you expect.

## How dedupe decides
- Accounts: normalised domain (`https://www.Acme.com/` = `acme.com`). Domainless rows fuzzy-match on legal-suffix-stripped name (≥ 0.92). Still no domain → dead-letter for manual enrichment (never guessed).
- Contacts: lowercase valid email. Invalid emails → dead-letter, not dropped silently.
- Survivorship: highest-priority source wins per field; nulls never overwrite values; list fields (tech stack) are unioned; CRM owner always wins over a routed owner.

## Reliability built in
Runs inside `gtm_core.jobs.run_job`: file lock (no overlapping cron runs), retries, `job_runs` row, per-record dead-letter, and the whole run fails + alerts if > 20 % of records dead-letter (that's a broken source, not bad rows). Re-running is idempotent (upserts on natural keys, signal hash dedupe) — covered by `tests/test_core.py::TestPipelineEndToEnd`.

## Going live
- HubSpot: create unique company property `gtm_domain_key` and properties `gtm_score`, `gtm_tier`, `gtm_score_reasons`, contact property `gtm_committee_role`; set `HUBSPOT_TOKEN`.
- Salesforce: External IDs `Account.Domain_Key__c`, `Contact.Email_Key__c`, fields `GTM_Score__c`, `GTM_Tier__c`; set `SF_INSTANCE_URL`, `SF_ACCESS_TOKEN`.
- Schedule nightly (see `gtm-reliability-ops`) and add the job to the freshness SLA.

## Checklist before shipping a pipeline change
- [ ] dry-run diff of `crm_writeback.jsonl` before vs after looks right
- [ ] tests pass (`make test`)
- [ ] no field the CRM owns (owner, stage) is overwritten by enrichment
- [ ] runbook updated if behaviour changed
