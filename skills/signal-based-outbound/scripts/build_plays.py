#!/usr/bin/env python3
"""Turn signals + scores in the central DB into a ranked outbound worklist:
which account, why now, which play, who to contact, which committee roles
are missing, and (optionally) a Claude-drafted first touch.

    python skills/signal-based-outbound/scripts/build_plays.py --db out/gtm.db --days 21 [--draft]

Output: out/outbound_plays.json  (consumed by rep-daily-alerts)
Drafts are drafts — nothing is ever sent from here.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from gtm_core import store  # noqa: E402
from gtm_core.config import load_config  # noqa: E402
from gtm_core.llm import complete_json  # noqa: E402

PLAYS = json.loads((ROOT / "skills/signal-based-outbound/plays.json").read_text())
ROLES = ["economic_buyer", "champion", "technical_evaluator", "end_user"]


def _decayed(base: float, occurred: str, now: datetime, half_life: float) -> float:
    age = (now - datetime.fromisoformat(occurred.replace("Z", "+00:00"))).total_seconds() / 86400
    return base * math.pow(0.5, max(age, 0) / half_life)


def build(conn, cfg: dict, now: datetime, days: int, draft: bool) -> list[dict]:
    weights = cfg["scoring"]["intent"]["signals"]
    hl = cfg["scoring"]["intent"]["half_life_days"]
    since = (now - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT a.account_id, a.domain, a.name, a.owner_email, a.employees, a.industry,
                  cs.score, cs.tier, cs.fit_score
           FROM accounts a LEFT JOIN current_account_scores cs USING(account_id)""").fetchall()
    plays = []
    for r in rows:
        sigs = conn.execute("SELECT type, occurred_at, detail FROM signals WHERE domain=? AND occurred_at>=? "
                            "ORDER BY occurred_at DESC", (r["domain"], since)).fetchall()
        if not sigs:
            continue
        ranked = sorted(sigs, key=lambda s: -_decayed(weights.get(s["type"], 0), s["occurred_at"], now, hl))
        top = ranked[0]
        play = PLAYS.get(top["type"], {"play": "Generic follow-up", "persona": "champion", "channel": "email", "angle": ""})
        committee = conn.execute(
            """SELECT c.first_name, c.last_name, c.email, c.title, bc.role
               FROM buying_committee bc JOIN contacts c USING(contact_id)
               WHERE bc.account_id=?""", (r["account_id"],)).fetchall()
        have = {c["role"] for c in committee}
        target = next((dict(c) for c in committee if c["role"] == play["persona"]), None) \
            or (dict(committee[0]) if committee else None)
        # priority = account score boosted by freshest signal strength (fit matters: no fit => low priority)
        urgency = sum(_decayed(weights.get(s["type"], 0), s["occurred_at"], now, hl) for s in sigs)
        priority = round((r["fit_score"] or 0) * 0.6 + urgency * 0.4, 1)
        item = {
            "account": r["name"] or r["domain"], "domain": r["domain"], "owner": r["owner_email"],
            "tier": r["tier"], "score": r["score"], "priority": priority,
            "why_now": [f"{s['type']} ({s['occurred_at'][:10]}): {s['detail'] or ''}".strip() for s in ranked[:3]],
            "play": play["play"], "channel": play["channel"], "angle": play["angle"],
            "contact": target, "missing_roles": [x for x in ROLES if x not in have],
        }
        if draft and target:
            item["draft"] = draft_touch(item, cfg)
        plays.append(item)
    return sorted(plays, key=lambda p: -p["priority"])


def draft_touch(item: dict, cfg: dict) -> dict:
    who = item["contact"]
    co = cfg.get("company", {})
    mock = {
        "subject": f"{item['account']} — {item['play'].lower()}",
        "body": ("[MOCK DRAFT: set ANTHROPIC_API_KEY for a real Claude draft]\n"
                 f"Hi {who.get('first_name') or 'there'},\n\n"
                 f"Saw this: {item['why_now'][0].split(': ', 1)[-1] or 'some recent activity at ' + item['account']}. "
                 f"<one line tying it to {co.get('product_one_liner', 'what we do')}>\n\n"
                 "Worth a 15-minute look next week?\n"),
        "linkedin_note": f"Hi {who.get('first_name') or ''}, saw the news at {item['account']} — congrats. Open to connecting?",
    }
    system = ("You are a senior BDR. Write a short, specific first touch (<90 words), plain text, no hype, "
              "one clear CTA. Reference the signal concretely. Never invent facts beyond the input.")
    user = json.dumps({"seller": co, "account": item["account"], "contact": who, "signals": item["why_now"],
                       "play": item["play"], "angle": item["angle"]}, default=str)
    return complete_json(system, user, {"subject": str, "body": str, "linkedin_note": str}, mock=mock, max_tokens=600)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(ROOT / "out/gtm.db"))
    ap.add_argument("--config", default=None)
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("--draft", action="store_true", help="draft first touches with Claude (mock if no API key)")
    ap.add_argument("--now", default=None)
    ap.add_argument("--out", default=str(ROOT / "out/outbound_plays.json"))
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else datetime.now(timezone.utc)
    plays = build(store.connect(a.db), load_config(a.config), now, a.days, a.draft)
    pathlib.Path(a.out).parent.mkdir(exist_ok=True, parents=True)
    pathlib.Path(a.out).write_text(json.dumps(plays, indent=2, default=str))
    for p in plays:
        print(f"[{p['priority']:>5}] {p['account']:<22} {p['play']:<24} -> {(p['contact'] or {}).get('email', 'NO CONTACT')}"
              f"  missing={','.join(p['missing_roles']) or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
