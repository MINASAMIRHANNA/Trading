"""Brain sync worker.

This worker periodically pulls trades from Mina schemas (mina_paper/mina_live/mina_pump)
and generates Brain features in the brain schema.

It is intentionally defensive:
  - waits for Postgres availability
  - never crashes the container on one bad role/symbol
  - logs concise summaries per cycle

Environment variables:
  - BRAIN_DB_DSN: target DB DSN (brain schema)
  - BRAIN_SCHEMA: target schema (default: brain)
  - BRAIN_SOURCE_DSN / MINA_TRADING_PG_DSN / TRADING_PG_DSN: source DSN
  - BRAIN_SYNC_ROLES: comma-separated roles (default: paper,live,pump)
  - BRAIN_SYNC_LIMIT: per-role trade fetch limit (default: 500)
  - BRAIN_SYNC_INTERVAL_SEC: sleep between cycles (default: 60)
  - BRAIN_SYNC_DRY_RUN: 1/0 (default: 0)
"""

from __future__ import annotations

import os
import signal
import sys
import time
from datetime import datetime, timezone

from database.base import Base
from database.engine import ensure_schema, get_db_schema, get_engine
from database.migrations import ensure_trade_features_columns
from database.service_registry import register_service
from database.session import SessionLocal
from ingestion.mina.sync_trades import sync_mina_trades


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Stop:
    value = False


def _handle_stop(signum, frame):  # noqa: ARG001
    _Stop.value = True


def _parse_roles(val: str) -> list[str]:
    roles = [r.strip() for r in val.split(",") if r.strip()]
    # keep stable ordering
    seen = set()
    out: list[str] = []
    for r in roles:
        if r not in seen:
            out.append(r)
            seen.add(r)
    return out or ["paper", "live", "pump"]


def _as_int(env_name: str, default: int) -> int:
    raw = os.getenv(env_name)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _as_bool(env_name: str, default: bool = False) -> bool:
    raw = os.getenv(env_name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _bootstrap_db() -> None:
    """Ensure schema + tables exist before worker cycles start."""
    engine = get_engine(echo=False)
    schema = get_db_schema()
    ensure_schema(engine, schema)
    Base.metadata.create_all(engine)
    ensure_trade_features_columns(engine, schema)


def main() -> int:
    # graceful shutdown
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    roles = _parse_roles(os.getenv("BRAIN_SYNC_ROLES", "paper,live,pump"))
    limit = _as_int("BRAIN_SYNC_LIMIT", 500)
    interval = _as_int("BRAIN_SYNC_INTERVAL_SEC", 60)
    dry_run = _as_bool("BRAIN_SYNC_DRY_RUN", False)

    print(f"🧠 [brain_sync_worker] starting @ {_utc()} roles={roles} limit={limit} interval={interval}s dry_run={dry_run}")

    # Ensure schema + tables exist (will retry if DB not ready yet)
    while not _Stop.value:
        try:
            _bootstrap_db()
            try:
                register_service(
                    "brain_sync_worker",
                    schema_name=get_db_schema(),
                    meta={"component": "worker"},
                )
            except Exception:
                pass
            break
        except Exception as e:
            print(f"🧠 [brain_sync_worker] waiting for DB... err={type(e).__name__}: {e}")
            time.sleep(3)

    # Main loop
    while not _Stop.value:
        cycle_started = time.time()
        ok_roles = 0
        fail_roles = 0

        for role in roles:
            if _Stop.value:
                break
            try:
                with SessionLocal() as db:
                    out = sync_mina_trades(db, role=role, symbol=None, limit=limit, dry_run=dry_run)
                ok_roles += 1
                summary = {
                    "role": role,
                    "ok": bool(out.get("ok")),
                    "fetched": out.get("fetched"),
                    "inserted": out.get("inserted"),
                    "skipped": out.get("skipped"),
                    "errors": out.get("errors"),
                }
                print(f"🧠 [brain_sync_worker] {_utc()} sync {summary}")
            except Exception as e:
                fail_roles += 1
                print(f"🧠 [brain_sync_worker] {_utc()} sync role={role} FAILED {type(e).__name__}: {e}")

        elapsed = max(0.0, time.time() - cycle_started)
        print(f"🧠 [brain_sync_worker] cycle done ok_roles={ok_roles} fail_roles={fail_roles} elapsed={elapsed:.2f}s")

        # sleep (interruptible)
        if interval <= 0:
            interval = 60
        for _ in range(interval):
            if _Stop.value:
                break
            time.sleep(1)

    print(f"🧠 [brain_sync_worker] stopping @ {_utc()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
