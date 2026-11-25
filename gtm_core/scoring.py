"""Explainable account/lead scoring: fit (who they are) + intent (what they're doing).

Every point awarded comes with a human-readable reason, so a rep can see
*why* an account is tier A, and so weights can be audited and tuned.
Intent decays exponentially with a configurable half-life.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Iterable

from . import normalize as n


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def fit_score(account: dict, cfg: dict, contact_titles: Iterable[str] = ()) -> tuple[float, list[str]]:
    icp, w = cfg["icp"], cfg["scoring"]["fit"]
    pts, reasons = 0.0, []

    if account.get("industry") and account["industry"].lower() in {i.lower() for i in icp["industries"]}:
        pts += w["industry_match"]; reasons.append(f"+{w['industry_match']} ICP industry ({account['industry']})")

    emp = account.get("employees")
    lo, hi = icp["employee_range"]
    if emp is not None and lo <= emp <= hi:
        pts += w["employee_in_range"]; reasons.append(f"+{w['employee_in_range']} headcount {emp} in {lo}-{hi}")

    if account.get("country") in icp["countries"]:
        pts += w["country_match"]; reasons.append(f"+{w['country_match']} target country {account['country']}")

    stack = set(account.get("tech_stack") or [])
    pos = stack & {t.lower() for t in icp["tech_stack_positive"]}
    if pos:
        p = min(len(pos) * w["positive_tech_each"], w["positive_tech_max"])
        pts += p; reasons.append(f"+{p} uses {', '.join(sorted(pos))}")
    neg = stack & {t.lower() for t in icp["tech_stack_negative"]}
    if neg:
        pts += w["negative_tech"]; reasons.append(f"{w['negative_tech']} uses {', '.join(sorted(neg))}")

    # best contact seniority we know at the account
    seniority_pts = w["title_seniority"]
    levels = [n.seniority(t) for t in contact_titles if t]
    if levels:
        top = max(levels, key=lambda lv: seniority_pts[lv])
        best = seniority_pts[top]
        pts += best; reasons.append(f"+{best} contact seniority: {top}")
    return pts, reasons


def intent_score(signals: Iterable[dict], cfg: dict, now: datetime | None = None) -> tuple[float, list[str]]:
    now = now or datetime.now(timezone.utc)
    icfg = cfg["scoring"]["intent"]
    half_life = icfg["half_life_days"]
    pts, reasons = 0.0, []
    for s in sorted(signals, key=lambda s: s["occurred_at"], reverse=True):
        base = icfg["signals"].get(s["type"])
        if base is None:
            continue
        age_days = max((now - _parse_ts(s["occurred_at"])).total_seconds() / 86400, 0)
        val = base * math.pow(0.5, age_days / half_life)
        if val < 0.5:
            continue  # stale signal, ignore
        pts += val
        reasons.append(f"+{val:.0f} {s['type']} {age_days:.0f}d ago" + (f": {s['detail']}" if s.get("detail") else ""))
    return pts, reasons


def tier(score: float, cfg: dict) -> str:
    for name, threshold in cfg["scoring"]["tiers"].items():
        if score >= threshold:
            return name
    return "D"


def score_account(account: dict, signals: list[dict], cfg: dict,
                  contact_titles: Iterable[str] = (), now: datetime | None = None) -> dict:
    f, fr = fit_score(account, cfg, contact_titles)
    i, ir = intent_score(signals, cfg, now)
    total = round(min(f + i, 100), 1)
    return {
        "fit_score": round(f, 1),
        "intent_score": round(i, 1),
        "score": total,
        "tier": tier(total, cfg),
        "reasons": fr + ir,
    }
