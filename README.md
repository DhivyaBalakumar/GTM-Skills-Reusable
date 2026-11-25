# GTM Skills — a reusable GTM engineering system for Claude

These are reusable **Claude skills plus working Python and SQL** for one central, automated go-to-market system. BDRs and AEs all work from it, so nobody has to run their own setup for data, outreach and comms.

Each skill is a `SKILL.md` that Claude (Claude Code, Claude apps or the API) can follow. All the skills sit on one shared, tested engine, `gtm_core`. That engine is stdlib-only Python plus a SQL data layer, so it runs anywhere: a laptop, cron, GitHub Actions or Lambda.

```
 Sources                  Central data layer (sql/schema.sql)                 Outputs
 ───────                  ───────────────────────────────────                 ───────
 CRM export ─┐                                                           ┌─> CRM write-back (HubSpot / Salesforce)
 Clay/Apollo ├─> ingest → normalise → dedupe → accounts/contacts/        ├─> inbound routing + SLAs
 Signals ────┤          (lineage)      (golden)  buying_committee        ├─> outbound plays ("why now")
 Webhooks ───┘                                   signals / scores        ├─> Slack call lists per rep
                                                 routing / job_runs      ├─> AE agents: brief · proposal · CRM update
                                                                         └─> health checks + alerts
```

## Skills

| Area | Skill | What it does |
|---|---|---|
| Data | [`gtm-data-model`](skills/gtm-data-model/SKILL.md) | Models accounts, contacts, buying committees, signals, score history, lineage and ops tables, plus 9 ready-made SQL queries |
| Data | [`account-data-pipeline`](skills/account-data-pipeline/SKILL.md) | Pulls multiple sources, then normalises, dedupes (with survivorship rules and lineage), scores and writes back to the CRM |
| Pipeline gen | [`lead-scoring`](skills/lead-scoring/SKILL.md) | Scores fit plus time-decayed intent with readable reasons and tiers, and backtests the model against outcomes |
| Pipeline gen | [`signal-based-outbound`](skills/signal-based-outbound/SKILL.md) | Turns signals into a play, a persona, buying-committee gaps and a Claude-drafted first touch |
| Pipeline gen | [`inbound-routing`](skills/inbound-routing/SKILL.md) | Disqualifies, routes by account owner, enterprise pod, territory or round-robin, and sets SLAs. Every assignment is auditable |
| Pipeline gen | [`rep-daily-alerts`](skills/rep-daily-alerts/SKILL.md) | Sends each rep a Slack list: call these accounts today, and here's why |
| Sales automation | [`account-research-agent`](skills/account-research-agent/SKILL.md) | Writes a one-page pre-call brief that keeps facts and hypotheses apart |
| Sales automation | [`proposal-generator`](skills/proposal-generator/SKILL.md) | Has Claude write the narrative while code prices the deal with discount guardrails |
| Sales automation | [`crm-update-agent`](skills/crm-update-agent/SKILL.md) | Turns call notes into validated CRM updates, split into auto-apply and needs-review |
| Infrastructure | [`gtm-api-integrations`](skills/gtm-api-integrations/SKILL.md) | Provides a retrying, rate-limited, idempotent API client, an incremental connector template and signed, idempotent webhooks |
| Infrastructure | [`gtm-reliability-ops`](skills/gtm-reliability-ops/SKILL.md) | Covers job locks, retries, dead-letter, freshness SLAs, health checks, alerts and replay |
| Ownership | [`gtm-incident-rca`](skills/gtm-incident-rca/SKILL.md) | Gives the steps for tracing a problem to its root cause, fixing it and documenting it, with postmortem and runbook templates |
| Ownership | [`gtm-bottleneck-discovery`](skills/gtm-bottleneck-discovery/SKILL.md) | Covers rep interviews, time audits and impact × confidence ÷ effort prioritisation |

## Quickstart (offline, no API keys)

```bash
git clone https://github.com/DhivyaBalakumar/GTM-Skills-Reusable && cd GTM-Skills-Reusable
make test     # 20 unit + integration tests
make demo     # full morning run on sample data: pipeline → routing → plays → Slack digest → brief → CRM update → proposal
```
Outputs land in `out/`. Without `ANTHROPIC_API_KEY`, the agents run in **mock mode**, so everything works offline. Set the key, and optionally `CLAUDE_MODEL`, to get real Claude output.

Sample digest from the demo:
```
*Today's call list for alice@yourco.com*
1. *vandelay.com* — INBOUND B — personal_email_today (SLA 2026-11-25T10:20)
    • why: +35 pricing_inquiry 0d ago: what does it cost for 30 reps?
2. *Acme Analytics Inc.* — Pricing-intent follow-up via email+phone → Raj Iyer (RevOps Manager)
    • why: pricing_page_visit (2026-11-24): 3 visits to /pricing
    • multithread: no technical_evaluator, end_user yet
*Hot accounts with NO owner — assign today*
1. *Hooli* — Champion moved via linkedin+email → Li Wang (Head of Data)
```

## Using the skills with Claude
- **Claude Code:** open this repo. `.claude/skills` links to `skills/`, so the skills load on their own. You can also copy any folder into `~/.claude/skills/`.
- **Claude apps:** zip a skill folder and upload it under Settings → Capabilities → Skills.
- **API / Agent SDK:** load `SKILL.md` as instructions and call the scripts as tools.

## Configuration
Copy `config/gtm.config.example.json` to `config/gtm.config.json`; that file is gitignored. It holds the ICP, buying-committee title keywords, scoring weights and half-life, tiers, territories, round-robin pools, SLAs and alert settings. The rest of the config is:
- `skills/account-data-pipeline/sources.example.json` maps each source's columns
- `skills/signal-based-outbound/plays.json` maps each signal to a play
- `skills/proposal-generator/pricing.example.json` is the price book

## Going live
| Step | How |
|---|---|
| CRM write-back | Set `GTM_CRM=hubspot` with `HUBSPOT_TOKEN`, or `GTM_CRM=salesforce` with `SF_*`. Create the properties listed in `gtm_core/crm.py` first |
| Claude | Set `ANTHROPIC_API_KEY` |
| Slack | Set `SLACK_WEBHOOK_URL` for rep digests and `SLACK_ALERT_WEBHOOK_URL` for ops alerts |
| Schedule | Use `.github/workflows/daily-gtm.yml` (add secrets, then uncomment the cron) or plain cron with `make daily` and `make health` |
| Webhooks | Deploy `webhook_receiver.py`, or port its handler to FastAPI or serverless. Set `WEBHOOK_SECRET` |
| Scale | Move SQLite to Postgres or a warehouse once multiple writers appear. The schema notes the type changes |

## Design principles
1. **One source of truth.** Golden records are keyed on domain and email, with lineage back to every source row.
2. **Explainable.** Every score point, routing decision and CRM change carries a reason or evidence.
3. **LLMs write words; code handles numbers and rules.** Pricing, validation and routing are deterministic.
4. **Safe to re-run.** Writes are idempotent upserts, signals use hash dedupe, and webhooks use event-id idempotency.
5. **Observable.** Every job writes a `job_runs` row, bad records go to dead-letter, and freshness SLAs and alerts point to runbooks.
6. **Humans approve risky actions.** Nothing is emailed automatically. Stage, amount and close-date changes always need a rep's review.

## Repo layout
```
gtm_core/      shared engine: config, normalize, dedupe, scoring, routing, store, crm, http, jobs, llm
sql/           schema.sql (central data layer) · queries.sql (everyday GTM questions)
skills/        13 skills, each with SKILL.md (+ scripts/, templates/, config)
config/        gtm.config.example.json
examples/data  sample CRM, enrichment, contacts, signals, inbound leads, call notes, scoring history
tests/         unit + end-to-end tests (run in CI on Python 3.10 & 3.12)
```
