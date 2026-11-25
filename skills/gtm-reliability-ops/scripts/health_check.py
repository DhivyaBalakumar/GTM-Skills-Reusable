#!/usr/bin/env python3
"""GTM system health check — run every 15-30 min from cron/Actions.

Checks:
  * freshness: each job's last success is within its SLA
  * failure rate: recent failed runs per job
  * dead-letter backlog: unreplayed records piling up
  * routing SLA: tier-A leads past SLA with no first touch
  * data quality: accounts missing owner / domain-less, contacts without accounts
Alerts to Slack ($SLACK_ALERT_WEBHOOK_URL) or stderr; exit code 1 if anything is red,
so CI/cron monitors can page on it.

    python skills/gtm-reliability-ops/scripts/health_check.py --db out/gtm.db
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from gtm_core import store  # noqa: E402
from gtm_core.jobs import alert, check_freshness  # noqa: E402

DEFAULT_SLAS = {"account_pipeline": 26}  # job -> max hours since last success


def run(conn, slas: dict, dl_max: int = 50) -> dict:
    report = {"stale_jobs": check_freshness(conn, slas)}
    report["recent_failures"] = [dict(r) for r in conn.execute(
        """SELECT job_name, COUNT(*) failures FROM job_runs
           WHERE status='failed' AND started_at >= datetime('now','-1 day') GROUP BY job_name""")]
    report["dead_letter_backlog"] = conn.execute("SELECT COUNT(*) FROM dead_letter WHERE replayed_at IS NULL").fetchone()[0]
    now = datetime.now(timezone.utc).isoformat()
    report["sla_breaches"] = [dict(r) for r in conn.execute(
        """SELECT lead_id, assigned_to, tier, sla_due_at FROM routing_assignments
           WHERE first_touch_at IS NULL AND sla_due_at IS NOT NULL AND sla_due_at < ? AND tier IN ('A','B')""", (now,))]
    report["data_quality"] = {
        "accounts_without_owner": conn.execute("SELECT COUNT(*) FROM accounts WHERE owner_email IS NULL").fetchone()[0],
        "contacts_without_account": conn.execute("SELECT COUNT(*) FROM contacts WHERE account_id IS NULL").fetchone()[0],
        "accounts_never_scored": conn.execute(
            "SELECT COUNT(*) FROM accounts a WHERE NOT EXISTS (SELECT 1 FROM account_scores s WHERE s.account_id=a.account_id)").fetchone()[0],
    }
    problems = []  # stale jobs are alerted inside check_freshness already
    if report["recent_failures"]:
        problems.append(f"failed runs in last 24h: {report['recent_failures']}")
    if report["dead_letter_backlog"] > dl_max:
        problems.append(f"dead-letter backlog {report['dead_letter_backlog']} (> {dl_max})")
    if report["sla_breaches"]:
        problems.append(f"{len(report['sla_breaches'])} inbound lead(s) past SLA, untouched")
    for p in problems:
        alert(f":warning: GTM health: {p}")
    report["status"] = "red" if (problems or report["stale_jobs"]) else "green"
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(ROOT / "out/gtm.db"))
    ap.add_argument("--slas", default=json.dumps(DEFAULT_SLAS), help='JSON {"job": max_hours}')
    a = ap.parse_args(argv)
    rep = run(store.connect(a.db), json.loads(a.slas))
    print(json.dumps(rep, indent=2))
    return 1 if rep["status"] == "red" else 0


if __name__ == "__main__":
    sys.exit(main())
