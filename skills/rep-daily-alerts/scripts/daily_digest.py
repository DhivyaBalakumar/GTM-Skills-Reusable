#!/usr/bin/env python3
"""Morning digest per rep: "call these accounts today, and here's why".

Reads out/outbound_plays.json (signal-based-outbound) and optionally
out/routed_leads.json (inbound-routing), groups by owner, caps per rep,
and posts to Slack (one message per rep) or prints Markdown.

    python skills/rep-daily-alerts/scripts/daily_digest.py            # print
    python skills/rep-daily-alerts/scripts/daily_digest.py --send     # Slack via $SLACK_WEBHOOK_URL

Unowned high-priority accounts go to the GTM lead in a separate block so
nothing hot sits unassigned.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from gtm_core.config import load_config  # noqa: E402
from gtm_core.http import Client  # noqa: E402

UNOWNED = "UNASSIGNED"


def _load(path):
    p = pathlib.Path(path)
    return json.loads(p.read_text()) if p.exists() else []


def group(plays: list[dict], leads: list[dict], cap: int) -> dict[str, list[dict]]:
    by_rep: dict[str, list[dict]] = {}
    inbound_domains = {l.get("domain") for l in leads if l.get("assigned_to")}
    for l in leads:  # inbound hand-raisers always first
        if l.get("assigned_to"):
            by_rep.setdefault(l["assigned_to"], []).append({
                "kind": "inbound", "account": l.get("domain"), "priority": 1000 + (l.get("score") or 0),
                "headline": f"INBOUND {l['tier']} — {l.get('next_step')} (SLA {l.get('sla_due_at', '')[:16]})",
                "why": [r for r in l.get("reasons", []) if " ago" in r][:2] or l.get("reasons", [])[:2],
            })
    for p in plays:
        if p.get("domain") in inbound_domains:
            continue  # already on the list as an inbound hand-raiser
        by_rep.setdefault(p.get("owner") or UNOWNED, []).append({
            "kind": "outbound", "account": p["account"], "priority": p["priority"],
            "headline": f"{p['play']} via {p['channel']} → {(p.get('contact') or {}).get('first_name', '?')} "
                        f"{(p.get('contact') or {}).get('last_name', '')} ({(p.get('contact') or {}).get('title', 'no contact')})",
            "why": p["why_now"][:2],
            "gap": p.get("missing_roles"),
        })
    return {rep: sorted(items, key=lambda x: -x["priority"])[:cap] for rep, items in by_rep.items()}


def to_markdown(rep: str, items: list[dict]) -> str:
    title = "Hot accounts with NO owner — assign today" if rep == UNOWNED else f"Today's call list for {rep}"
    lines = [f"*{title}*"]
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. *{it['account']}* — {it['headline']}")
        for w in it["why"]:
            lines.append(f"    • why: {w}")
        if it.get("gap"):
            lines.append(f"    • multithread: no {', '.join(it['gap'])} yet")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plays", default=str(ROOT / "out/outbound_plays.json"))
    ap.add_argument("--leads", default=str(ROOT / "out/routed_leads.json"))
    ap.add_argument("--config", default=None)
    ap.add_argument("--send", action="store_true")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    cap = cfg.get("alerts", {}).get("max_accounts_per_rep", 5)
    digest = group(_load(a.plays), _load(a.leads), cap)
    webhook = os.environ.get(cfg.get("alerts", {}).get("slack_webhook_env", "SLACK_WEBHOOK_URL"))
    for rep, items in digest.items():
        md = to_markdown(rep, items)
        if a.send:
            if not webhook:
                sys.exit("--send needs the Slack webhook env var set (see config alerts.slack_webhook_env)")
            Client(webhook, rate_per_sec=1).post("", {"text": md})
        else:
            print(md + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
