---
name: signal-based-outbound
description: Build signal-based outbound — detect buying signals (funding, hiring, champion job changes, pricing-page visits, tech installs, competitor churn), pick the right play and persona, find buying-committee gaps, and draft first touches with Claude. Use for outbound prioritisation, "who should BDRs work today", trigger-based prospecting, or designing outbound plays.
---

# Signal-based outbound

Outbound only works when there's a reason to reach out now. This skill turns the
signals and scores already in the central DB into a ranked worklist.

```bash
python skills/signal-based-outbound/scripts/build_plays.py --db out/gtm.db --days 21 --draft
```
Output `out/outbound_plays.json` — each item: account, owner, priority, **why_now** (top 3 signals),
play, channel, angle, the contact to lead with, and the buying-committee **missing_roles**.
`--draft` adds a Claude-written subject/body/LinkedIn note (mock text without `ANTHROPIC_API_KEY`).

## Priority
`priority = 0.6 × fit + 0.4 × sum(decayed signal weights)` → fit gates: a hot signal at a non-ICP company stays low.

## Plays
`plays.json` maps signal type → play, lead persona, channel, angle. Edit with the BDR team; it's config, not code.
When adding a signal source: add its weight in `config scoring.intent.signals`, a play in `plays.json`, and a connector that writes to `signals` (domain, type, occurred_at, detail).

## Signal sources to wire up (typical)
| Signal | Where from |
|---|---|
| pricing_page_visit, demo_request | website analytics / reverse-IP (RB2B, Clearbit Reveal, Apollo visitors), form webhooks |
| funding_round | Crunchbase, news APIs, Clay |
| hiring_for_role | job board scrapers / Clay / LinkedIn jobs |
| champion_job_change | CRM closed-won contacts × LinkedIn/Clay job-change tracking |
| tech_install | BuiltWith / HG Insights / Clay |
| email_reply_positive | sequencer webhooks (Outreach, Salesloft, Apollo) |

## Drafting rules (enforced in the prompt)
Under 90 words, reference the actual signal, one CTA, no invented facts. **Drafts are never sent automatically** — they land in the rep's queue/sequencer as drafts for review.

## Multithreading
`missing_roles` tells the rep who else to find. Pair with prospecting tools (Apollo / Clay / Vibe Prospecting MCP) to fill economic buyer / champion gaps, then the pipeline picks them up as contacts.
