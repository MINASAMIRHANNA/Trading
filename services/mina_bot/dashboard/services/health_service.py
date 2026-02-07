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

    role = ""
    try:
        role = str(db.get_setting("BOT_ROLE") or os.getenv("BOT_ROLE") or "").strip().lower()
    except Exception:
        role = str(os.getenv("BOT_ROLE") or "").strip().lower()
    if role == "arena":
        role = "paper"

    last_beat = db.get_setting("last_heartbeat") or db.get_setting("bot_heartbeat")
    is_online = False
    last_seen_seconds = 999999

    def _iso_to_ms(val: Any) -> int:
        try:
            t = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            return int(t.astimezone(timezone.utc).timestamp() * 1000)
        except Exception:
            return 0

    now_ms = int(time.time() * 1000)
    settings_hb_ms = _iso_to_ms(last_beat) if last_beat else 0
    pump_hb_ms = 0
    try:
        if hasattr(db, "get_pump_hunter_state"):
            st = db.get_pump_hunter_state() or {}
            pump_hb_ms = int(st.get("last_heartbeat_ms") or 0)
    except Exception:
        pump_hb_ms = 0

    if role == "pump":
        hb_ms = max(settings_hb_ms, pump_hb_ms)
        if hb_ms > 0:
            last_seen_seconds = int((now_ms - hb_ms) / 1000)
            if last_seen_seconds < 60:
                is_online = True
    else:
        if settings_hb_ms > 0:
            last_seen_seconds = int((now_ms - settings_hb_ms) / 1000)
            if last_seen_seconds < 60:
                is_online = True
        elif pump_hb_ms > 0:
            last_seen_seconds = int((now_ms - pump_hb_ms) / 1000)
            if last_seen_seconds < 60:
                is_online = True

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

    # If bot heartbeat is missing but execution_monitor is alive, treat the role as online.
    if not is_online and execmon_last_seen_seconds < 60:
        is_online = True
        if last_seen_seconds == 999999 or execmon_last_seen_seconds < last_seen_seconds:
            last_seen_seconds = execmon_last_seen_seconds

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
