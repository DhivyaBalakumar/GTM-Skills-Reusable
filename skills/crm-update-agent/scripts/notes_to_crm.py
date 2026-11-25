#!/usr/bin/env python3
"""Call notes / transcript -> validated CRM update proposal.

Claude extracts structured fields (stage, next step, close date, MEDDPICC,
new contacts, tasks). Python then *validates* every field against allowed
values, diffs against the current CRM record, and splits changes into:
  auto_apply   high-confidence, low-risk fields (next step, tasks, notes)
  needs_review anything touching stage, amount, close date, or low confidence
so the AE approves in one click instead of typing — and nothing risky is
written silently.

    python skills/crm-update-agent/scripts/notes_to_crm.py examples/data/call_notes_acme.txt \
        --current '{"stage":"discovery","amount":null,"close_date":null}'
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from gtm_core.llm import complete_json  # noqa: E402

STAGES = ["prospecting", "discovery", "evaluation", "proposal", "negotiation", "closed_won", "closed_lost"]
RISKY = {"stage", "amount", "close_date"}
AUTO_MIN_CONFIDENCE = 0.8

SCHEMA = {"fields": dict, "contacts": list, "tasks": list, "summary": str}
SYSTEM = f"""You update a CRM from a sales call. Extract ONLY what was said.
Return JSON:
{{"summary": "<=3 sentence call summary",
  "fields": {{ "<field>": {{"value": ..., "confidence": 0-1, "evidence": "short quote from notes"}} }},
  "contacts": [{{"name","title","email"|null,"role": "economic_buyer|champion|technical_evaluator|end_user|blocker"}}],
  "tasks": [{{"owner":"rep|prospect","task","due": "YYYY-MM-DD"|null}}]}}
Allowed fields: stage ({'|'.join(STAGES)}), amount (number), close_date (YYYY-MM-DD), next_step (text),
metrics, economic_buyer, decision_criteria, decision_process, paper_process, pain, champion, competition.
Omit a field if not discussed. Never guess amounts or dates."""


def validate(fields: dict) -> tuple[dict, list[str]]:
    ok, errors = {}, []
    for k, f in fields.items():
        v, conf = f.get("value"), float(f.get("confidence", 0))
        if k == "stage" and v not in STAGES:
            errors.append(f"stage '{v}' not in {STAGES}"); continue
        if k == "amount":
            try:
                v = float(v)
            except (TypeError, ValueError):
                errors.append(f"amount '{v}' not numeric"); continue
        if k == "close_date":
            try:
                if date.fromisoformat(str(v)) < date.today():
                    errors.append(f"close_date {v} is in the past"); continue
            except ValueError:
                errors.append(f"close_date '{v}' not YYYY-MM-DD"); continue
        if not f.get("evidence"):
            errors.append(f"{k}: no evidence quote — dropped"); continue
        ok[k] = {"value": v, "confidence": conf, "evidence": f["evidence"]}
    return ok, errors


def plan(extracted: dict, current: dict) -> dict:
    fields, errors = validate(extracted.get("fields", {}))
    auto, review = {}, {}
    for k, f in fields.items():
        if current.get(k) == f["value"]:
            continue  # no change
        change = {"from": current.get(k), "to": f["value"], "confidence": f["confidence"], "evidence": f["evidence"]}
        if k in RISKY or f["confidence"] < AUTO_MIN_CONFIDENCE:
            review[k] = change
        else:
            auto[k] = change
    if "stage" in review and current.get("stage") in STAGES and review["stage"]["to"] in STAGES:
        jump = STAGES.index(review["stage"]["to"]) - STAGES.index(current["stage"])
        if jump > 1:
            review["stage"]["warning"] = f"skips {jump - 1} stage(s) — confirm exit criteria were met"
    return {"summary": extracted.get("summary"), "auto_apply": auto, "needs_review": review,
            "new_contacts": extracted.get("contacts", []), "tasks": extracted.get("tasks", []),
            "validation_errors": errors}


def mock_extract(notes: str) -> dict:
    """Offline heuristic so the pipeline is testable without an API key."""
    out = {"summary": "[MOCK] " + notes.strip().splitlines()[0][:200], "fields": {}, "contacts": [], "tasks": []}
    m = re.search(r"next step[s]?:\s*(.+)", notes, re.I)
    if m:
        out["fields"]["next_step"] = {"value": m.group(1).strip(), "confidence": 0.9, "evidence": m.group(0)[:120]}
    m = re.search(r"budget[^\d$€£]*([$€£]?\s?[\d,.]+k?)", notes, re.I)
    if m:
        raw = m.group(1).replace(",", "").replace("$", "").replace("€", "").replace("£", "").strip()
        val = float(raw[:-1]) * 1000 if raw.lower().endswith("k") else float(raw)
        out["fields"]["amount"] = {"value": val, "confidence": 0.7, "evidence": m.group(0)[:120]}
    if re.search(r"\b(send|share) (a |the )?proposal\b", notes, re.I):
        out["fields"]["stage"] = {"value": "proposal", "confidence": 0.75, "evidence": "proposal requested"}
        out["tasks"].append({"owner": "rep", "task": "Send proposal", "due": None})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("notes_file")
    ap.add_argument("--current", default="{}", help="current CRM deal fields as JSON")
    a = ap.parse_args(argv)
    notes = pathlib.Path(a.notes_file).read_text(encoding="utf-8")
    current = json.loads(a.current)
    extracted = complete_json(SYSTEM, f"CURRENT RECORD:\n{json.dumps(current)}\n\nNOTES:\n{notes[:40000]}",
                              SCHEMA, mock=mock_extract(notes), max_tokens=2000)
    print(json.dumps(plan(extracted, current), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
