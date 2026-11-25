#!/usr/bin/env python3
"""Multi-source account pipeline: ingest -> normalise -> dedupe -> load -> score -> CRM write-back.

    python skills/account-data-pipeline/scripts/run_pipeline.py \
        --sources skills/account-data-pipeline/sources.example.json --db gtm.db --crm dryrun

Idempotent: re-running with the same inputs produces the same golden records
and no duplicate signals. Wrapped in the reliability job runner (lock,
retries, dead-letter, alert on failure, job_runs row).
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from gtm_core import dedupe, normalize as n, store  # noqa: E402
from gtm_core.config import load_config  # noqa: E402
from gtm_core.crm import get_crm  # noqa: E402
from gtm_core.jobs import run_job, setup_logging  # noqa: E402
from gtm_core.scoring import score_account  # noqa: E402


def _read(path: str):
    p = ROOT / path if not pathlib.Path(path).is_absolute() else pathlib.Path(path)
    if p.suffix == ".jsonl":
        with open(p, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build(sources: dict, cfg: dict, conn, crm, dl, now: datetime) -> dict:
    priorities = {s["source"]: s.get("priority", 1) for s in sources["accounts"]}
    role_map = cfg["icp"]["buying_committee_roles"]

    # ---- ingest + normalise accounts
    raw_accounts, n_in = [], 0
    for src in sources["accounts"]:
        for row in _read(src["path"]):
            n_in += 1
            try:
                rec = dedupe.account_from_row(row, src["source"], src["mapping"])
                if not rec["domain"] and not rec["name_key"]:
                    raise ValueError("record has neither domain nor name")
                raw_accounts.append(rec)
            except Exception as e:  # noqa: BLE001
                dl.add({"source": src["source"], "row": row}, e)

    golden_accounts = dedupe.dedupe_accounts(raw_accounts, priorities)
    # domainless survivors cannot be keyed in the CRM: surface for manual review
    keyed = [a for a in golden_accounts if a.get("domain")]
    for a in golden_accounts:
        if not a.get("domain"):
            dl.add(a, "no domain after dedupe — needs manual enrichment")

    # ---- contacts
    raw_contacts = []
    for src in sources.get("contacts", []):
        for row in _read(src["path"]):
            n_in += 1
            raw_contacts.append(dedupe.contact_from_row(row, row.get(src.get("source_column", "source"), "manual"), role_map))
    contacts = dedupe.dedupe_contacts(raw_contacts, priorities)
    for c in [c for c in contacts if c.get("_reject_reason")]:
        dl.add(c, c["_reject_reason"])
    contacts = [c for c in contacts if not c.get("_reject_reason")]

    # ---- signals
    signals_by_domain: dict[str, list] = {}
    new_signals = 0
    for src in sources.get("signals", []):
        for s in _read(src["path"]):
            n_in += 1
            s["domain"] = n.domain(s.get("domain"))
            if not s["domain"]:
                dl.add(s, "signal without domain"); continue
            new_signals += store.insert_signal(conn, s)
            signals_by_domain.setdefault(s["domain"], []).append(s)

    # ---- load golden records
    ids = {}
    for a in keyed:
        ids[a["domain"]] = store.upsert_account(conn, a)
        for lin in a["_lineage"]:
            src, sid = lin.split(":", 1)
            store.record_source(conn, src, sid, "account", a["domain"], a)
    titles_by_domain: dict[str, list] = {}
    for c in contacts:
        store.upsert_contact(conn, c, ids.get(c.get("account_domain")))
        titles_by_domain.setdefault(c.get("account_domain"), []).append(c.get("title"))

    # ---- score
    version, scored_at = store.config_version(cfg), now.isoformat(timespec="seconds")
    scored = []
    for a in keyed:
        res = score_account(a, signals_by_domain.get(a["domain"], []), cfg,
                            titles_by_domain.get(a["domain"], []), now=now)
        store.write_score(conn, ids[a["domain"]], res, version, scored_at)
        scored.append({**a, **res})
    conn.commit()

    # ---- write back to CRM (single source of truth)
    pushed_a = crm.upsert_accounts(scored)
    pushed_c = crm.upsert_contacts(contacts)

    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    with open(out / "scored_accounts.json", "w", encoding="utf-8") as f:
        json.dump(sorted(scored, key=lambda x: -x["score"]), f, indent=2, default=str)

    return {"records_in": n_in, "records_out": pushed_a + pushed_c, "accounts": len(keyed),
            "contacts": len(contacts), "new_signals": new_signals,
            "merged_from": len(raw_accounts), "scoring_version": version}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sources", default=str(ROOT / "skills/account-data-pipeline/sources.example.json"))
    ap.add_argument("--config", default=None)
    ap.add_argument("--db", default=str(ROOT / "out/gtm.db"))
    ap.add_argument("--crm", default=None, help="dryrun | hubspot | salesforce (default $GTM_CRM or dryrun)")
    ap.add_argument("--now", default=None, help="ISO timestamp to score 'as of' (for backfills/tests)")
    args = ap.parse_args(argv)

    setup_logging()
    (ROOT / "out").mkdir(exist_ok=True)
    cfg = load_config(args.config)
    sources = json.loads(pathlib.Path(args.sources).read_text())
    conn = store.connect(args.db)
    crm = get_crm(args.crm)
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)
    result = run_job("account_pipeline", lambda dl: build(sources, cfg, conn, crm, dl, now), conn=conn, retries=1, backoff_s=1)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
