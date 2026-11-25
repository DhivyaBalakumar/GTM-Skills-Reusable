"""Run scheduled GTM jobs reliably.

Wrap any pipeline step with `run_job(...)` (or the @job decorator) to get:
  * a lock so two cron fires never run the same job concurrently
  * retries with backoff for transient failures
  * a job_runs row per run (status, counts, error) => monitoring & SLAs
  * per-record failures go to a dead-letter table instead of killing the run
  * an alert (Slack webhook or stderr) when a run fails or a job goes stale
  * JSON logs to stdout for any log shipper
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

log = logging.getLogger("gtm.jobs")


def setup_logging(level: str = "INFO") -> None:
    class JsonFmt(logging.Formatter):
        def format(self, r):
            base = {"ts": datetime.now(timezone.utc).isoformat(), "level": r.levelname, "logger": r.name}
            msg = r.getMessage()
            try:
                base.update(json.loads(msg))
            except (ValueError, TypeError):
                base["msg"] = msg
            return json.dumps(base)

    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFmt())
    logging.basicConfig(level=level, handlers=[h], force=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def file_lock(name: str, lock_dir: str = ".locks", stale_after_s: int = 3600):
    Path(lock_dir).mkdir(exist_ok=True)
    p = Path(lock_dir) / f"{name}.lock"
    if p.exists() and time.time() - p.stat().st_mtime < stale_after_s:
        raise JobLocked(name)
    p.write_text(str(os.getpid()))
    try:
        yield
    finally:
        p.unlink(missing_ok=True)


class JobLocked(Exception):
    pass


class DeadLetter:
    """Collect per-record failures; the run continues."""

    def __init__(self, conn, job_name: str):
        self.conn, self.job_name, self.count = conn, job_name, 0

    def add(self, payload: dict, error: Exception | str) -> None:
        self.count += 1
        if self.conn is not None:
            self.conn.execute("INSERT INTO dead_letter(job_name,payload,error) VALUES(?,?,?)",
                              (self.job_name, json.dumps(payload, default=str), str(error)))
        log.warning(json.dumps({"event": "dead_letter", "job": self.job_name, "error": str(error)}))


def alert(text: str) -> None:
    """Send an alert to Slack if SLACK_ALERT_WEBHOOK_URL is set, else stderr."""
    url = os.environ.get("SLACK_ALERT_WEBHOOK_URL")
    if not url:
        print(f"[ALERT] {text}", file=sys.stderr)
        return
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps({"text": text}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:  # alerting must never crash the job
        print(f"[ALERT-FAILED] {e}: {text}", file=sys.stderr)


def run_job(name: str, fn: Callable[[DeadLetter], dict | None], conn=None,
            retries: int = 2, backoff_s: float = 5.0, dead_letter_fail_ratio: float = 0.2) -> dict:
    """Execute `fn(dead_letter)`; fn may return {'records_in': n, 'records_out': m}."""
    run_id = str(uuid.uuid4())
    started = now_iso()
    if conn is not None:
        conn.execute("INSERT INTO job_runs(run_id,job_name,status,started_at) VALUES(?,?, 'running', ?)",
                     (run_id, name, started))
        conn.commit()
    try:
        with file_lock(name):
            attempt, last_err = 0, None
            while attempt <= retries:
                attempt += 1
                dl = DeadLetter(conn, name)
                try:
                    stats = fn(dl) or {}
                    rin = stats.get("records_in")
                    if rin and dl.count / rin > dead_letter_fail_ratio:
                        raise RuntimeError(f"{dl.count}/{rin} records dead-lettered (> {dead_letter_fail_ratio:.0%})")
                    _finish(conn, run_id, "success", attempt, stats)
                    log.info(json.dumps({"event": "job_success", "job": name, "run_id": run_id,
                                         "attempt": attempt, **stats, "dead_lettered": dl.count}))
                    return {"status": "success", "run_id": run_id, **stats, "dead_lettered": dl.count}
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    log.error(json.dumps({"event": "job_attempt_failed", "job": name, "attempt": attempt,
                                          "error": str(e)}))
                    if conn is not None:
                        conn.rollback()
                    if attempt <= retries:
                        time.sleep(backoff_s * 2 ** (attempt - 1))
            tb = "".join(traceback.format_exception(last_err))[-2000:]
            _finish(conn, run_id, "failed", attempt, {}, tb)
            alert(f":rotating_light: GTM job `{name}` failed after {attempt} attempts (run {run_id}): {last_err}")
            return {"status": "failed", "run_id": run_id, "error": str(last_err)}
    except JobLocked:
        _finish(conn, run_id, "skipped", 0, {}, "previous run still holds lock")
        log.warning(json.dumps({"event": "job_skipped_locked", "job": name}))
        return {"status": "skipped", "run_id": run_id}


def _finish(conn, run_id, status, attempts, stats, error=None):
    if conn is None:
        return
    conn.execute(
        "UPDATE job_runs SET status=?, finished_at=?, attempts=?, records_in=?, records_out=?, error=? WHERE run_id=?",
        (status, now_iso(), attempts, stats.get("records_in"), stats.get("records_out"), error, run_id),
    )
    conn.commit()


def check_freshness(conn, expectations: dict[str, int]) -> list[str]:
    """expectations: {job_name: max_hours_since_last_success}. Returns problems & alerts on them."""
    problems = []
    for job, max_h in expectations.items():
        row = conn.execute("SELECT MAX(finished_at) FROM job_runs WHERE job_name=? AND status='success'",
                           (job,)).fetchone()
        last = row[0] if row else None
        if not last:
            problems.append(f"{job}: never succeeded")
        elif datetime.fromisoformat(last) < datetime.now(timezone.utc) - timedelta(hours=max_h):
            problems.append(f"{job}: last success {last} (> {max_h}h ago)")
    for p in problems:
        alert(f":warning: Stale GTM job — {p}")
    return problems
