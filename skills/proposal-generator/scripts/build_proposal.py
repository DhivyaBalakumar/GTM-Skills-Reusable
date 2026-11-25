#!/usr/bin/env python3
"""Draft a customer proposal from discovery notes + an account brief.

Split of responsibilities (on purpose):
  * Python computes the price from the price book (deterministic, auditable,
    discount guardrails enforced). The LLM never invents numbers.
  * Claude writes the narrative: their situation in their words, the
    proposed solution, success metrics, mutual action plan.

    python skills/proposal-generator/scripts/build_proposal.py \
        --account "Acme Analytics" --plan growth --seats 18 --years 1 \
        --notes examples/data/call_notes_acme.txt --brief out/briefs/acme-analytics.com.md
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from gtm_core.config import load_config  # noqa: E402
from gtm_core.llm import complete_json  # noqa: E402

PRICING = ROOT / "skills/proposal-generator/pricing.example.json"


class PricingError(ValueError):
    pass


def quote(pb: dict, plan: str, seats: int, years: int = 1, extra_discount: float = 0.0) -> dict:
    if plan not in pb["plans"]:
        raise PricingError(f"unknown plan {plan}; choose from {list(pb['plans'])}")
    p = pb["plans"][plan]
    if seats < p["min_seats"]:
        raise PricingError(f"{plan} needs at least {p['min_seats']} seats")
    if extra_discount > pb["max_rep_discount"]:
        raise PricingError(f"discount {extra_discount:.0%} exceeds rep limit {pb['max_rep_discount']:.0%} — needs deal desk")
    list_price = seats * p["per_seat_annual"] + p["platform_fee"]
    vol = max((d["discount"] for d in pb["volume_discounts"] if seats >= d["min_seats"]), default=0.0)
    multi = pb["multi_year_discount"].get(str(years), 0.0)
    total_disc = min(vol + multi + extra_discount, 0.35)
    annual = round(list_price * (1 - total_disc), 2)
    return {"currency": pb["currency"], "plan": plan, "seats": seats, "years": years,
            "list_annual": list_price, "discount": round(total_disc, 4), "annual": annual,
            "onboarding_fee": pb["onboarding_fee"], "first_year_total": round(annual + pb["onboarding_fee"], 2),
            "contract_total": round(annual * years + pb["onboarding_fee"], 2)}


SCHEMA = {"situation": str, "objectives": list, "solution": list, "success_metrics": list,
          "mutual_action_plan": list, "assumptions": list}
SYSTEM = """You write concise B2B proposals. Use the buyer's own words from the notes.
Never state prices or discounts — pricing is inserted separately. Never invent facts;
anything uncertain goes in "assumptions". mutual_action_plan: list of {"step","owner","date"}.
Return JSON: situation, objectives, solution, success_metrics, mutual_action_plan, assumptions."""


def render(account: str, seller: dict, n: dict, q: dict) -> str:
    def bl(xs): return "\n".join(f"- {x}" for x in xs)
    c = q["currency"]
    map_rows = "\n".join(f"| {m.get('step')} | {m.get('owner')} | {m.get('date') or 'TBD'} |" for m in n["mutual_action_plan"])
    return f"""# Proposal: {seller.get('name', 'Us')} × {account}
*Prepared {date.today().isoformat()} — draft for rep review*

## Where you are today
{n['situation']}

## What you want to achieve
{bl(n['objectives'])}

## Proposed solution
{bl(n['solution'])}

## How we'll measure success
{bl(n['success_metrics'])}

## Investment
| Item | Amount |
|---|---|
| Plan | {q['plan'].title()} · {q['seats']} seats · {q['years']}-year term |
| List price (annual) | {c} {q['list_annual']:,.0f} |
| Discount | {q['discount']:.0%} |
| **Annual subscription** | **{c} {q['annual']:,.0f}** |
| One-time onboarding | {c} {q['onboarding_fee']:,.0f} |
| **First-year total** | **{c} {q['first_year_total']:,.0f}** |

## Mutual action plan
| Step | Owner | Date |
|---|---|---|
{map_rows}

## Assumptions
{bl(n['assumptions'])}
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--account", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--seats", type=int, required=True)
    ap.add_argument("--years", type=int, default=1)
    ap.add_argument("--discount", type=float, default=0.0, help="extra rep discount, e.g. 0.05")
    ap.add_argument("--notes", required=True)
    ap.add_argument("--brief", default=None)
    ap.add_argument("--pricing", default=str(PRICING))
    ap.add_argument("--out", default=str(ROOT / "out/proposals"))
    a = ap.parse_args(argv)
    q = quote(json.loads(pathlib.Path(a.pricing).read_text()), a.plan, a.seats, a.years, a.discount)
    seller = load_config().get("company", {})
    notes = pathlib.Path(a.notes).read_text(encoding="utf-8")
    brief = pathlib.Path(a.brief).read_text(encoding="utf-8") if a.brief else ""
    mock = {"situation": "[MOCK] " + notes.splitlines()[0], "objectives": ["(needs Claude)"],
            "solution": [seller.get("product_one_liner", "")], "success_metrics": ["(needs Claude)"],
            "mutual_action_plan": [{"step": "Proposal review", "owner": "both", "date": None}],
            "assumptions": ["Seat count confirmed by buyer"]}
    narrative = complete_json(SYSTEM, json.dumps({"seller": seller, "account": a.account, "notes": notes,
                                                  "brief": brief[:15000]}), SCHEMA, mock=mock, max_tokens=2500)
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    path = out / f"{a.account.lower().replace(' ', '-')}-proposal.md"
    path.write_text(render(a.account, seller, narrative, q), encoding="utf-8")
    print(path)
    print(json.dumps(q, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
