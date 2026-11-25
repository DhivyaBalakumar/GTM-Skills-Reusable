---
name: crm-update-agent
description: Turn call notes or transcripts (Gong, Fathom, Zoom, manual notes) into validated CRM updates — stage, amount, close date, next step, MEDDPICC fields, new contacts and tasks — with confidence, evidence quotes, a diff against the current record, and auto-apply vs needs-review split. Use for CRM hygiene, post-call updates, deal-field extraction, or removing manual CRM work from AEs.
---

# CRM update agent

```bash
python skills/crm-update-agent/scripts/notes_to_crm.py notes.txt --current '{"stage":"discovery","amount":null}'
```
Output JSON: `summary`, `auto_apply`, `needs_review`, `new_contacts`, `tasks`, `validation_errors`.

## Safety model (why AEs can trust it)
1. Claude extracts **only what was said**, each field with `confidence` and an **evidence quote**.
2. Python validates: stage must be in the allowed list, amount numeric, close date valid and not in the past, no evidence → dropped.
3. Diff against the current record — unchanged fields are ignored.
4. **Risky fields (stage, amount, close date) and anything under 0.8 confidence always go to `needs_review`.** Stage jumps of more than one step get a warning.
5. Only `auto_apply` is written automatically (next step, tasks, notes, MEDDPICC text at high confidence).

## Wiring it up
- Trigger: call-recorder webhook (transcript ready) → this agent → post the review card to the AE in Slack (approve / edit) → write via `gtm_core.crm` adapter.
- New contacts → upsert as contacts with `buying_committee.source='ai'` (reps can override).
- Track: % of proposed fields approved unchanged. Falling approval = prompt or field definitions need work.

## Adapting
Edit `STAGES`, `RISKY` and the allowed field list in the script to match your CRM's picklists exactly (copy the API names, not the labels).
