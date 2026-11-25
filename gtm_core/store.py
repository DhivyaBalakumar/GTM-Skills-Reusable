"""SQLite-backed central data layer. Swap the connection for Postgres in prod;
all writes are idempotent upserts keyed on natural keys (domain, email)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

SCHEMA = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"


def connect(path: str = "gtm.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    return conn


def upsert_account(conn, a: dict) -> int:
    conn.execute(
        """INSERT INTO accounts(domain,name,industry,employees,country,owner_email,tech_stack)
           VALUES(:domain,:name,:industry,:employees,:country,:owner,:tech)
           ON CONFLICT(domain) DO UPDATE SET
             name=COALESCE(excluded.name,accounts.name),
             industry=COALESCE(excluded.industry,accounts.industry),
             employees=COALESCE(excluded.employees,accounts.employees),
             country=COALESCE(excluded.country,accounts.country),
             owner_email=COALESCE(excluded.owner_email,accounts.owner_email),  -- CRM owner wins; else keep routed owner
             tech_stack=excluded.tech_stack,
             updated_at=CURRENT_TIMESTAMP""",
        {**{k: a.get(k) for k in ("domain", "name", "industry", "employees", "country", "owner")},
         "tech": json.dumps(a.get("tech_stack") or [])},
    )
    return conn.execute("SELECT account_id FROM accounts WHERE domain=?", (a["domain"],)).fetchone()[0]


def upsert_contact(conn, c: dict, account_id: int | None) -> int:
    conn.execute(
        """INSERT INTO contacts(email,account_id,first_name,last_name,title,seniority)
           VALUES(:email,:account_id,:first_name,:last_name,:title,:seniority)
           ON CONFLICT(email) DO UPDATE SET
             account_id=COALESCE(excluded.account_id,contacts.account_id),
             first_name=COALESCE(excluded.first_name,contacts.first_name),
             last_name=COALESCE(excluded.last_name,contacts.last_name),
             title=COALESCE(excluded.title,contacts.title),
             seniority=COALESCE(excluded.seniority,contacts.seniority),
             updated_at=CURRENT_TIMESTAMP""",
        {**{k: c.get(k) for k in ("email", "first_name", "last_name", "title", "seniority")}, "account_id": account_id},
    )
    cid = conn.execute("SELECT contact_id FROM contacts WHERE email=?", (c["email"],)).fetchone()[0]
    if account_id and c.get("committee_role"):
        # rule-based guess never overwrites a rep's manual assignment
        conn.execute(
            """INSERT INTO buying_committee(account_id,contact_id,role,source,confidence)
               VALUES(?,?,?,'rule',0.6)
               ON CONFLICT(account_id,contact_id,role) DO NOTHING""",
            (account_id, cid, c["committee_role"]),
        )
    return cid


def insert_signal(conn, s: dict) -> bool:
    key = hashlib.sha256(json.dumps([s["domain"], s["type"], s["occurred_at"], s.get("detail")]).encode()).hexdigest()
    cur = conn.execute(
        """INSERT OR IGNORE INTO signals(domain,type,occurred_at,detail,source,dedupe_key)
           VALUES(?,?,?,?,?,?)""",
        (s["domain"], s["type"], s["occurred_at"], s.get("detail"), s.get("source"), key),
    )
    return cur.rowcount == 1


def record_source(conn, source: str, source_id: str, entity: str, golden_key: str, payload: dict) -> None:
    conn.execute(
        """INSERT INTO source_records(source,source_id,entity_type,golden_key,payload)
           VALUES(?,?,?,?,?)
           ON CONFLICT(source,source_id,entity_type) DO UPDATE SET
             golden_key=excluded.golden_key, payload=excluded.payload, ingested_at=CURRENT_TIMESTAMP""",
        (source, str(source_id), entity, golden_key, json.dumps(payload, default=str)),
    )


def write_score(conn, account_id: int, result: dict, model_version: str, scored_at: str) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO account_scores(account_id,scored_at,model_version,fit_score,intent_score,score,tier,reasons)
           VALUES(?,?,?,?,?,?,?,?)""",
        (account_id, scored_at, model_version, result["fit_score"], result["intent_score"],
         result["score"], result["tier"], json.dumps(result["reasons"])),
    )


def config_version(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg["scoring"], sort_keys=True).encode()).hexdigest()[:12]
