#!/usr/bin/env python3
"""Backtest the scoring model against real outcomes before changing weights.

Input: CSV with the scoring columns + `outcome` (1 = became opportunity / won, 0 = not).
Reports, per tier: count, conversion rate, lift vs baseline — and per
reason: how often it appears in converters vs non-converters. If tier A
doesn't convert clearly better than C, the model isn't working; fix weights,
re-run, compare. Ship the change only when lift improves.

    python skills/lead-scoring/scripts/backtest.py history.csv
"""
from __future__ import annotations

import argparse
import csv
import pathlib
import re
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from gtm_core import normalize as n  # noqa: E402
from gtm_core.config import load_config  # noqa: E402
from gtm_core.scoring import score_account  # noqa: E402


def backtest(rows: list[dict], cfg: dict) -> dict:
    by_tier = defaultdict(lambda: [0, 0])
    reason_hits = defaultdict(lambda: [0, 0])  # [converted, not]
    total_conv = 0
    for r in rows:
        y = int(r["outcome"])
        total_conv += y
        acct = {"industry": (r.get("industry") or "").lower(), "employees": n.to_int(r.get("employees")),
                "country": n.country(r.get("country")), "tech_stack": n.split_list(r.get("tech_stack"))}
        res = score_account(acct, [], cfg, contact_titles=[r.get("title")])
        by_tier[res["tier"]][0] += 1
        by_tier[res["tier"]][1] += y
        for reason in res["reasons"]:
            key = re.sub(r"\(.*?\)|\d+", "#", reason.split(" ", 1)[1])  # generalise "headcount 320 in 50-2000"
            reason_hits[key][0 if y else 1] += 1
    base = total_conv / len(rows) if rows else 0
    tiers = {t: {"n": c, "conv_rate": round(k / c, 3), "lift": round((k / c) / base, 2) if base else None}
             for t, (c, k) in sorted(by_tier.items())}
    pos, neg = max(total_conv, 1), max(len(rows) - total_conv, 1)
    reasons = {k: {"in_converters": round(a / pos, 2), "in_non": round(b / neg, 2)} for k, (a, b) in reason_hits.items()}
    return {"rows": len(rows), "baseline_conv": round(base, 3), "tiers": tiers, "reasons": reasons}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--config", default=None)
    a = ap.parse_args(argv)
    res = backtest(list(csv.DictReader(open(a.path, newline="", encoding="utf-8"))), load_config(a.config))
    print(f"rows={res['rows']} baseline conversion={res['baseline_conv']:.1%}\n")
    print("tier      n   conv   lift")
    for t, v in res["tiers"].items():
        print(f"{t:<5}{v['n']:>6}  {v['conv_rate']:>5.1%}  {v['lift']}")
    print("\nreason (share of converters vs non-converters) — big gap = predictive")
    for k, v in sorted(res["reasons"].items(), key=lambda x: -(x[1]["in_converters"] - x[1]["in_non"])):
        print(f"  {v['in_converters']:>4.0%} vs {v['in_non']:>4.0%}  {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
