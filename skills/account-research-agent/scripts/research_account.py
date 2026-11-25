#!/usr/bin/env python3
"""Account research agent: one-page pre-call brief for an AE/BDR.

Combines what we already know (central DB: firmographics, score reasons,
signals, buying committee) with optional raw research the caller passes in
(website text, news, LinkedIn notes as .txt/.md files) and asks Claude for a
structured brief. Facts the model can't ground in the inputs must be marked
as hypotheses — the prompt enforces this and the output keeps them separate.

    python skills/account-research-agent/scripts/research_account.py acme-analytics.com \
        --notes research/acme_site.txt --out out/briefs/
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from gtm_core import normalize as n, store  # noqa: E402
from gtm_core.config import load_config  # noqa: E402
from gtm_core.llm import complete_json  # noqa: E402

SCHEMA = {"summary": str, "why_now": list, "likely_pains": list, "hypotheses": list,
          "committee_map": list, "talk_track": list, "discovery_questions": list, "risks": list}

SYSTEM = """You are a meticulous B2B account researcher preparing a rep for a first call.
Rules:
- Use ONLY facts present in the input. Anything inferred goes in "hypotheses", phrased as a question to validate.
- Be specific and short. Bullets, not paragraphs. No marketing fluff.
- committee_map: list of {"name","title","role","angle"} using the provided contacts; add {"name":"UNKNOWN","role":<missing role>,"angle":"how to find them"} for gaps.
- talk_track: 3-5 lines a rep could actually say.
- discovery_questions: 5 open questions tied to the pains.
Return JSON with keys: summary, why_now, likely_pains, hypotheses, committee_map, talk_track, discovery_questions, risks."""


def gather(conn, domain: str) -> dict:
    a = conn.execute("SELECT * FROM accounts WHERE domain=?", (domain,)).fetchone()
    if not a:
        return {"domain": domain, "known": False}
    sc = conn.execute("SELECT score, tier, reasons FROM current_account_scores WHERE account_id=?",
                      (a["account_id"],)).fetchone()
    sigs = conn.execute("SELECT type, occurred_at, detail FROM signals WHERE domain=? ORDER BY occurred_at DESC LIMIT 10",
                        (domain,)).fetchall()
    committee = conn.execute(
        """SELECT c.first_name||' '||COALESCE(c.last_name,'') name, c.title, bc.role
           FROM buying_committee bc JOIN contacts c USING(contact_id) WHERE bc.account_id=?""",
        (a["account_id"],)).fetchall()
    return {
        "known": True, "domain": domain, "name": a["name"], "industry": a["industry"],
        "employees": a["employees"], "country": a["country"], "tech_stack": json.loads(a["tech_stack"] or "[]"),
        "owner": a["owner_email"],
        "score": dict(sc) if sc else None,
        "signals": [dict(s) for s in sigs],
        "committee": [dict(c) for c in committee],
    }


def mock_brief(ctx: dict) -> dict:
    roles = {c["role"] for c in ctx.get("committee", [])}
    missing = [r for r in ("economic_buyer", "champion", "technical_evaluator", "end_user") if r not in roles]
    return {
        "summary": f"[MOCK] {ctx.get('name') or ctx['domain']}: {ctx.get('industry')}, ~{ctx.get('employees')} employees, {ctx.get('country')}.",
        "why_now": [f"{s['type']}: {s.get('detail')}" for s in ctx.get("signals", [])[:3]],
        "likely_pains": ["(needs Claude) derive from signals + notes"],
        "hypotheses": ["Is the team running separate tools per rep for data/outreach?"],
        "committee_map": [{"name": c["name"].strip(), "title": c["title"], "role": c["role"], "angle": ""} for c in ctx.get("committee", [])]
                         + [{"name": "UNKNOWN", "role": r, "angle": "search LinkedIn / ask champion"} for r in missing],
        "talk_track": ["(needs Claude)"], "discovery_questions": ["(needs Claude)"], "risks": [],
    }


def to_markdown(ctx: dict, b: dict) -> str:
    def bl(xs): return "\n".join(f"- {x}" for x in xs) or "- (none)"
    cm = "\n".join(f"| {c.get('name')} | {c.get('title', '')} | {c.get('role')} | {c.get('angle', '')} |" for c in b["committee_map"])
    score = ctx.get("score") or {}
    return f"""# Account brief — {ctx.get('name') or ctx['domain']}
**Domain:** {ctx['domain']} · **Tier:** {score.get('tier', '?')} ({score.get('score', '?')}) · **Owner:** {ctx.get('owner') or 'unassigned'}

## Summary
{b['summary']}

## Why now
{bl(b['why_now'])}

## Likely pains
{bl(b['likely_pains'])}

## Hypotheses to validate (not facts)
{bl(b['hypotheses'])}

## Buying committee
| Name | Title | Role | Angle |
|---|---|---|---|
{cm}

## Talk track
{bl(b['talk_track'])}

## Discovery questions
{bl(b['discovery_questions'])}

## Risks
{bl(b['risks'])}
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("domain")
    ap.add_argument("--db", default=str(ROOT / "out/gtm.db"))
    ap.add_argument("--notes", nargs="*", default=[], help="text/markdown files with raw research")
    ap.add_argument("--out", default=str(ROOT / "out/briefs"))
    a = ap.parse_args(argv)
    domain = n.domain(a.domain)
    cfg = load_config()
    ctx = gather(store.connect(a.db), domain)
    notes = {pathlib.Path(p).name: pathlib.Path(p).read_text(encoding="utf-8")[:20000] for p in a.notes}
    user = json.dumps({"seller": cfg.get("company"), "account": ctx, "raw_research": notes}, default=str)
    brief = complete_json(SYSTEM, user, SCHEMA, mock=mock_brief(ctx), max_tokens=2500)
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    path = out / f"{domain}.md"
    path.write_text(to_markdown(ctx, brief), encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
