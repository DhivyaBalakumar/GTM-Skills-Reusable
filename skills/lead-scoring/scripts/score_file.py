#!/usr/bin/env python3
"""Score any CSV/JSONL of accounts or leads ad hoc (no DB needed).

Columns understood: domain, industry, employees, country, tech_stack, title,
plus optional signals_json (JSON list of {type, occurred_at, detail}).

    python skills/lead-scoring/scripts/score_file.py leads.csv --out scored.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from gtm_core import normalize as n  # noqa: E402
from gtm_core.config import load_config  # noqa: E402
from gtm_core.scoring import score_account  # noqa: E402


def read_rows(path: str):
    if path.endswith(".jsonl"):
        return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    return list(csv.DictReader(open(path, newline="", encoding="utf-8")))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    out_rows = []
    for row in read_rows(a.path):
        acct = {"domain": n.domain(row.get("domain") or row.get("email")),
                "industry": (row.get("industry") or "").lower() or None,
                "employees": n.to_int(row.get("employees")), "country": n.country(row.get("country")),
                "tech_stack": n.split_list(row.get("tech_stack"))}
        sigs = row.get("signals_json") or []
        sigs = json.loads(sigs) if isinstance(sigs, str) else list(sigs)
        if row.get("form") and row.get("created_at"):  # an inbound form fill is itself an intent signal
            sigs.append({"type": row["form"], "occurred_at": row["created_at"], "detail": row.get("message")})
        res = score_account(acct, sigs, cfg, contact_titles=[row.get("title")])
        out_rows.append({**row, "score": res["score"], "tier": res["tier"],
                         "fit_score": res["fit_score"], "intent_score": res["intent_score"],
                         "reasons": " | ".join(res["reasons"])})
    out_rows.sort(key=lambda r: -r["score"])
    if a.out:
        with open(a.out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
            w.writeheader(); w.writerows(out_rows)
        print(f"wrote {len(out_rows)} rows -> {a.out}")
    else:
        for r in out_rows:
            print(f"{r['tier']} {r['score']:>5}  {r.get('domain') or r.get('email')}  {r['reasons'][:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
