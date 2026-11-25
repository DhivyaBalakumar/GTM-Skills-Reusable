---
name: account-research-agent
description: Produce a one-page pre-call account brief for AEs/BDRs — firmographics, score reasons, why-now signals, buying-committee map with gaps, likely pains, hypotheses to validate, talk track and discovery questions — using the central DB plus web research. Use for account research, call prep, "research this company before my call", or automating AE research.
---

# Account research agent

## In a Claude conversation
1. Pull what we know: `python skills/account-research-agent/scripts/research_account.py <domain>` (also works with the mock if no API key) — or query the DB directly.
2. Research the open web yourself: company site (product, pricing, customers), recent news/funding, job posts (they reveal priorities and tools), leadership on LinkedIn, tech stack hints.
3. Save raw findings to `research/<domain>.md`, then re-run with `--notes research/<domain>.md` so the brief is grounded in both.
4. Fill/correct `templates/account-brief.md` structure if writing by hand.

## Automated (batch for tomorrow's meetings)
```bash
for d in $(python skills/gtm-data-model/scripts/db.py sql "SELECT domain FROM accounts ..."); do
  python skills/account-research-agent/scripts/research_account.py $d --notes research/$d.md
done
```
Pair with calendar data (meetings tomorrow → domains) to auto-attach briefs to events.

## Non-negotiable rules
- **Facts vs hypotheses are separate sections.** Anything not in the inputs is a hypothesis phrased as a question to validate on the call.
- Cite where a fact came from when writing by hand (URL or "CRM").
- No personal info beyond professional role/title. No guessing private details.
- Keep it to one page. Reps read it 3 minutes before the call.
