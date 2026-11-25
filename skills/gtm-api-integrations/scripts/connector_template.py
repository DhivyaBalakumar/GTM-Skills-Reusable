#!/usr/bin/env python3
"""Template for adding a new GTM data source (Apollo, Clay export, Clearbit,
6sense, website visitors, product usage...). Copy, rename, fill the TODOs.

Contract every connector follows:
  1. incremental: keep a watermark (last updated_at / cursor) in state, pull only changes
  2. paginate with the shared Client (retries, rate limits, Retry-After)
  3. map vendor fields -> canonical shape (see gtm_core.dedupe.account_from_row)
  4. write raw rows to a landing file (replayable), never straight into the CRM
  5. advance the watermark ONLY after the batch is durably written
  6. run under gtm_core.jobs.run_job so failures alert and are visible

    python skills/gtm-api-integrations/scripts/connector_template.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from gtm_core.http import Client, paginate  # noqa: E402
from gtm_core.jobs import run_job, setup_logging  # noqa: E402

NAME = "example_vendor"                      # TODO
BASE_URL = "https://api.example-vendor.com"  # TODO
STATE = ROOT / "out/state" / f"{NAME}.json"
LANDING = ROOT / "out/landing" / NAME


def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"watermark": "1970-01-01T00:00:00Z"}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(STATE)  # atomic


def to_canonical(rec: dict) -> dict:
    # TODO: map vendor fields
    return {"source_id": rec.get("id"), "name": rec.get("name"), "domain": rec.get("website"),
            "industry": rec.get("industry"), "employees": rec.get("employee_count"),
            "country": rec.get("country"), "tech_stack": rec.get("technologies"), "updated_at": rec.get("updated_at")}


def fetch(client: Client, since: str):
    # TODO: adjust endpoint, params and cursor shape to the vendor's API
    yield from paginate(client, "/v1/companies", params={"updated_since": since, "limit": 100},
                        results_key="data", cursor_path=("next_cursor",), cursor_param="cursor")


def sync(dl, dry_run: bool) -> dict:
    state = load_state()
    if dry_run:
        rows = [{"id": "1", "name": "Demo Co", "website": "democo.com", "updated_at": datetime.now(timezone.utc).isoformat()}]
    else:
        client = Client(BASE_URL, headers={"Authorization": f"Bearer {os.environ[NAME.upper() + '_API_KEY']}"}, rate_per_sec=2)
        rows = fetch(client, state["watermark"])
    LANDING.mkdir(parents=True, exist_ok=True)
    out = LANDING / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.jsonl"
    n, max_wm = 0, state["watermark"]
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            try:
                c = to_canonical(r)
                f.write(json.dumps(c) + "\n")
                n += 1
                max_wm = max(max_wm, c.get("updated_at") or max_wm)
            except Exception as e:  # noqa: BLE001
                dl.add(r, e)
    save_state({"watermark": max_wm, "last_file": str(out)})
    return {"records_in": n, "records_out": n}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    setup_logging()
    print(json.dumps(run_job(f"connector_{NAME}", lambda dl: sync(dl, a.dry_run), retries=2, backoff_s=2)))
