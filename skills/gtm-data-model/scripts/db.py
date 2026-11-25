#!/usr/bin/env python3
"""Create / inspect the central GTM database.

    python skills/gtm-data-model/scripts/db.py init  --db out/gtm.db
    python skills/gtm-data-model/scripts/db.py query --db out/gtm.db 2      # run query #2 from sql/queries.sql
    python skills/gtm-data-model/scripts/db.py sql   --db out/gtm.db "SELECT COUNT(*) FROM accounts"
    python skills/gtm-data-model/scripts/db.py describe --db out/gtm.db
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from gtm_core import store  # noqa: E402


def named_queries() -> dict[str, str]:
    text = (ROOT / "sql/queries.sql").read_text()
    parts = re.split(r"^-- (\d+)\. .*$", text, flags=re.M)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


def show(cur) -> None:
    rows = cur.fetchall()
    if not rows:
        print("(no rows)"); return
    cols = rows[0].keys()
    widths = [max(len(str(c)), *(min(len(str(r[c])), 60) for r in rows)) for c in cols]
    print(" | ".join(str(c).ljust(w) for c, w in zip(cols, widths)))
    print("-+-".join("-" * w for w in widths))
    for r in rows:
        print(" | ".join(str(r[c])[:60].ljust(w) for c, w in zip(cols, widths)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["init", "query", "sql", "describe"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--db", default=str(ROOT / "out/gtm.db"))
    a = ap.parse_args(argv)
    pathlib.Path(a.db).parent.mkdir(parents=True, exist_ok=True)
    conn = store.connect(a.db)
    if a.cmd == "init":
        print(f"schema applied to {a.db}")
    elif a.cmd == "describe":
        for (name, typ) in conn.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY type, name"):
            n = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            print(f"{typ:<5} {name:<24} {n} rows")
    elif a.cmd == "query":
        q = named_queries()
        if a.arg not in q:
            sys.exit(f"query must be one of {sorted(q, key=int)}")
        show(conn.execute(q[a.arg].rstrip(";")))
    elif a.cmd == "sql":
        show(conn.execute(a.arg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
