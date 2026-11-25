---
name: gtm-bottleneck-discovery
description: Find the biggest bottlenecks in a go-to-market team and decide what to build next — shadow and interview BDRs, AEs and managers, run a time audit, map tools and data flows, quantify hours and pipeline impact, and prioritise automation projects with the Head of GTM. Use at the start of a GTM engineering role, for quarterly planning, or when asked "what should we automate next".
---

# GTM bottleneck discovery & prioritisation

Own outcomes, not tickets: before building, find where reps lose the most time or pipeline.

## Week 1–2 playbook
1. **Map the current stack** — every tool each role uses for data, outreach, comms; where data is copied by hand; who owns each tool. Draw it (boxes = tools, arrows = data flows, red = manual copy).
2. **Shadow** 2 BDRs and 2 AEs for half a day each. Log every task with minutes spent (`templates/time-audit.csv`).
3. **Interview** each role with `templates/interview-guide.md` (30 min). Ask for the last real example, not opinions.
4. **Pull the numbers**: speed-to-lead, % leads routed correctly, duplicate rate in CRM, activities per rep per day, meeting → opp conversion, time from call to CRM update.
5. **Synthesize** into a bottleneck list: problem, who, evidence (quotes + numbers), hours/week lost, pipeline impact.

## Prioritise (with the Head of GTM)
Score each candidate project:
- **Impact** = hours saved per week across the team × reps affected, or pipeline $ unlocked
- **Confidence** = how strong the evidence is (measured > observed > said)
- **Effort** = engineer-weeks
- **Adoption risk** = does it change how reps work? (higher = needs a champion rep + rollout plan)

`priority = impact × confidence / effort`, then sanity-check adoption risk. Pick 1–2; ship an MVP in ≤ 2 weeks to 1–2 pilot reps; measure; expand.

## Typical order that works
1. CRM as single source of truth (dedupe + ownership) — everything else depends on clean data
2. Inbound routing + SLA alerts — fastest pipeline win
3. Daily signal-based call lists
4. AE time savers: research briefs, CRM auto-update, proposal drafts
5. Reporting on what the systems produced (pipeline sourced by automated plays)

## Success metrics to report monthly
Hours of manual work removed per rep per week · pipeline from system-generated plays · speed-to-lead · CRM duplicate rate · job success rate / incidents · rep adoption (% alerted accounts actioned).
