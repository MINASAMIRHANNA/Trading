from __future__ import annotations

import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def env(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v else default


BRAIN_API_URL = env("BRAIN_API_URL", "http://brain_api:8100").rstrip("/")
ROLES = [r.strip() for r in env("ROLES", "paper,live,pump").split(",") if r.strip()]
INTERVAL_SEC = int(env("INTERVAL_SEC", "60"))
STARTUP_SLEEP_SEC = int(env("STARTUP_SLEEP_SEC", "5"))


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    print(f"[brain_sync_worker] {ts} {msg}", flush=True)


def http_post(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return resp.status, body


def main() -> int:
    log(f"starting: BRAIN_API_URL={BRAIN_API_URL} ROLES={ROLES} INTERVAL_SEC={INTERVAL_SEC}")
    if STARTUP_SLEEP_SEC > 0:
        time.sleep(STARTUP_SLEEP_SEC)

    while True:
        for role in ROLES:
            url = f"{BRAIN_API_URL}/api/sync/run?role={urllib.parse.quote(role)}"
            try:
                code, body = http_post(url)
                log(f"sync role={role} status={code} body={body[:200]}")
            except Exception as e:
                log(f"sync role={role} ERROR={type(e).__name__}: {e}")
        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    raise SystemExit(main())
