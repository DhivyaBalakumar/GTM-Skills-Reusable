"""Entity resolution for accounts and contacts.

Accounts match on (1) normalised domain, then (2) fuzzy normalised name
when one side has no domain. Contacts match on normalised email.
Field values are chosen by survivorship rules: highest-priority source
wins, ties broken by most-recent, and nulls never overwrite values.
Every golden record keeps lineage (which source ids were merged).
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Iterable

from . import normalize as n

DEFAULT_SOURCE_PRIORITY = {"crm": 3, "enrichment": 2, "manual": 1}
NAME_MATCH_THRESHOLD = 0.92


def _priority(rec: dict, priorities: dict[str, int]) -> tuple[int, str]:
    return (priorities.get(rec.get("_source", ""), 0), rec.get("_updated_at") or "")


def _survive(records: list[dict], priorities: dict[str, int]) -> dict:
    """Merge records describing the same entity into one golden record."""
    ordered = sorted(records, key=lambda r: _priority(r, priorities), reverse=True)
    golden: dict = {}
    for rec in ordered:
        for k, v in rec.items():
            if k.startswith("_"):
                continue
            if isinstance(v, list):
                # list fields (tech stack) are unioned, not overwritten
                golden[k] = sorted(set(golden.get(k, [])) | set(v))
            elif golden.get(k) in (None, "") and v not in (None, ""):
                golden[k] = v
    golden["_lineage"] = sorted(f"{r.get('_source')}:{r.get('_source_id')}" for r in records)
    golden["_sources"] = sorted({r.get("_source") for r in records})
    return golden


def dedupe_accounts(records: Iterable[dict], priorities: dict[str, int] | None = None) -> list[dict]:
    priorities = priorities or DEFAULT_SOURCE_PRIORITY
    by_domain: dict[str, list[dict]] = {}
    no_domain: list[dict] = []
    for r in records:
        (by_domain.setdefault(r["domain"], []) if r.get("domain") else no_domain).append(r)

    # Fuzzy-attach domainless records to a domain cluster by name, else keep alone.
    clusters = list(by_domain.values())
    for r in no_domain:
        key = r.get("name_key") or ""
        best, best_score = None, 0.0
        for cl in clusters:
            score = max(SequenceMatcher(None, key, c.get("name_key") or "").ratio() for c in cl)
            if score > best_score:
                best, best_score = cl, score
        if best is not None and best_score >= NAME_MATCH_THRESHOLD:
            best.append(r)
        else:
            clusters.append([r])
    return [_survive(cl, priorities) for cl in clusters]


def dedupe_contacts(records: Iterable[dict], priorities: dict[str, int] | None = None) -> list[dict]:
    priorities = priorities or DEFAULT_SOURCE_PRIORITY
    by_email: dict[str, list[dict]] = {}
    rejects = []
    for r in records:
        if r.get("email"):
            by_email.setdefault(r["email"], []).append(r)
        else:
            rejects.append(r)
    out = [_survive(cl, priorities) for cl in by_email.values()]
    # contacts without a valid email are surfaced, not silently dropped
    for r in rejects:
        r = dict(r)
        r["_reject_reason"] = "missing_or_invalid_email"
        out.append(r)
    return out


def account_from_row(row: dict, source: str, mapping: dict[str, str]) -> dict:
    """Map a raw source row to the canonical account shape using a column mapping."""
    g = lambda field: row.get(mapping.get(field, field))  # noqa: E731
    name = g("name")
    return {
        "_source": source,
        "_source_id": g("source_id"),
        "_updated_at": g("updated_at"),
        "name": (name or "").strip() or None,
        "name_key": n.company_name(name),
        "domain": n.domain(g("domain")),
        "industry": (g("industry") or "").strip().lower() or None,
        "employees": n.to_int(g("employees")),
        "country": n.country(g("country")),
        "owner": (g("owner") or "").strip().lower() or None,
        "tech_stack": n.split_list(g("tech_stack")),
    }


def contact_from_row(row: dict, source: str, role_map: dict[str, list[str]]) -> dict:
    title = (row.get("title") or "").strip() or None
    return {
        "_source": source,
        "_source_id": row.get("email"),
        "email": n.email(row.get("email")),
        "first_name": (row.get("first_name") or "").strip() or None,
        "last_name": (row.get("last_name") or "").strip() or None,
        "title": title,
        "seniority": n.seniority(title),
        "committee_role": n.committee_role(title, role_map),
        "account_domain": n.domain(row.get("company_domain") or row.get("email")),
    }
