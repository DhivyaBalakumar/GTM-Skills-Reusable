#!/usr/bin/env python3
"""Inspect and replay dead-lettered records after a fix ships.

    python skills/gtm-reliability-ops/scripts/replay_dead_letter.py --list
    python skills/gtm-reliability-ops/scripts/replay_dead_letter.py --export out/dlq.jsonl --job account_pipeline
    python skills/gtm-reliability-ops/scripts/replay_dead_letter.py --mark-replayed 12 13 14

Replay = export the payloads, fix the data or code, feed them back through
the normal pipeline (as a source file), then mark them replayed. Rows are
never deleted, so the history of what broke stays auditable.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from gtm_core import store  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(ROOT / "out/gtm.db"))
    ap.add_argument("--job")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--export")
    ap.add_argument("--mark-replayed", nargs="*", type=int)
    a = ap.parse_args(argv)
    conn = store.connect(a.db)
    where, params = "WHERE replayed_at IS NULL", []
    if a.job:
        where += " AND job_name=?"; params.append(a.job)
    rows = conn.execute(f"SELECT id, job_name, error, payload, created_at FROM dead_letter {where} ORDER BY id", params).fetchall()
    if a.list or not (a.export or a.mark_replayed):
        by_err: dict[str, int] = {}
        for r in rows:
            by_err[f"{r['job_name']} | {r['error'][:80]}"] = by_err.get(f"{r['job_name']} | {r['error'][:80]}", 0) + 1
        for k, v in sorted(by_err.items(), key=lambda x: -x[1]):
            print(f"{v:>5}  {k}")
        print(f"total unreplayed: {len(rows)}")
    if a.export:
        with open(a.export, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps({"dlq_id": r["id"], **json.loads(r["payload"])}) + "\n")
        print(f"exported {len(rows)} -> {a.export}")
    if a.mark_replayed:
        conn.executemany("UPDATE dead_letter SET replayed_at=CURRENT_TIMESTAMP WHERE id=?", [(i,) for i in a.mark_replayed])
        conn.commit()
        print(f"marked {len(a.mark_replayed)} replayed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
