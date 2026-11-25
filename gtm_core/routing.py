"""Inbound lead routing: qualify -> match to account -> pick owner -> set SLA.

Rules run in a fixed, documented order and the winning rule is recorded,
so "why did this lead go to Bob?" always has an answer.
  1. disqualify   (free-email + no company, students, competitors)
  2. account owner (existing account already owned => same rep)
  3. enterprise    (employees >= threshold => enterprise pod)
  4. territory     (country -> territory -> round-robin, load-balanced)
  5. fallback queue
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from itertools import cycle

from . import normalize as n
from .scoring import score_account

DISQUALIFY_TITLES = re.compile(r"\b(student|intern|job seeker|unemployed|professor)\b", re.I)


class RoundRobin:
    """Least-loaded-then-round-robin. `load` = open leads per rep today."""

    def __init__(self, load: dict[str, int] | None = None):
        self.load = dict(load or {})
        self._cycles: dict[tuple, cycle] = {}

    def pick(self, reps: list[str]) -> str:
        m = min(self.load.get(r, 0) for r in reps)
        candidates = [r for r in reps if self.load.get(r, 0) == m]
        key = tuple(candidates)
        self._cycles.setdefault(key, cycle(candidates))
        rep = next(self._cycles[key])
        self.load[rep] = self.load.get(rep, 0) + 1
        return rep


def route_lead(lead: dict, cfg: dict, accounts_by_domain: dict[str, dict], rr: RoundRobin,
               signals_by_domain: dict[str, list] | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    r = cfg["routing"]
    dom = n.domain(lead.get("domain") or lead.get("email"))
    result = {"lead_id": lead.get("lead_id"), "domain": dom}

    # 1. disqualify
    if n.is_free_email_domain(dom) and not lead.get("company"):
        return {**result, "assigned_to": None, "rule": "disqualified:free_email_no_company", "tier": "D", "sla_due_at": None,
                "next_step": "nurture_sequence"}
    if DISQUALIFY_TITLES.search(lead.get("title") or ""):
        return {**result, "assigned_to": None, "rule": "disqualified:title", "tier": "D", "sla_due_at": None,
                "next_step": "nurture_sequence"}

    # score using account data if we have it, else the lead's own firmographics
    acct = accounts_by_domain.get(dom) or {
        "domain": dom, "industry": (lead.get("industry") or "").lower() or None,
        "employees": n.to_int(lead.get("employees")), "country": n.country(lead.get("country")), "tech_stack": [],
    }
    lead_signal = {"type": lead.get("form"), "occurred_at": lead.get("created_at") or now.isoformat(),
                   "detail": lead.get("message")}
    sigs = list((signals_by_domain or {}).get(dom, [])) + [lead_signal]
    sc = score_account(acct, sigs, cfg, contact_titles=[lead.get("title")], now=now)
    tier = sc["tier"]

    # 2-5. owner selection
    if acct.get("owner"):
        owner, rule = acct["owner"], "account_owner"
    elif (acct.get("employees") or 0) >= r["enterprise_threshold_employees"] and r.get("enterprise_reps"):
        owner, rule = rr.pick(r["enterprise_reps"]), "enterprise_pod"
    else:
        terr = next((t for t in r["territories"] if acct.get("country") in t["countries"]), None)
        if terr and terr["reps"]:
            owner, rule = rr.pick(terr["reps"]), f"territory:{terr['name']}"
        else:
            owner, rule = r["fallback_queue"], "fallback_queue"

    sla_min = r["sla_minutes"].get(tier)
    created = datetime.fromisoformat((lead.get("created_at") or now.isoformat()).replace("Z", "+00:00"))
    return {
        **result,
        "assigned_to": owner,
        "rule": rule,
        "tier": tier,
        "score": sc["score"],
        "reasons": sc["reasons"],
        "sla_due_at": (created + timedelta(minutes=sla_min)).isoformat() if sla_min else None,
        "next_step": "call_now" if tier == "A" else "personal_email_today" if tier == "B" else "sequence",
    }
