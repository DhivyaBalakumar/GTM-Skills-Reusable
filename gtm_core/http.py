"""Production HTTP client for GTM APIs (CRM, enrichment, Slack, email tools).

Handles what one-off scripts don't:
  * retries with exponential backoff + full jitter on 429/5xx/network errors
  * honours Retry-After headers
  * client-side token-bucket rate limiting (stay under vendor limits)
  * idempotency keys on writes so a retry never double-creates
  * structured logs for every attempt
Stdlib only, so it runs anywhere (cron box, Lambda, GitHub Actions).
"""
from __future__ import annotations

import json
import logging
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field

log = logging.getLogger("gtm.http")
RETRYABLE = {408, 425, 429, 500, 502, 503, 504}


class HTTPError(Exception):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} for {url}: {body[:300]}")
        self.status, self.body, self.url = status, body, url


class TokenBucket:
    """Allow `rate` requests per second with bursts up to `capacity`."""

    def __init__(self, rate: float, capacity: int | None = None):
        self.rate, self.capacity = rate, capacity or max(1, int(rate))
        self.tokens, self.updated = float(self.capacity), time.monotonic()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            time.sleep(wait)


@dataclass
class Client:
    base_url: str
    headers: dict = field(default_factory=dict)
    rate_per_sec: float = 5.0
    max_retries: int = 5
    timeout: float = 30.0
    backoff_base: float = 0.5
    backoff_cap: float = 30.0
    _bucket: TokenBucket = field(init=False, repr=False)
    _opener: object = field(default=None, repr=False)  # injectable for tests

    def __post_init__(self):
        self._bucket = TokenBucket(self.rate_per_sec)

    def request(self, method: str, path: str, body: dict | None = None,
                params: dict | None = None, idempotency_key: str | None = None) -> dict:
        url = self.base_url.rstrip("/") + "/" + path.lstrip("/")
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"Content-Type": "application/json", "Accept": "application/json", **self.headers}
        if method.upper() in {"POST", "PUT", "PATCH"}:
            headers["Idempotency-Key"] = idempotency_key or str(uuid.uuid4())
        data = json.dumps(body).encode() if body is not None else None

        for attempt in range(1, self.max_retries + 2):
            self._bucket.acquire()
            t0 = time.monotonic()
            try:
                req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
                opener = self._opener or urllib.request.urlopen
                with opener(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode() or "{}"
                    log.info(json.dumps({"event": "http_ok", "method": method, "url": url, "status": resp.status,
                                         "attempt": attempt, "ms": int((time.monotonic() - t0) * 1000)}))
                    return json.loads(raw)
            except urllib.error.HTTPError as e:
                body_txt = e.read().decode(errors="replace") if hasattr(e, "read") else ""
                retry_after = e.headers.get("Retry-After") if e.headers else None
                if e.code not in RETRYABLE or attempt > self.max_retries:
                    log.error(json.dumps({"event": "http_fail", "url": url, "status": e.code, "attempt": attempt}))
                    raise HTTPError(e.code, body_txt, url) from None
                delay = self._delay(attempt, retry_after)
                log.warning(json.dumps({"event": "http_retry", "url": url, "status": e.code,
                                        "attempt": attempt, "sleep_s": round(delay, 2)}))
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt > self.max_retries:
                    raise
                delay = self._delay(attempt, None)
                log.warning(json.dumps({"event": "http_retry", "url": url, "error": str(e),
                                        "attempt": attempt, "sleep_s": round(delay, 2)}))
            time.sleep(delay)
        raise RuntimeError("unreachable")

    def _delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), self.backoff_cap)
            except ValueError:
                pass
        return random.uniform(0, min(self.backoff_cap, self.backoff_base * 2 ** (attempt - 1)))

    def get(self, path, **kw): return self.request("GET", path, **kw)
    def post(self, path, body=None, **kw): return self.request("POST", path, body=body, **kw)
    def patch(self, path, body=None, **kw): return self.request("PATCH", path, body=body, **kw)


def paginate(client: Client, path: str, params: dict | None = None,
             results_key: str = "results", cursor_path: tuple = ("paging", "next", "after"),
             cursor_param: str = "after"):
    """Generic cursor pagination (HubSpot-style by default). Yields records."""
    params = dict(params or {})
    while True:
        page = client.get(path, params=params)
        yield from page.get(results_key, [])
        cur = page
        for k in cursor_path:
            cur = cur.get(k) if isinstance(cur, dict) else None
        if not cur:
            return
        params[cursor_param] = cur

