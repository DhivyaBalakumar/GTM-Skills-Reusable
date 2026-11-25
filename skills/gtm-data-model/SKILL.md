---
name: gtm-data-model
description: Design, extend or query the central GTM data layer — accounts, contacts, buying committees, signals, scores, routing and job/ops tables. Use when modelling CRM objects, adding a field or source, mapping a buying committee, writing SQL for GTM questions, or making the CRM the single source of truth for target accounts.
---

# GTM data model

The CRM is the system reps live in; this data layer is what keeps it clean.
Every pipeline in this repo reads and writes the schema in `sql/schema.sql`.

## Core entities
| Table | Natural key | Why it exists |
|---|---|---|
| `accounts` | normalised `domain` | one golden row per company, whatever the source |
| `contacts` | lowercase `email` | one row per person, linked to an account |
| `buying_committee` | (account, contact, role) | role per deal: economic_buyer, champion, technical_evaluator, end_user, blocker. `source` = rule / rep / ai — a rep's manual role is never overwritten by a rule |
| `source_records` | (source, source_id) | lineage: which raw rows built each golden record (debug "where did this value come from?") |
| `signals` | `dedupe_key` hash | intent events; inserting the same event twice is a no-op |
| `account_scores` | (account, scored_at) | append-only score history + `model_version` (hash of weights) → you can compare models |
| `routing_assignments` | `lead_id` | who got the lead, **which rule fired**, SLA due time |
| `job_runs`, `dead_letter`, `webhook_events` | — | observability + idempotency for the pipelines |

Views: `current_account_scores`, `committee_coverage`.

## How to work with it
1. Init / inspect: `python skills/gtm-data-model/scripts/db.py init|describe --db out/gtm.db`
2. Canned queries (top accounts, committee gaps, hot-but-unowned, score movers, speed-to-lead, routing audit, dupes, job health, quiet signal sources): `python skills/gtm-data-model/scripts/db.py query <1-9>` — see `sql/queries.sql`.
3. Ad hoc: `db.py sql "SELECT ..."`.

## Rules when changing the model
- **Natural keys first.** Match on domain/email, never on names. Names are display fields.
- **Additive migrations.** Add nullable columns; never rename/drop a column a pipeline reads without updating every reader in the same PR. `grep -r column_name gtm_core skills`.
- **History over overwrite** for anything you'll want to explain later (scores, stage changes).
- **Map to the CRM explicitly.** Every field written back needs a CRM property; document it in `gtm_core/crm.py` and in the CRM.
- **Portability:** SQLite for local/dev. For Postgres use `BIGSERIAL`, `JSONB` for `tech_stack`/`reasons`, `TIMESTAMPTZ`. For Snowflake/BigQuery use `VARIANT`/`JSON`, and MERGE instead of `ON CONFLICT`.

## Buying-committee modelling
- Title → role guess comes from `config icp.buying_committee_roles` (longest keyword wins; "of/the/&" ignored).
- Always report coverage gaps (`committee_coverage`): a tier-A account with no economic buyer is a multithreading task, not a forecastable deal.
- Reps correct roles in the CRM → sync back with `source='rep'`.
