---
name: rep-daily-alerts
description: Send each rep a daily "call these accounts today and here's why" alert in Slack, combining inbound hand-raisers (with SLA) and signal-based outbound plays, plus a separate alert for hot accounts with no owner. Use for rep alerts, daily call lists, Slack notifications for sales, or "tell the right rep which account to call today".
---

# Rep daily alerts

```bash
python skills/rep-daily-alerts/scripts/daily_digest.py            # print Markdown
SLACK_WEBHOOK_URL=... python skills/rep-daily-alerts/scripts/daily_digest.py --send
```
Inputs: `out/routed_leads.json` (inbound-routing) and `out/outbound_plays.json` (signal-based-outbound).
Run order each morning: pipeline → routing → plays → digest (`make daily`).

## What a good alert looks like
- **Short:** max `alerts.max_accounts_per_rep` (default 5). A list of 40 gets ignored.
- **Ranked:** inbound hand-raisers first (they have an SLA), then outbound by priority. An account already on the list as inbound is not repeated as outbound.
- **Explains why:** the top 1–2 signals in plain words.
- **Says what to do:** play + channel + contact, and who's missing from the buying committee.
- **Nothing hot is orphaned:** unowned A/B accounts go to the "assign today" block (send to the GTM lead's channel).

## Production notes
- One Slack incoming webhook per rep DM, or a bot token + `chat.postMessage` keyed by rep email → Slack user id (`users.lookupByEmail`).
- Schedule ~08:00 in each rep's timezone.
- Measure adoption: log which alerted accounts get a logged activity within 24 h. If the rate is low, the alert is wrong, not the reps — interview them (`gtm-bottleneck-discovery`).
