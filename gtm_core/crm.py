"""CRM write-back adapters. The pipeline talks to `CRMAdapter`; swap the
implementation per company. All writes are batched upserts on a natural key,
so re-running a job is safe (idempotent).

HubSpot setup: create a unique-value company property `gtm_domain_key`
(single-line text, "require unique values") — HubSpot's built-in `domain`
can't be used as an upsert key.
Salesforce setup: create External ID fields Account.Domain_Key__c and
Contact.Email_Key__c.
"""
from __future__ import annotations

import json
import os
from typing import Iterable, Protocol

from .http import Client


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


class CRMAdapter(Protocol):
    def upsert_accounts(self, accounts: Iterable[dict]) -> int: ...
    def upsert_contacts(self, contacts: Iterable[dict]) -> int: ...


class DryRunCRM:
    """Writes the exact payloads that would be sent to a JSONL file. Default."""

    def __init__(self, path: str = "out/crm_writeback.jsonl"):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        open(self.path, "w").close()

    def _write(self, kind, rows):
        rows = list(rows)
        with open(self.path, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps({"object": kind, **r}, default=str) + "\n")
        return len(rows)

    def upsert_accounts(self, accounts): return self._write("account", accounts)
    def upsert_contacts(self, contacts): return self._write("contact", contacts)


class HubSpotCRM:
    BATCH = 100

    def __init__(self, token: str | None = None):
        token = token or os.environ["HUBSPOT_TOKEN"]
        # HubSpot private apps allow ~100 req / 10s; stay well under it.
        self.c = Client("https://api.hubapi.com", headers={"Authorization": f"Bearer {token}"}, rate_per_sec=8)

    def upsert_accounts(self, accounts):
        inputs = [{
            "idProperty": "gtm_domain_key", "id": a["domain"],
            "properties": {k: v for k, v in {
                "gtm_domain_key": a["domain"], "domain": a["domain"], "name": a.get("name"),
                "industry_raw": a.get("industry"), "numberofemployees": a.get("employees"),
                "country": a.get("country"), "gtm_score": a.get("score"), "gtm_tier": a.get("tier"),
                "gtm_score_reasons": "; ".join(a.get("reasons", []))[:65000] or None,
            }.items() if v not in (None, "")},
        } for a in accounts if a.get("domain")]
        for batch in _chunks(inputs, self.BATCH):
            self.c.post("/crm/v3/objects/companies/batch/upsert", {"inputs": batch})
        return len(inputs)

    def upsert_contacts(self, contacts):
        inputs = [{
            "idProperty": "email", "id": c["email"],
            "properties": {k: v for k, v in {
                "email": c["email"], "firstname": c.get("first_name"), "lastname": c.get("last_name"),
                "jobtitle": c.get("title"), "gtm_committee_role": c.get("committee_role"),
            }.items() if v not in (None, "")},
        } for c in contacts if c.get("email")]
        for batch in _chunks(inputs, self.BATCH):
            self.c.post("/crm/v3/objects/contacts/batch/upsert", {"inputs": batch})
        return len(inputs)


class SalesforceCRM:
    BATCH = 200
    API = "v60.0"

    def __init__(self, instance_url: str | None = None, token: str | None = None):
        self.c = Client(instance_url or os.environ["SF_INSTANCE_URL"],
                        headers={"Authorization": f"Bearer {token or os.environ['SF_ACCESS_TOKEN']}"}, rate_per_sec=10)

    def _upsert(self, sobject, ext_field, records):
        for batch in _chunks(records, self.BATCH):
            self.c.patch(f"/services/data/{self.API}/composite/sobjects/{sobject}/{ext_field}",
                         {"allOrNone": False, "records": batch})
        return len(records)

    def upsert_accounts(self, accounts):
        recs = [{"attributes": {"type": "Account"}, "Domain_Key__c": a["domain"], "Name": a.get("name") or a["domain"],
                 "Website": a["domain"], "NumberOfEmployees": a.get("employees"),
                 "GTM_Score__c": a.get("score"), "GTM_Tier__c": a.get("tier")} for a in accounts if a.get("domain")]
        return self._upsert("Account", "Domain_Key__c", recs)

    def upsert_contacts(self, contacts):
        recs = [{"attributes": {"type": "Contact"}, "Email_Key__c": c["email"], "Email": c["email"],
                 "FirstName": c.get("first_name"), "LastName": c.get("last_name") or "(unknown)",
                 "Title": c.get("title")} for c in contacts if c.get("email")]
        return self._upsert("Contact", "Email_Key__c", recs)


def get_crm(kind: str | None = None) -> CRMAdapter:
    kind = (kind or os.environ.get("GTM_CRM", "dryrun")).lower()
    return {"hubspot": HubSpotCRM, "salesforce": SalesforceCRM}.get(kind, DryRunCRM)()
