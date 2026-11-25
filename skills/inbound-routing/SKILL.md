---
name: inbound-routing
description: Score, qualify and route inbound leads (demo requests, pricing inquiries, form fills, chat) to the right rep with SLAs, round-robin, territories, enterprise pods and account-owner matching. Use for lead routing, speed-to-lead, inbound qualification, SLA design, or debugging "why did this lead go to that rep".
---

# Inbound scoring & routing

```bash
python skills/inbound-routing/scripts/route_leads.py --leads examples/data/inbound_leads.jsonl --db out/gtm.db
```
Real time: the webhook receiver (`gtm-api-integrations`) calls `route_one()` per form submission.

## Rule order (first match wins, the rule name is stored on every assignment)
1. **Disqualify** — free-email + no company, student/intern/job-seeker titles → nurture, no rep time.
2. **Account owner** — the account already has an owner → same rep (no channel conflict between inbound & outbound).
3. **Enterprise pod** — employees ≥ `routing.enterprise_threshold_employees`.
4. **Territory** — country → territory → least-loaded, then round-robin across that territory's reps.
5. **Fallback queue** — never drop a lead.

Score = same model as accounts (`lead-scoring`), with the form fill itself counted as an intent signal. Tier sets SLA (`routing.sla_minutes`, default A=5 min, B=60, C=24h) and next step (call now / personal email today / sequence).
Routing an unowned account claims it for the rep, so the next outbound play goes to the same person.

## Debugging a routing complaint
```sql
SELECT * FROM routing_assignments WHERE lead_id = '<id>';      -- which rule fired, tier, SLA
```
Then check the account's `owner_email`, the lead's country/employees, and `config routing`. Fix the rule/config, add a test in `tests/test_core.py::TestRouting` reproducing the case, ship.

## SLA monitoring
`gtm-reliability-ops/scripts/health_check.py` alerts on A/B leads past SLA with no first touch. Populate `first_touch_at` from CRM activity (call/email logged) via a sync job.

## Before changing rules
- Write the new rule as a test first.
- Announce territory/round-robin changes to reps *before* deploying (it changes their pipeline).
- Keep rules in config where possible; code changes need a PR.
