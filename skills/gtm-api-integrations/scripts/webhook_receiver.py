#!/usr/bin/env python3
"""Webhook receiver for real-time GTM events (form fills, chat, CRM changes).

Production patterns baked in:
  * HMAC-SHA256 signature verification (constant-time compare) + timestamp
    tolerance to stop replay attacks
  * idempotency: provider event_id stored in webhook_events; duplicates
    return 200 without reprocessing (providers retry aggressively)
  * ack fast: persist first, process second; processing errors are kept on
    the event row for replay instead of returning 500 forever
  * structured JSON logs

    WEBHOOK_SECRET=dev python skills/gtm-api-integrations/scripts/webhook_receiver.py --port 8787
    # then POST /webhooks/form with header X-Signature: sha256=<hex(hmac(secret, ts + "." + body))>, X-Timestamp: <unix>

Stdlib http.server keeps this dependency-free; in production run the same
handler logic behind FastAPI/uvicorn or a serverless function.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import pathlib
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills/inbound-routing/scripts"))

from gtm_core import store  # noqa: E402
from gtm_core.config import load_config  # noqa: E402
from gtm_core.jobs import setup_logging  # noqa: E402

log = logging.getLogger("gtm.webhooks")
TOLERANCE_S = 300


def verify(secret: str, body: bytes, ts: str | None, sig: str | None, now: float | None = None) -> bool:
    if not (secret and ts and sig):
        return False
    try:
        if abs((now or time.time()) - int(ts)) > TOLERANCE_S:
            return False
    except ValueError:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig.removeprefix("sha256="))


def handle_event(conn, cfg, provider: str, event: dict) -> dict:
    """Idempotent processing. Returns {'status': 'processed'|'duplicate', ...}."""
    event_id = str(event.get("event_id") or event.get("id") or hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest())
    conn.execute("INSERT OR IGNORE INTO webhook_events(event_id,provider,payload) VALUES(?,?,?)",
                 (event_id, provider, json.dumps(event)))
    conn.commit()  # persisted before processing => replayable
    row = conn.execute("SELECT processed_at FROM webhook_events WHERE event_id=?", (event_id,)).fetchone()
    if row and row[0]:
        return {"status": "duplicate", "event_id": event_id}
    # stored-but-unprocessed (earlier attempt failed) => process again on provider retry
    result = {"status": "processed", "event_id": event_id}
    if provider == "form":
        from route_leads import route_one  # inbound-routing skill
        lead = event.get("lead", event)
        result["routing"] = route_one(conn, cfg, lead)
    conn.execute("UPDATE webhook_events SET processed_at=CURRENT_TIMESTAMP WHERE event_id=?", (event_id,))
    conn.commit()
    return result


def make_handler(db_path, cfg, secret):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            body = json.dumps(obj, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/healthz":
                return self._send(200, {"ok": True})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self.path.startswith("/webhooks/"):
                return self._send(404, {"error": "not found"})
            provider = self.path.split("/")[2]
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if not verify(secret, body, self.headers.get("X-Timestamp"), self.headers.get("X-Signature")):
                log.warning(json.dumps({"event": "webhook_bad_signature", "provider": provider}))
                return self._send(401, {"error": "bad signature"})
            try:
                event = json.loads(body)
            except json.JSONDecodeError:
                return self._send(400, {"error": "invalid json"})
            conn = store.connect(db_path)  # one connection per request: sqlite objects are thread-bound
            conn.execute("PRAGMA busy_timeout=5000")
            try:
                res = handle_event(conn, cfg, provider, event)
            except Exception as e:  # keep event for replay, don't make the provider retry forever
                log.error(json.dumps({"event": "webhook_processing_failed", "provider": provider, "error": str(e)}))
                return self._send(202, {"status": "accepted_with_error"})
            finally:
                conn.close()
            log.info(json.dumps({"event": "webhook_ok", "provider": provider, **{k: res[k] for k in ("status", "event_id")}}))
            self._send(200, res)

        def log_message(self, *a):  # silence default access log; we log JSON
            pass
    return H


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--db", default=str(ROOT / "out/gtm.db"))
    a = ap.parse_args(argv)
    setup_logging()
    secret = os.environ.get("WEBHOOK_SECRET")
    if not secret:
        sys.exit("Set WEBHOOK_SECRET")
    store.connect(a.db).close()  # apply schema once
    ThreadingHTTPServer(("0.0.0.0", a.port), make_handler(a.db, load_config(), secret)).serve_forever()


if __name__ == "__main__":
    main()
