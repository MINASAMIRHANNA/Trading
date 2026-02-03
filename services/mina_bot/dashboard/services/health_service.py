from __future__ import annotations

import os
from datetime import datetime, timezone
import time
from typing import Any, Callable, Dict, Optional


def build_system_health_payload(
    *,
    db: Any,
    project_root: str,
    execmon_age_seconds_fn: Optional[Callable[[], int]] = None,
) -> Dict[str, Any]:
    """Build the /api/system_health response payload."""

    last_beat = db.get_setting("last_heartbeat") or db.get_setting("bot_heartbeat")
    is_online = False
    last_seen_seconds = 999999

    if last_beat:
        try:
            last_time = datetime.fromisoformat(str(last_beat).replace("Z", "+00:00"))
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            diff = now - last_time.astimezone(timezone.utc)
            last_seen_seconds = diff.total_seconds()
            if last_seen_seconds < 60:
                is_online = True
        except Exception:
            pass
    else:
        # Pump Hunter fallback (heartbeat stored in pump_hunter_state)
        try:
            if hasattr(db, "get_pump_hunter_state"):
                st = db.get_pump_hunter_state() or {}
                hb_ms = int(st.get("last_heartbeat_ms") or 0)
                if hb_ms > 0:
                    last_seen_seconds = int((time.time() * 1000 - hb_ms) / 1000)
                    if last_seen_seconds < 60:
                        is_online = True
        except Exception:
            pass

    db_path = getattr(db, "db_file", None) or os.path.join(project_root, "bot_data.db")
    db_size_mb = 0.0
    try:
        # Postgres: approximate schema size
        if getattr(db, "is_postgres", False):
            schema = getattr(db, "pg_schema", None) or os.getenv("MINA_PG_SCHEMA") or os.getenv("TRADING_PG_SCHEMA")
            if schema:
                cur = db.conn.cursor()
                cur.execute(
                    """
                    SELECT COALESCE(
                        SUM(pg_total_relation_size(quote_ident(schemaname)||'.'||quote_ident(tablename))),
                        0
                    )
                    FROM pg_tables
                    WHERE schemaname = ?
                    """,
                    (schema,),
                )
                row = cur.fetchone()
                bytes_sz = int(row[0]) if row else 0
                db_size_mb = bytes_sz / (1024 * 1024)
        else:
            if os.path.exists(db_path):
                db_size_mb = os.path.getsize(db_path) / (1024 * 1024)
    except Exception:
        pass

    # Batch-11: expose DB schema/meta versions (best-effort)
    schema_version = None
    ddl_version = None
    try:
        conn2 = getattr(db, "conn", None)
        if conn2 is not None:
            from mina_core.db.ddl import get_schema_meta

            schema_version = get_schema_meta(conn2, "mina_schema_version", lock=getattr(db, "lock", None))
            ddl_version = get_schema_meta(conn2, "mina_ddl_version", lock=getattr(db, "lock", None))
    except Exception:
        pass

    execmon_last_seen_seconds = 999999
    if execmon_age_seconds_fn is not None:
        try:
            execmon_last_seen_seconds = int(execmon_age_seconds_fn() or 0)
        except Exception:
            execmon_last_seen_seconds = 999999

    return {
        "backend": ("postgres" if getattr(db, "is_postgres", False) else "sqlite"),
        "pg_schema": getattr(db, "pg_schema", None),
        "online": is_online,
        "last_seen_seconds": int(last_seen_seconds),
        "latency": int(float(db.get_setting("api_latency") or 0)),
        "schema_version": schema_version,
        "ddl_version": ddl_version,
        "cpu": float(db.get_setting("sys_cpu") or 0),
        "ram": float(db.get_setting("sys_ram") or 0),
        "db_size": f"{db_size_mb:.2f} MB",
        "error_count": len(db.get_logs(limit=50)),
        "kill_switch": str(db.get_setting("kill_switch") or "0"),
        "kill_switch_reason": str(db.get_setting("kill_switch_reason") or ""),
        "execmon_last_seen_seconds": execmon_last_seen_seconds,
    }
