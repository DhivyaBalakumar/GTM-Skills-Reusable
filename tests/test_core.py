"""Unit + integration tests. Run: python -m pytest -q   (or python -m unittest)"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile
import time
import unittest
import urllib.error
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["GTM_LLM_MOCK"] = "1"

from gtm_core import dedupe, normalize as n, store  # noqa: E402
from gtm_core.config import load_config  # noqa: E402
from gtm_core.http import Client  # noqa: E402
from gtm_core.jobs import run_job  # noqa: E402
from gtm_core.routing import RoundRobin, route_lead  # noqa: E402
from gtm_core.scoring import intent_score, score_account  # noqa: E402

CFG = load_config(ROOT / "config/gtm.config.example.json")
NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)


def load_script(rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(mod)
    return mod


class TestNormalize(unittest.TestCase):
    def test_domain(self):
        for raw in ["https://www.Acme.com/about", "acme.com", "WWW.ACME.COM", "jane@acme.com"]:
            self.assertEqual(n.domain(raw), "acme.com")
        self.assertIsNone(n.domain(""))

    def test_company_name(self):
        self.assertEqual(n.company_name("ACME Analytics, Inc."), n.company_name("Acme Analytics"))
        self.assertEqual(n.company_name("Globex Logistics GmbH"), "globex logistics")

    def test_country(self):
        self.assertEqual(n.country("United States"), "US")
        self.assertEqual(n.country("de"), "DE")

    def test_seniority_and_roles(self):
        roles = CFG["icp"]["buying_committee_roles"]
        self.assertEqual(n.seniority("VP of Sales"), "vp")
        self.assertEqual(n.committee_role("VP of Sales", roles), "economic_buyer")
        self.assertEqual(n.committee_role("RevOps Manager", roles), "champion")
        self.assertIsNone(n.committee_role("Chef", roles))


class TestDedupe(unittest.TestCase):
    def test_merge_with_priority_and_lineage(self):
        m = {"source_id": "id", "name": "name", "domain": "domain", "employees": "emp", "tech_stack": "tech", "owner": "owner"}
        a = dedupe.account_from_row({"id": "1", "name": "Acme Inc", "domain": "acme.com", "emp": "300", "tech": "salesforce", "owner": "a@x.com"}, "crm", m)
        b = dedupe.account_from_row({"id": "9", "name": "ACME", "domain": "https://www.acme.com", "emp": "340", "tech": "snowflake"}, "enrichment", m)
        c = dedupe.account_from_row({"id": "7", "name": "Acme Inc.", "domain": ""}, "manual", m)
        out = dedupe.dedupe_accounts([b, a, c])
        self.assertEqual(len(out), 1)
        g = out[0]
        self.assertEqual(g["employees"], 300)            # crm beats enrichment
        self.assertEqual(g["tech_stack"], ["salesforce", "snowflake"])  # lists unioned
        self.assertEqual(len(g["_lineage"]), 3)          # domainless record fuzzy-matched by name

    def test_contacts_reject_bad_email(self):
        roles = CFG["icp"]["buying_committee_roles"]
        rows = [dedupe.contact_from_row({"email": "JANE@acme.com", "title": "CFO"}, "crm", roles),
                dedupe.contact_from_row({"email": "jane@acme.com", "title": "Chief Financial Officer"}, "enrichment", roles),
                dedupe.contact_from_row({"email": "not-an-email"}, "crm", roles)]
        out = dedupe.dedupe_contacts(rows)
        good = [c for c in out if not c.get("_reject_reason")]
        self.assertEqual(len(good), 1)
        self.assertEqual(good[0]["title"], "CFO")
        self.assertEqual(sum(1 for c in out if c.get("_reject_reason")), 1)


class TestScoring(unittest.TestCase):
    def test_intent_decays(self):
        fresh, _ = intent_score([{"type": "demo_request", "occurred_at": "2026-11-25T12:00:00Z"}], CFG, NOW)
        old, _ = intent_score([{"type": "demo_request", "occurred_at": "2026-11-11T12:00:00Z"}], CFG, NOW)
        self.assertAlmostEqual(fresh, 40, places=3)
        self.assertAlmostEqual(old, 20, places=3)  # one half-life

    def test_negative_tech_and_tiers(self):
        acct = {"industry": "software", "employees": 300, "country": "US", "tech_stack": ["competitor-x"]}
        r = score_account(acct, [], CFG, now=NOW)
        self.assertEqual(r["fit_score"], 25)
        self.assertTrue(any("competitor-x" in x for x in r["reasons"]))
        self.assertEqual(r["tier"], "D")


class TestRouting(unittest.TestCase):
    def lead(self, **kw):
        base = {"lead_id": "x", "email": "a@co.com", "company": "Co", "title": "Director of Sales", "country": "US",
                "employees": 200, "industry": "software", "form": "demo_request", "created_at": "2026-11-25T11:00:00Z"}
        return {**base, **kw}

    def test_rules(self):
        rr = RoundRobin()
        self.assertEqual(route_lead(self.lead(email="x@gmail.com", company=""), CFG, {}, rr, now=NOW)["rule"],
                         "disqualified:free_email_no_company")
        self.assertEqual(route_lead(self.lead(title="Student"), CFG, {}, rr, now=NOW)["rule"], "disqualified:title")
        owned = {"co.com": {"domain": "co.com", "owner": "zoe@yourco.com", "country": "US"}}
        self.assertEqual(route_lead(self.lead(), CFG, owned, rr, now=NOW)["assigned_to"], "zoe@yourco.com")
        self.assertEqual(route_lead(self.lead(employees=5000), CFG, {}, rr, now=NOW)["rule"], "enterprise_pod")
        self.assertEqual(route_lead(self.lead(country="BR"), CFG, {}, rr, now=NOW)["rule"], "fallback_queue")

    def test_round_robin_balances(self):
        rr = RoundRobin({"alice@yourco.com": 3})
        picks = [route_lead(self.lead(lead_id=str(i)), CFG, {}, rr, now=NOW)["assigned_to"] for i in range(4)]
        self.assertEqual(picks[:3], ["bob@yourco.com"] * 3)  # least-loaded first

    def test_sla(self):
        r = route_lead(self.lead(), CFG, {}, RoundRobin(), now=NOW)
        self.assertEqual(r["tier"], "A")
        self.assertEqual(r["sla_due_at"], "2026-11-25T11:05:00+00:00")


class FakeResp(io.BytesIO):
    status = 200
    def __enter__(self): return self
    def __exit__(self, *a): self.close()


class TestHttp(unittest.TestCase):
    def test_retries_on_429_then_succeeds(self):
        calls = {"n": 0}

        def opener(req, timeout):
            calls["n"] += 1
            if calls["n"] < 3:
                raise urllib.error.HTTPError(req.full_url, 429, "slow down", {"Retry-After": "0"}, io.BytesIO(b""))
            return FakeResp(b'{"ok": true}')

        c = Client("https://api.test", rate_per_sec=100, backoff_base=0)
        c._opener = opener
        self.assertEqual(c.post("/x", {"a": 1}), {"ok": True})
        self.assertEqual(calls["n"], 3)

    def test_no_retry_on_400(self):
        def opener(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, io.BytesIO(b"bad input"))
        c = Client("https://api.test", rate_per_sec=100)
        c._opener = opener
        with self.assertRaises(Exception) as cm:
            c.get("/x")
        self.assertIn("400", str(cm.exception))


class TestJobs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(os.path.join(self.tmp.name, "t.db"))
        self.cwd = os.getcwd(); os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.cwd); self.tmp.cleanup()

    def test_success_with_dead_letter(self):
        def fn(dl):
            dl.add({"row": 1}, "bad row")
            return {"records_in": 10, "records_out": 9}
        r = run_job("t", fn, conn=self.conn, retries=0)
        self.assertEqual(r["status"], "success")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM dead_letter").fetchone()[0], 1)

    def test_failure_recorded_and_alerts(self):
        def fn(dl):
            raise RuntimeError("vendor down")
        r = run_job("t2", fn, conn=self.conn, retries=1, backoff_s=0)
        self.assertEqual(r["status"], "failed")
        row = self.conn.execute("SELECT status, attempts FROM job_runs WHERE job_name='t2'").fetchone()
        self.assertEqual((row[0], row[1]), ("failed", 2))

    def test_too_many_dead_letters_fails_run(self):
        def fn(dl):
            for i in range(5):
                dl.add({"i": i}, "x")
            return {"records_in": 10}
        self.assertEqual(run_job("t3", fn, conn=self.conn, retries=0)["status"], "failed")


class TestPipelineEndToEnd(unittest.TestCase):
    def test_idempotent_rerun(self):
        mod = load_script("skills/account-data-pipeline/scripts/run_pipeline.py")
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "g.db")
            cwd = os.getcwd(); os.chdir(d)
            try:
                for _ in range(2):
                    self.assertEqual(mod.main(["--db", db, "--crm", "dryrun", "--now", "2026-11-25T12:00:00Z"]), 0)
            finally:
                os.chdir(cwd)
            conn = store.connect(db)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0], 7)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0], 6)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 7)
            acme = conn.execute("SELECT employees, owner_email FROM accounts WHERE domain='acme-analytics.com'").fetchone()
            self.assertEqual((acme[0], acme[1]), (320, "alice@yourco.com"))


class TestWebhook(unittest.TestCase):
    def test_signature_and_idempotency(self):
        import hashlib, hmac
        mod = load_script("skills/gtm-api-integrations/scripts/webhook_receiver.py")
        body, ts = b'{"event_id":"e1"}', str(int(time.time()))
        sig = "sha256=" + hmac.new(b"s3cret", f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
        self.assertTrue(mod.verify("s3cret", body, ts, sig))
        self.assertFalse(mod.verify("s3cret", body + b"x", ts, sig))
        self.assertFalse(mod.verify("s3cret", body, str(int(time.time()) - 3600), sig))
        with tempfile.TemporaryDirectory() as d:
            conn = store.connect(os.path.join(d, "w.db"))
            self.assertEqual(mod.handle_event(conn, CFG, "crm", {"event_id": "e1"})["status"], "processed")
            self.assertEqual(mod.handle_event(conn, CFG, "crm", {"event_id": "e1"})["status"], "duplicate")


class TestAgents(unittest.TestCase):
    def test_crm_update_guardrails(self):
        mod = load_script("skills/crm-update-agent/scripts/notes_to_crm.py")
        extracted = {"summary": "s", "contacts": [], "tasks": [], "fields": {
            "next_step": {"value": "send deck", "confidence": 0.95, "evidence": "next step: send deck"},
            "stage": {"value": "negotiation", "confidence": 0.9, "evidence": "talked terms"},
            "amount": {"value": "lots", "confidence": 0.9, "evidence": "big budget"},
            "pain": {"value": "dupes", "confidence": 0.5, "evidence": "dupes everywhere"},
            "metrics": {"value": "x", "confidence": 0.9, "evidence": ""}}}
        p = mod.plan(extracted, {"stage": "discovery"})
        self.assertIn("next_step", p["auto_apply"])
        self.assertIn("stage", p["needs_review"])            # risky field never auto-applied
        self.assertIn("warning", p["needs_review"]["stage"])  # skipped stages flagged
        self.assertIn("pain", p["needs_review"])             # low confidence -> review
        self.assertTrue(any("amount" in e for e in p["validation_errors"]))
        self.assertTrue(any("metrics" in e for e in p["validation_errors"]))  # no evidence -> dropped

    def test_pricing_guardrails(self):
        mod = load_script("skills/proposal-generator/scripts/build_proposal.py")
        pb = json.loads((ROOT / "skills/proposal-generator/pricing.example.json").read_text())
        q = mod.quote(pb, "growth", 60, years=2)
        self.assertEqual(q["list_annual"], 60 * 1400 + 6000)
        self.assertAlmostEqual(q["discount"], 0.15)
        with self.assertRaises(mod.PricingError):
            mod.quote(pb, "growth", 5)
        with self.assertRaises(mod.PricingError):
            mod.quote(pb, "growth", 20, extra_discount=0.3)


if __name__ == "__main__":
    unittest.main()
