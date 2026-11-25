---
name: lead-scoring
description: Design, run, explain, backtest or tune account and lead scoring — ICP fit plus time-decayed intent signals, with tiers and human-readable reasons. Use for lead scoring, account scoring, ICP fit, MQL definitions, prioritising a list, or checking whether the scoring model actually predicts pipeline.
---

# Lead & account scoring

Score = **fit** (who they are) + **intent** (what they're doing, decaying with a half-life), capped at 100 → tier A/B/C/D.
Every point carries a reason string ("+40 demo_request 0d ago: …") so reps trust it and you can audit it.
Weights live in `config/gtm.config.json` → `scoring`. Logic: `gtm_core/scoring.py`.

## Use it
```bash
python skills/lead-scoring/scripts/score_file.py leads.csv --out scored.csv   # ad hoc, no DB
python skills/lead-scoring/scripts/backtest.py history.csv                    # needs an `outcome` 0/1 column
```
The account pipeline scores everything in the DB on every run and stores history with `model_version`.

## Designing / tuning weights (do it in this order)
1. **Start from closed-won, not opinions.** Pull 12–24 months of accounts with outcome (opp created or won). Run `backtest.py`.
2. Read the tier table: tier A conversion should be clearly above B > C > D. Lift ≈ 1 everywhere = the model is noise.
3. Read the reason table: a reason that appears equally in converters and non-converters is worth ~0 points; a big gap deserves weight. Negative gap → make it negative (e.g. competitor tech).
4. Change weights in config, re-run backtest, keep the change only if tier separation improves.
5. Ship: config change → PR → the new `model_version` hash appears in `account_scores`; compare tier distributions week over week.

## Intent rules of thumb
- Hand-raisers (demo request, positive reply, pricing inquiry) are near-A on their own; research signals (content download, webinar) are weak alone.
- Half-life 14 days default: a 2-week-old pricing visit is worth half. Shorten for high-velocity SMB, lengthen for enterprise.
- Score accounts, then pick contacts — B2B buys as a committee.

## Guardrails
- Never let scoring change ownership; routing does that.
- Keep weights in config (reviewable), not code.
- Document every weight change in the PR with before/after backtest output.
