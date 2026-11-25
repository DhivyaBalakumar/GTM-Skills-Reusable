---
name: proposal-generator
description: Draft customer proposals from discovery notes and an account brief — buyer situation in their words, solution, success metrics, mutual action plan — with pricing computed deterministically from the price book and discount guardrails. Use for proposals, quotes, order-form drafts, pricing a deal, or automating AE proposal work.
---

# Proposal generator

```bash
python skills/proposal-generator/scripts/build_proposal.py --account "Acme Analytics" \
  --plan growth --seats 18 --years 1 \
  --notes examples/data/call_notes_acme.txt --brief out/briefs/acme-analytics.com.md
```
Output: `out/proposals/<account>-proposal.md` + the quote JSON.

## Division of labour (the important design choice)
- **Python prices.** `pricing.json` = plans, per-seat price, minimum seats, platform fee, volume and multi-year discounts, `max_rep_discount`. Discounts above the rep limit raise an error → route to deal desk. Total discount hard-capped at 35 %.
- **Claude writes words.** Situation (their language), objectives, solution, success metrics, mutual action plan, assumptions. The prompt forbids stating prices.

## Workflow
1. Run `crm-update-agent` on the discovery notes first — confirms pain, metrics, decision process.
2. Run `account-research-agent` for the brief.
3. Generate the proposal; the AE edits, never sends unreviewed.
4. Export to the format the buyer wants (Docs/PDF/your CPQ). Log the sent proposal + amount back to the CRM deal.

## Good proposal checklist
- [ ] First section is *their* problem, in *their* words, with a number attached
- [ ] Success metrics are measurable and dated
- [ ] Mutual action plan has owners and dates through signature
- [ ] Price matches the CRM amount
- [ ] Assumptions listed (seat count, start date, security review)
