#!/usr/bin/env python3
"""Score and route inbound leads (forms, chat, demo requests) with SLAs.

    python skills/inbound-routing/scripts/route_leads.py --leads examples/data/inbound_leads.jsonl --db out/gtm.db

Batch mode reads JSONL; for real-time, call `route_one()` from the webhook
receiver in gtm-api-integrations. Writes routing_assignments (auditable:
which rule fired) and out/routed_leads.json for the daily digest.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from gtm_core import store  # noqa: E402
from gtm_core.config import load_config  # noqa: E402
from gtm_core.routing import RoundRobin, route_lead  # noqa: E402


def _accounts(conn) -> dict:
    out = {}
    for r in conn.execute("SELECT account_id, domain, industry, employees, country, owner_email, tech_stack FROM accounts"):
        out[r["domain"]] = {"account_id": r["account_id"], "domain": r["domain"], "industry": r["industry"],
                            "employees": r["employees"], "country": r["country"], "owner": r["owner_email"],
                            "tech_stack": json.loads(r["tech_stack"] or "[]")}
    return out


def _signals(conn) -> dict:
    out: dict[str, list] = {}
    for r in conn.execute("SELECT domain, type, occurred_at, detail FROM signals"):
        out.setdefault(r["domain"], []).append(dict(r))
    return out


def _load_today(conn) -> dict[str, int]:
    rows = conn.execute("SELECT assigned_to, COUNT(*) n FROM routing_assignments "
                        "WHERE date(created_at)=date('now') GROUP BY assigned_to").fetchall()
    return {r["assigned_to"]: r["n"] for r in rows}


def route_one(conn, cfg, lead: dict, rr: RoundRobin | None = None, now=None) -> dict:
    accts = _accounts(conn)
    sigs = _signals(conn)
    # don't double-count: the lead's own form fill is added inside route_lead
    dom = (lead.get("domain") or "").lower()
    sigs[dom] = [s for s in sigs.get(dom, []) if not (s["type"] == lead.get("form") and s["occurred_at"] == lead.get("created_at"))]
    res = route_lead(lead, cfg, accts, rr or RoundRobin(_load_today(conn)), sigs, now)
    conn.execute(
        """INSERT INTO routing_assignments(lead_id,account_id,assigned_to,rule,tier,sla_due_at)
           VALUES(?,?,?,?,?,?) ON CONFLICT(lead_id) DO NOTHING""",
        (res["lead_id"], (accts.get(res["domain"]) or {}).get("account_id"),
         res["assigned_to"] or "nurture", res["rule"], res["tier"], res["sla_due_at"]))
    # claim unowned accounts for the routed rep so outbound + inbound share one owner
    if res["assigned_to"] and res["assigned_to"] != cfg["routing"]["fallback_queue"]:
        conn.execute("UPDATE accounts SET owner_email=?, updated_at=CURRENT_TIMESTAMP "
                     "WHERE domain=? AND owner_email IS NULL", (res["assigned_to"], res["domain"]))
    conn.commit()
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--leads", default=str(ROOT / "examples/data/inbound_leads.jsonl"))
    ap.add_argument("--db", default=str(ROOT / "out/gtm.db"))
    ap.add_argument("--config", default=None)
    ap.add_argument("--now", default=None)
    ap.add_argument("--out", default=str(ROOT / "out/routed_leads.json"))
    a = ap.parse_args(argv)
    cfg, conn = load_config(a.config), store.connect(a.db)
    now = datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else datetime.now(timezone.utc)
    rr = RoundRobin(_load_today(conn))
    leads = [json.loads(l) for l in open(a.leads, encoding="utf-8") if l.strip()]
    results = [route_one(conn, cfg, l, rr, now) for l in leads]
    pathlib.Path(a.out).parent.mkdir(exist_ok=True, parents=True)
    pathlib.Path(a.out).write_text(json.dumps(results, indent=2))
    for r in results:
        print(f"{r['lead_id']:<4} {r['domain'] or '-':<22} tier={r['tier']} -> {r['assigned_to'] or 'NURTURE':<22} "
              f"rule={r['rule']:<34} sla={(r['sla_due_at'] or '-')[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
