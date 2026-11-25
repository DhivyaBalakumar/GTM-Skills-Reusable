---
name: gtm-incident-rca
description: Investigate GTM system problems to root cause, ship the fix, and document it — wrong routing, duplicate CRM records, missing leads, broken syncs, bad scores, stale alerts — using job logs, lineage and the central DB, then write a blameless postmortem and runbook so nothing depends on one person. Use when something in the GTM stack broke or reps report bad data.
---

# Incident investigation, RCA & documentation

## Investigation loop
1. **Scope it with a concrete example.** Get one lead/account/rep that shows the problem. "Routing is broken" → "lead L123 from initech.com went to Bob, should be Chen".
2. **Trace the record** through the system:
   - `SELECT * FROM routing_assignments WHERE lead_id=?` — which rule fired
   - `SELECT * FROM source_records WHERE golden_key=?` — which sources built the account (lineage)
   - `SELECT * FROM account_scores WHERE account_id=? ORDER BY scored_at` — score history + model_version
   - `SELECT * FROM job_runs WHERE job_name=? ORDER BY started_at DESC LIMIT 10` — did the job run / fail / skip
   - `python skills/gtm-reliability-ops/scripts/replay_dead_letter.py --list` — rejected records
   - JSON logs: filter by `job`, `run_id`, `url`, `status`
3. **Find when it started** — correlate with deploys (`git log`), config changes, vendor incidents, new fields in the CRM.
4. **Ask "why" until you hit something you can change** (5 whys). Stop at process/system causes, not people.
5. **Fix forward**: write a failing test that reproduces the case → fix → test passes → deploy → replay affected records (dead-letter export / re-run job for the window).
6. **Verify with the person who reported it.**
7. **Document**: postmortem (`templates/postmortem.md`) + update the runbook (`templates/runbook.md`) + add a monitor so it's caught automatically next time.

## Severity guide
| Sev | Example | Response |
|---|---|---|
| 1 | inbound leads not routed / CRM writes corrupting data | stop the job (disable schedule), fix same day, notify Head of GTM + reps |
| 2 | daily alerts missing/wrong, enrichment sync stale > 1 day | fix within 1 business day |
| 3 | cosmetic, single-record issues | backlog |

## Documentation rules
Blameless. Timeline in UTC. Impact in business terms (leads delayed, reps affected, pipeline at risk). Every action item has an owner and a date. Runbooks are written so a new teammate can execute them at 7 am without you.
