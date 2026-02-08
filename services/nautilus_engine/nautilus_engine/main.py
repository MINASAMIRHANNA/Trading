from __future__ import annotations

import datetime as dt
import json
import os
import random
import re
import time
import uuid
from typing import Any, Dict, Mapping

import psycopg
from psycopg.rows import dict_row


DEFAULT_DSN = "postgresql://trading:trading@postgres:5432/trading"
ROLE_TO_SCHEMA = {
    "paper": "mina_paper",
    "live": "mina_live",
    "pump": "mina_pump",
}

OPENING_COMMANDS = {
    "EXECUTE_SIGNAL",
    "OPEN_TRADE",
    "OPEN_POSITION",
    "MANUAL_EXECUTE",
    "MANUAL_OPEN",
}
CLOSING_COMMANDS = {
    "CLOSE_ALL_POSITIONS",
    "CLOSE_ALL",
    "CLOSE_TRADE",
    "CLOSE_POSITION",
    "REDUCE_POSITION",
}
SAFE_LIVE_MODES = {"TEST", "TESTNET", "SIM", "PAPER", "SANDBOX", "SIM_OR_TESTNET"}
SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RETRYABLE_ERROR_TOKENS = (
    "timeout",
    "timed out",
    "temporar",
    "connection",
    "reset by peer",
    "deadlock",
    "could not serialize",
    "too many connections",
)


def _env(name: str, default: str = "") -> str:
    val = os.getenv(name)
    if val is None or str(val).strip() == "":
        return default
    return str(val)


def _normalize_dsn(raw: str) -> str:
    txt = str(raw or "").strip()
    if txt.startswith("postgres://"):
        txt = "postgresql://" + txt[len("postgres://") :]
    if txt.startswith("postgresql+psycopg://"):
        txt = "postgresql://" + txt[len("postgresql+psycopg://") :]
    if txt.startswith("postgresql+psycopg2://"):
        txt = "postgresql://" + txt[len("postgresql+psycopg2://") :]
    return txt


def _validate_schema_name(schema: str) -> str:
    out = str(schema or "").strip()
    if not SCHEMA_RE.fullmatch(out):
        raise ValueError(f"invalid schema name: {schema!r}")
    return out


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now_ms() -> int:
    return int(time.time() * 1000)


def truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def safe_json_loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    txt = str(value).strip()
    if not txt:
        return default
    try:
        return json.loads(txt)
    except Exception:
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def role_to_schema(role: str) -> str:
    key = str(role or "").strip().lower()
    if key not in ROLE_TO_SCHEMA:
        raise ValueError(f"unknown role: {role!r}")
    return ROLE_TO_SCHEMA[key]


def resolve_role_schemas() -> list[tuple[str, str]]:
    # Preferred Phase C inputs.
    role_raw = _env("ROLE", _env("NAUTILUS_ROLE", "")).strip().lower()
    schema_raw = _env("DB_SCHEMA", "").strip()

    if role_raw:
        if role_raw not in ROLE_TO_SCHEMA:
            raise ValueError(f"ROLE must be one of: {', '.join(sorted(ROLE_TO_SCHEMA))}")
        schema = _validate_schema_name(schema_raw) if schema_raw else role_to_schema(role_raw)
        return [(role_raw, schema)]

    # Backward-compatible fallback.
    raw_roles = [x.strip().lower() for x in _env("NAUTILUS_ROLES", "paper").split(",") if x.strip()]
    roles = [r for r in raw_roles if r in ROLE_TO_SCHEMA]
    if not roles:
        roles = ["paper"]

    if schema_raw:
        schema = _validate_schema_name(schema_raw)
        if len(roles) != 1:
            raise ValueError("DB_SCHEMA override requires exactly one role")
        return [(roles[0], schema)]

    return [(r, role_to_schema(r)) for r in roles]


def connect() -> psycopg.Connection:
    dsn = _normalize_dsn(_env("TRADING_PG_DSN", DEFAULT_DSN))
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)


def table_exists(conn: psycopg.Connection, schema: str, table: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
            LIMIT 1
            """,
            (schema, table),
        )
        return cur.fetchone() is not None


def table_columns(conn: psycopg.Connection, schema: str, table: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            """,
            (schema, table),
        )
        return {str(r.get("column_name") or "") for r in (cur.fetchall() or []) if r and r.get("column_name")}


def ensure_schema_tables(conn: psycopg.Connection, schema: str) -> None:
    with conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.trades (
                id BIGSERIAL PRIMARY KEY,
                symbol TEXT,
                signal TEXT,
                status TEXT,
                entry_price DOUBLE PRECISION,
                quantity DOUBLE PRECISION,
                close_price DOUBLE PRECISION,
                close_reason TEXT,
                pnl DOUBLE PRECISION,
                timestamp TEXT,
                timestamp_ms BIGINT,
                closed_at TEXT,
                closed_at_ms BIGINT,
                source TEXT
            )
            """
        )
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.logs (
                id BIGSERIAL PRIMARY KEY,
                level TEXT,
                msg TEXT,
                created_at TEXT,
                created_at_ms BIGINT,
                source TEXT
            )
            """
        )
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.events (
                id BIGSERIAL PRIMARY KEY,
                event_type TEXT,
                payload_json JSONB,
                source TEXT,
                created_at TEXT,
                created_at_ms BIGINT,
                trace_id TEXT,
                decision_id TEXT,
                schema_version TEXT,
                bot_role TEXT
            )
            """
        )
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.trade_events (
                id BIGSERIAL PRIMARY KEY,
                event_type TEXT,
                payload_json JSONB,
                source TEXT,
                created_at TEXT,
                created_at_ms BIGINT,
                trace_id TEXT,
                decision_id TEXT,
                schema_version TEXT
            )
            """
        )


def ensure_consumer_schema(conn: psycopg.Connection, schema: str) -> None:
    if not table_exists(conn, schema, "commands"):
        return

    with conn.cursor() as cur:
        cur.execute(f"ALTER TABLE {schema}.commands ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0")
        cur.execute(f"ALTER TABLE {schema}.commands ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 5")
        cur.execute(f"ALTER TABLE {schema}.commands ADD COLUMN IF NOT EXISTS next_retry_at_ms BIGINT NULL")
        cur.execute(f"ALTER TABLE {schema}.commands ADD COLUMN IF NOT EXISTS last_error TEXT NULL")
        cur.execute(f"ALTER TABLE {schema}.commands ADD COLUMN IF NOT EXISTS last_error_at_ms BIGINT NULL")
        cur.execute(f"ALTER TABLE {schema}.commands ADD COLUMN IF NOT EXISTS dead_lettered BOOLEAN NOT NULL DEFAULT FALSE")

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.command_dead_letters (
                id BIGSERIAL PRIMARY KEY,
                command_id BIGINT NOT NULL,
                cmd TEXT,
                params JSONB,
                status TEXT,
                attempt_count INT,
                max_attempts INT,
                claimed_by TEXT,
                created_at_ms BIGINT,
                failed_at_ms BIGINT,
                last_error TEXT,
                inserted_at_ms BIGINT NOT NULL
            )
            """
        )

        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS commands_status_next_retry_idx
            ON {schema}.commands(status, next_retry_at_ms)
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS command_dead_letters_command_id_idx
            ON {schema}.command_dead_letters(command_id)
            """
        )


def fetch_setting(conn: psycopg.Connection, schema: str, key: str, default: str = "") -> str:
    if not table_exists(conn, schema, "settings"):
        return default
    cols = table_columns(conn, schema, "settings")
    if "key" not in cols or "value" not in cols:
        return default
    with conn.cursor() as cur:
        cur.execute(f"SELECT value FROM {schema}.settings WHERE key = %s LIMIT 1", (str(key),))
        row = cur.fetchone() or {}
    val = row.get("value")
    return default if val is None else str(val)


def set_setting(conn: psycopg.Connection, schema: str, key: str, value: Any, source: str = "nautilus_engine") -> None:
    if not table_exists(conn, schema, "settings"):
        return
    cols = table_columns(conn, schema, "settings")
    if "key" not in cols or "value" not in cols:
        return

    fields = ["key", "value"]
    vals: list[Any] = [str(key), "" if value is None else str(value)]
    updates = ["value = EXCLUDED.value"]

    if "updated_at" in cols:
        fields.append("updated_at")
        vals.append(now_iso())
        updates.append("updated_at = EXCLUDED.updated_at")
    if "source" in cols:
        fields.append("source")
        vals.append(str(source))
        updates.append("source = EXCLUDED.source")
    if "version" in cols:
        updates.append(f"version = COALESCE({schema}.settings.version, 0) + 1")

    placeholders = ",".join(["%s"] * len(fields))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {schema}.settings ({', '.join(fields)})
            VALUES ({placeholders})
            ON CONFLICT (key) DO UPDATE SET {', '.join(updates)}
            """,
            tuple(vals),
        )


def insert_log(conn: psycopg.Connection, schema: str, level: str, msg: str, source: str = "nautilus_engine") -> None:
    if not table_exists(conn, schema, "logs"):
        return
    cols = table_columns(conn, schema, "logs")
    fields: list[str] = []
    vals: list[Any] = []

    def add(col: str, val: Any) -> None:
        if col in cols:
            fields.append(col)
            vals.append(val)

    add("level", str(level or "INFO"))
    add("msg", str(msg or ""))
    add("message", str(msg or ""))
    add("created_at", now_iso())
    add("created_at_ms", now_ms())
    add("timestamp", now_iso())
    add("timestamp_ms", now_ms())
    add("source", str(source or "nautilus_engine"))

    if not fields:
        return

    placeholders = ",".join(["%s"] * len(fields))
    with conn.cursor() as cur:
        cur.execute(f"INSERT INTO {schema}.logs ({', '.join(fields)}) VALUES ({placeholders})", tuple(vals))


def _append_event_like(
    conn: psycopg.Connection,
    schema: str,
    *,
    table: str,
    role: str,
    event_type: str,
    payload: Mapping[str, Any],
    trace_id: str,
    decision_id: str,
    schema_version: str,
) -> None:
    if not table_exists(conn, schema, table):
        return
    cols = table_columns(conn, schema, table)

    event_payload = {
        "schema_version": schema_version,
        "trace_id": trace_id,
        "decision_id": decision_id,
        **dict(payload or {}),
    }

    fields: list[str] = []
    vals: list[Any] = []

    def add(col: str, val: Any) -> None:
        if col in cols:
            fields.append(col)
            vals.append(val)

    add("event_type", event_type)
    add("type", event_type)
    add("payload_json", json.dumps(event_payload, ensure_ascii=True, default=str))
    add("payload", json.dumps(event_payload, ensure_ascii=True, default=str))
    add("data", json.dumps(event_payload, ensure_ascii=True, default=str))
    add("source", "nautilus_engine")
    add("created_at", now_iso())
    add("created_at_ms", now_ms())
    add("timestamp", now_iso())
    add("timestamp_ms", now_ms())
    add("trace_id", trace_id)
    add("decision_id", decision_id)
    add("schema_version", schema_version)
    add("bot_role", role)

    if not fields:
        return

    placeholders = ",".join(["%s"] * len(fields))
    with conn.cursor() as cur:
        cur.execute(f"INSERT INTO {schema}.{table} ({', '.join(fields)}) VALUES ({placeholders})", tuple(vals))


def append_event(
    conn: psycopg.Connection,
    schema: str,
    *,
    role: str,
    event_type: str,
    payload: Mapping[str, Any],
    trace_id: str,
    decision_id: str,
    schema_version: str,
) -> None:
    _append_event_like(
        conn,
        schema,
        table="events",
        role=role,
        event_type=event_type,
        payload=payload,
        trace_id=trace_id,
        decision_id=decision_id,
        schema_version=schema_version,
    )


def append_trade_event(
    conn: psycopg.Connection,
    schema: str,
    *,
    role: str,
    event_type: str,
    payload: Mapping[str, Any],
    trace_id: str,
    decision_id: str,
    schema_version: str,
) -> None:
    _append_event_like(
        conn,
        schema,
        table="trade_events",
        role=role,
        event_type=event_type,
        payload=payload,
        trace_id=trace_id,
        decision_id=decision_id,
        schema_version=schema_version,
    )


def claim_next_pending_command(conn: psycopg.Connection, schema: str, worker_id: str) -> dict | None:
    if not table_exists(conn, schema, "commands"):
        return None
    cols = table_columns(conn, schema, "commands")
    required = {"id", "cmd", "status"}
    if not required.issubset(cols):
        return None

    set_parts: list[str] = ["status = %s"]
    set_vals: list[Any] = ["CLAIMED"]

    if "claimed_by" in cols:
        set_parts.append("claimed_by = %s")
        set_vals.append(worker_id)
    if "claimed_at" in cols:
        set_parts.append("claimed_at = %s")
        set_vals.append(now_iso())
    if "claimed_at_ms" in cols:
        set_parts.append("claimed_at_ms = %s")
        set_vals.append(now_ms())
    if "next_retry_at_ms" in cols:
        set_parts.append("next_retry_at_ms = NULL")

    where_parts: list[str] = []
    pick_vals: list[Any] = []
    if "status" in cols:
        where_parts.append("UPPER(COALESCE(status,'')) IN ('PENDING','FAILED')")
    if "next_retry_at_ms" in cols:
        where_parts.append("(next_retry_at_ms IS NULL OR next_retry_at_ms <= %s)")
        pick_vals.append(now_ms())
    if "dead_lettered" in cols:
        where_parts.append("COALESCE(dead_lettered, FALSE) = FALSE")

    where_sql = " AND ".join(where_parts) if where_parts else "TRUE"
    order_parts: list[str] = []
    if "cmd" in cols:
        order_parts.append(
            "CASE "
            "WHEN UPPER(COALESCE(cmd,'')) = 'CLOSE_ALL_POSITIONS' THEN 0 "
            "WHEN UPPER(COALESCE(cmd,'')) LIKE 'CLOSE_%' THEN 1 "
            "WHEN UPPER(COALESCE(cmd,'')) LIKE 'REDUCE_%' THEN 1 "
            "WHEN UPPER(COALESCE(cmd,'')) = 'EXECUTE_SIGNAL' THEN 3 "
            "ELSE 2 END"
        )
    order_parts.append("id ASC")
    order_sql = ", ".join(order_parts)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH picked AS (
                SELECT id
                FROM {schema}.commands
                WHERE {where_sql}
                ORDER BY {order_sql}
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE {schema}.commands AS c
            SET {', '.join(set_parts)}
            FROM picked
            WHERE c.id = picked.id
              AND UPPER(COALESCE(c.status,'')) IN ('PENDING','FAILED')
            RETURNING c.*
            """,
            tuple(pick_vals + set_vals),
        )
        row = cur.fetchone() or {}
    return dict(row) if row else None


def mark_command(
    conn: psycopg.Connection,
    schema: str,
    command_id: int,
    *,
    status: str,
    ack_meta: Mapping[str, Any] | None = None,
    last_error: str | None = None,
) -> None:
    if not table_exists(conn, schema, "commands"):
        return
    cols = table_columns(conn, schema, "commands")

    updates: list[str] = []
    vals: list[Any] = []
    status_upper = str(status or "").strip().upper() or "DONE"

    if "status" in cols:
        updates.append("status = %s")
        vals.append(status_upper)

    if status_upper in {"DONE", "REJECTED", "FAILED", "DEAD"}:
        if "done_at" in cols:
            updates.append("done_at = %s")
            vals.append(now_iso())
        if "done_at_ms" in cols:
            updates.append("done_at_ms = %s")
            vals.append(now_ms())

    if "ack_meta" in cols and ack_meta is not None:
        updates.append("ack_meta = %s")
        vals.append(json.dumps(dict(ack_meta), ensure_ascii=True, default=str))

    if "last_error" in cols and last_error is not None:
        updates.append("last_error = %s")
        vals.append(str(last_error))

    if not updates:
        return

    vals.append(int(command_id))
    with conn.cursor() as cur:
        cur.execute(f"UPDATE {schema}.commands SET {', '.join(updates)} WHERE id = %s", tuple(vals))


def _backoff_ms(attempt_count: int) -> int:
    base_ms = max(250, safe_int(_env("NAUTILUS_RETRY_BASE_MS", "1000"), 1000))
    cap_ms = max(base_ms, safe_int(_env("NAUTILUS_RETRY_CAP_MS", "60000"), 60000))
    jitter_ms = max(0, safe_int(_env("NAUTILUS_RETRY_JITTER_MS", "250"), 250))
    exp_ms = base_ms * (2 ** max(0, int(attempt_count) - 1))
    wait_ms = min(cap_ms, exp_ms)
    if jitter_ms > 0:
        wait_ms = min(cap_ms, wait_ms + random.randint(0, jitter_ms))
    return int(wait_ms)


def _is_transient_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError, psycopg.OperationalError, psycopg.InterfaceError)):
        return True
    msg = str(exc or "").strip().lower()
    return any(token in msg for token in RETRYABLE_ERROR_TOKENS)


def _insert_dead_letter(
    conn: psycopg.Connection,
    schema: str,
    *,
    cmd_row: Mapping[str, Any],
    status: str,
    attempt_count: int,
    max_attempts: int,
    failed_at_ms: int,
    last_error: str,
) -> None:
    if not table_exists(conn, schema, "command_dead_letters"):
        return
    cols = table_columns(conn, schema, "command_dead_letters")
    fields: list[str] = []
    vals: list[Any] = []

    cmd_params = safe_json_loads(cmd_row.get("params"), {})
    if not isinstance(cmd_params, (dict, list)):
        cmd_params = {}

    def add(col: str, val: Any) -> None:
        if col in cols:
            fields.append(col)
            vals.append(val)

    add("command_id", safe_int(cmd_row.get("id"), 0))
    add("cmd", str(cmd_row.get("cmd") or ""))
    add("params", json.dumps(cmd_params, ensure_ascii=True, default=str))
    add("status", str(status or "DEAD"))
    add("attempt_count", int(attempt_count))
    add("max_attempts", int(max_attempts))
    add("claimed_by", str(cmd_row.get("claimed_by") or ""))
    add("created_at_ms", safe_int(cmd_row.get("created_at_ms"), 0))
    add("failed_at_ms", int(failed_at_ms))
    add("last_error", str(last_error or ""))
    add("inserted_at_ms", now_ms())

    if not fields:
        return

    placeholders = ",".join(["%s"] * len(fields))
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {schema}.command_dead_letters ({', '.join(fields)}) VALUES ({placeholders})",
            tuple(vals),
        )


def schedule_retry_or_dead_letter(
    conn: psycopg.Connection,
    schema: str,
    *,
    cmd_row: Mapping[str, Any],
    exc: Exception,
) -> str:
    if not table_exists(conn, schema, "commands"):
        return "FAILED"
    cols = table_columns(conn, schema, "commands")
    command_id = safe_int(cmd_row.get("id"), 0)
    if command_id <= 0:
        return "FAILED"

    old_attempt = max(0, safe_int(cmd_row.get("attempt_count"), 0))
    max_attempts = max(1, safe_int(cmd_row.get("max_attempts"), 5))
    next_attempt = old_attempt + 1
    err_text = f"{type(exc).__name__}: {exc}"
    transient = _is_transient_error(exc)
    retryable = True
    terminal = (not retryable) or (next_attempt >= max_attempts)

    updates: list[str] = []
    vals: list[Any] = []

    def set_col(col: str, value: Any, expr: str = "%s") -> None:
        if col in cols:
            updates.append(f"{col} = {expr}")
            if expr == "%s":
                vals.append(value)

    retry_at_ms = 0
    if terminal:
        set_col("status", "DEAD")
        set_col("dead_lettered", True)
        set_col("next_retry_at_ms", None)
        set_col("attempt_count", next_attempt)
        set_col("max_attempts", max_attempts)
        set_col("last_error", err_text)
        set_col("last_error_at_ms", now_ms())
        if "done_at" in cols:
            set_col("done_at", now_iso())
        if "done_at_ms" in cols:
            set_col("done_at_ms", now_ms())
    else:
        retry_at_ms = now_ms() + _backoff_ms(next_attempt)
        set_col("status", "FAILED")
        set_col("dead_lettered", False)
        set_col("next_retry_at_ms", retry_at_ms)
        set_col("attempt_count", next_attempt)
        set_col("max_attempts", max_attempts)
        set_col("last_error", err_text)
        set_col("last_error_at_ms", now_ms())
        if "done_at" in cols:
            set_col("done_at", None)
        if "done_at_ms" in cols:
            set_col("done_at_ms", None)

    if not updates:
        return "FAILED"

    vals.append(command_id)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE {schema}.commands SET {', '.join(updates)} WHERE id = %s", tuple(vals))

    if terminal:
        _insert_dead_letter(
            conn,
            schema,
            cmd_row=cmd_row,
            status="DEAD",
            attempt_count=next_attempt,
            max_attempts=max_attempts,
            failed_at_ms=now_ms(),
            last_error=err_text,
        )
        insert_log(
            conn,
            schema,
            "ERROR",
            (
                f"dead-lettered command id={command_id} cmd={cmd_row.get('cmd')} "
                f"attempt={next_attempt}/{max_attempts} transient={transient}"
            ),
        )
        return "DEAD"

    insert_log(
        conn,
        schema,
        "WARN",
        (
            f"command retry scheduled id={command_id} cmd={cmd_row.get('cmd')} "
            f"attempt={next_attempt}/{max_attempts} transient={transient} next_retry_at_ms={retry_at_ms}"
        ),
    )
    return "FAILED"


def insert_open_trade(
    conn: psycopg.Connection,
    schema: str,
    *,
    symbol: str,
    side: str,
    params: Mapping[str, Any],
    trace_id: str,
    decision_id: str,
    schema_version: str,
) -> int:
    if not table_exists(conn, schema, "trades"):
        return 0

    cols = table_columns(conn, schema, "trades")
    entry = safe_float(params.get("entry_price") or params.get("price") or params.get("mark_price") or 0.0, 0.0)
    qty = safe_float(params.get("quantity") or params.get("qty") or params.get("size") or 1.0, 1.0)

    fields: list[str] = []
    vals: list[Any] = []

    def add(col: str, val: Any) -> None:
        if col in cols:
            fields.append(col)
            vals.append(val)

    add("symbol", symbol)
    add("pair", symbol)
    add("signal", side)
    add("side", side)
    add("status", "OPEN")
    add("entry_price", entry)
    add("price", entry)
    add("quantity", qty)
    add("qty", qty)
    add("size", qty)
    add("timestamp", now_iso())
    add("timestamp_ms", now_ms())
    add("created_at", now_iso())
    add("created_at_ms", now_ms())
    add("source", "nautilus_engine")
    add("trace_id", trace_id)
    add("decision_id", decision_id)
    add("schema_version", schema_version)

    if not fields:
        return 0

    placeholders = ",".join(["%s"] * len(fields))
    with conn.cursor() as cur:
        if "id" in cols:
            cur.execute(
                f"INSERT INTO {schema}.trades ({', '.join(fields)}) VALUES ({placeholders}) RETURNING id",
                tuple(vals),
            )
            row = cur.fetchone() or {}
            return safe_int(row.get("id"), 0)

        cur.execute(f"INSERT INTO {schema}.trades ({', '.join(fields)}) VALUES ({placeholders})", tuple(vals))
    return 0


def close_trade_by_id(conn: psycopg.Connection, schema: str, trade_id: int, reason: str) -> bool:
    if not table_exists(conn, schema, "trades"):
        return False
    cols = table_columns(conn, schema, "trades")
    if "id" not in cols:
        return False

    updates: list[str] = []
    vals: list[Any] = []

    if "status" in cols:
        updates.append("status = %s")
        vals.append("CLOSED")
    if "close_reason" in cols:
        updates.append("close_reason = %s")
        vals.append(str(reason))
    if "closed_at" in cols:
        updates.append("closed_at = %s")
        vals.append(now_iso())
    if "closed_at_ms" in cols:
        updates.append("closed_at_ms = %s")
        vals.append(now_ms())
    if "updated_at" in cols:
        updates.append("updated_at = %s")
        vals.append(now_iso())
    if "updated_at_ms" in cols:
        updates.append("updated_at_ms = %s")
        vals.append(now_ms())
    if "close_price" in cols and "entry_price" in cols:
        updates.append("close_price = COALESCE(close_price, entry_price)")

    if not updates:
        return False

    vals.append(int(trade_id))
    with conn.cursor() as cur:
        cur.execute(f"UPDATE {schema}.trades SET {', '.join(updates)} WHERE id = %s", tuple(vals))
        return cur.rowcount > 0


def close_all_positions(conn: psycopg.Connection, schema: str, reason: str) -> int:
    if not table_exists(conn, schema, "trades"):
        return 0
    cols = table_columns(conn, schema, "trades")
    if "id" not in cols:
        return 0

    with conn.cursor() as cur:
        if "status" in cols:
            cur.execute(f"SELECT id FROM {schema}.trades WHERE UPPER(COALESCE(status,'')) = 'OPEN' ORDER BY id ASC")
        else:
            cur.execute(f"SELECT id FROM {schema}.trades ORDER BY id ASC")
        rows = cur.fetchall() or []

    closed = 0
    for row in rows:
        tid = safe_int((row or {}).get("id"), 0)
        if tid <= 0:
            continue
        if close_trade_by_id(conn, schema, tid, reason):
            closed += 1
    return closed


def is_opening_command(cmd: str) -> bool:
    c = str(cmd or "").strip().upper()
    if c in OPENING_COMMANDS:
        return True
    return c.startswith("OPEN_") or c.startswith("ENTER_") or c == "EXECUTE_SIGNAL"


def is_closing_command(cmd: str) -> bool:
    c = str(cmd or "").strip().upper()
    if c in CLOSING_COMMANDS:
        return True
    return c.startswith("CLOSE_") or c.startswith("REDUCE_")


def normalize_side(raw: Any) -> str:
    side = str(raw or "").strip().upper().replace("-", "_").replace(" ", "_")
    if side in {"BUY", "LONG", "MANUAL_BUY", "MANUAL_LONG"}:
        return "LONG"
    if side in {"SELL", "SHORT", "MANUAL_SELL", "MANUAL_SHORT"}:
        return "SHORT"
    return side or "LONG"


def _live_open_allowed(conn: psycopg.Connection, schema: str) -> tuple[bool, str, Dict[str, Any]]:
    execution_enabled = (
        truthy(fetch_setting(conn, schema, "execution_enabled", "0"))
        or truthy(fetch_setting(conn, schema, "live_execution_enabled", "0"))
        or truthy(fetch_setting(conn, schema, "ENABLE_LIVE_TRADING", "0"))
    )

    mode = str(fetch_setting(conn, schema, "mode", fetch_setting(conn, schema, "RUN_MODE", "")) or "").upper()
    testnet_flag = (
        truthy(fetch_setting(conn, schema, "USE_TESTNET", "0"))
        or truthy(fetch_setting(conn, schema, "use_testnet", "0"))
        or truthy(fetch_setting(conn, schema, "TESTNET", "0"))
        or truthy(fetch_setting(conn, schema, "sandbox", "0"))
        or mode in SAFE_LIVE_MODES
    )

    override = truthy(_env("LIVE_EXECUTION_ALLOWED", "0"))
    allowed = bool(execution_enabled and (testnet_flag or override))

    details = {
        "execution_enabled": bool(execution_enabled),
        "safe_testnet_or_sandbox": bool(testnet_flag),
        "live_execution_allowed_override": bool(override),
        "mode": mode,
    }

    if not execution_enabled:
        return False, "live_execution_disabled", details
    if not (testnet_flag or override):
        return False, "live_execution_not_safe", details
    return allowed, "ok", details


def _emit_health_heartbeat(
    conn: psycopg.Connection,
    *,
    role: str,
    schema: str,
    engine_id: str,
    execution_mode: str,
    schema_version: str,
) -> None:
    ts_iso = now_iso()
    set_setting(conn, schema, "last_heartbeat", ts_iso)
    set_setting(conn, schema, "bot_heartbeat", ts_iso)
    set_setting(conn, schema, "execution_monitor_heartbeat", ts_iso)

    trace_id = uuid.uuid4().hex
    decision_id = uuid.uuid4().hex
    payload = {
        "component": "nautilus_engine",
        "engine_id": engine_id,
        "role": role,
        "schema": schema,
        "execution_mode": execution_mode,
        "created_at": ts_iso,
        "created_at_ms": now_ms(),
    }
    append_event(
        conn,
        schema,
        role=role,
        event_type="HealthEvent",
        payload=payload,
        trace_id=trace_id,
        decision_id=decision_id,
        schema_version=schema_version,
    )


def process_command(
    conn: psycopg.Connection,
    role: str,
    schema: str,
    cmd_row: Mapping[str, Any],
    *,
    execution_mode: str,
) -> None:
    command_id = safe_int(cmd_row.get("id"), 0)
    cmd = str(cmd_row.get("cmd") or "").strip().upper()
    params = safe_json_loads(cmd_row.get("params"), {})
    if not isinstance(params, dict):
        params = {}

    trace_id = str(params.get("trace_id") or cmd_row.get("trace_id") or uuid.uuid4().hex)
    decision_id = str(params.get("decision_id") or uuid.uuid4().hex)
    schema_version = str(params.get("schema_version") or _env("SIGNAL_SCHEMA_VERSION", "v1"))

    if command_id <= 0:
        return

    kill_switch_on = truthy(fetch_setting(conn, schema, "kill_switch", "0"))
    if kill_switch_on and is_opening_command(cmd):
        msg = f"kill_switch=1 blocked opening command {cmd}"
        insert_log(conn, schema, "WARN", msg)
        append_event(
            conn,
            schema,
            role=role,
            event_type="TradeEvent",
            payload={"action": "BLOCK", "cmd": cmd, "reason": "kill_switch", "command_id": command_id},
            trace_id=trace_id,
            decision_id=decision_id,
            schema_version=schema_version,
        )
        mark_command(
            conn,
            schema,
            command_id,
            status="REJECTED",
            ack_meta={"ok": False, "blocked": "kill_switch", "cmd": cmd},
            last_error="kill_switch blocks opening commands",
        )
        return

    if role == "live" and is_opening_command(cmd):
        allowed, reason, details = _live_open_allowed(conn, schema)
        if not allowed:
            insert_log(conn, schema, "WARN", f"live safety gate blocked opening command {cmd}: {reason}")
            append_event(
                conn,
                schema,
                role=role,
                event_type="TradeEvent",
                payload={
                    "action": "BLOCK",
                    "cmd": cmd,
                    "reason": reason,
                    "details": details,
                    "command_id": command_id,
                },
                trace_id=trace_id,
                decision_id=decision_id,
                schema_version=schema_version,
            )
            mark_command(
                conn,
                schema,
                command_id,
                status="REJECTED",
                ack_meta={"ok": False, "blocked": reason, "cmd": cmd, "details": details},
                last_error=reason,
            )
            return

    if cmd == "EXECUTE_SIGNAL":
        symbol = str(params.get("symbol") or params.get("pair") or "").strip().upper() or "UNKNOWN"
        side = normalize_side(params.get("side") or params.get("signal") or params.get("direction"))
        trade_id = insert_open_trade(
            conn,
            schema,
            symbol=symbol,
            side=side,
            params=params,
            trace_id=trace_id,
            decision_id=decision_id,
            schema_version=schema_version,
        )

        insert_log(conn, schema, "INFO", f"simulated EXECUTE_SIGNAL -> trade_id={trade_id} {symbol} {side}")
        evt_payload = {
            "action": "OPEN",
            "command": cmd,
            "command_id": command_id,
            "trade_id": trade_id,
            "symbol": symbol,
            "side": side,
            "execution_mode": execution_mode,
        }
        append_trade_event(
            conn,
            schema,
            role=role,
            event_type="TradeEvent",
            payload=evt_payload,
            trace_id=trace_id,
            decision_id=decision_id,
            schema_version=schema_version,
        )
        append_event(
            conn,
            schema,
            role=role,
            event_type="TradeEvent",
            payload=evt_payload,
            trace_id=trace_id,
            decision_id=decision_id,
            schema_version=schema_version,
        )
        mark_command(
            conn,
            schema,
            command_id,
            status="DONE",
            ack_meta={"ok": True, "simulated": True, "trade_id": trade_id, "cmd": cmd},
        )
        return

    if cmd == "CLOSE_ALL_POSITIONS":
        reason = str(params.get("reason") or "nautilus_close_all")
        closed = close_all_positions(conn, schema, reason)
        insert_log(conn, schema, "INFO", f"simulated CLOSE_ALL_POSITIONS -> closed={closed}")
        evt_payload = {
            "action": "CLOSE_ALL",
            "command": cmd,
            "command_id": command_id,
            "closed": closed,
            "reason": reason,
            "execution_mode": execution_mode,
        }
        append_trade_event(
            conn,
            schema,
            role=role,
            event_type="TradeEvent",
            payload=evt_payload,
            trace_id=trace_id,
            decision_id=decision_id,
            schema_version=schema_version,
        )
        append_event(
            conn,
            schema,
            role=role,
            event_type="TradeEvent",
            payload=evt_payload,
            trace_id=trace_id,
            decision_id=decision_id,
            schema_version=schema_version,
        )
        mark_command(
            conn,
            schema,
            command_id,
            status="DONE",
            ack_meta={"ok": True, "simulated": True, "closed": closed, "cmd": cmd},
        )
        return

    if cmd == "CLOSE_TRADE":
        trade_id = safe_int(params.get("trade_id"), 0)
        reason = str(params.get("reason") or "nautilus_close_trade")
        closed = close_trade_by_id(conn, schema, trade_id, reason) if trade_id > 0 else False
        insert_log(conn, schema, "INFO", f"simulated CLOSE_TRADE trade_id={trade_id} closed={closed}")
        evt_payload = {
            "action": "CLOSE",
            "command": cmd,
            "command_id": command_id,
            "trade_id": trade_id,
            "closed": bool(closed),
            "reason": reason,
            "execution_mode": execution_mode,
        }
        append_trade_event(
            conn,
            schema,
            role=role,
            event_type="TradeEvent",
            payload=evt_payload,
            trace_id=trace_id,
            decision_id=decision_id,
            schema_version=schema_version,
        )
        append_event(
            conn,
            schema,
            role=role,
            event_type="TradeEvent",
            payload=evt_payload,
            trace_id=trace_id,
            decision_id=decision_id,
            schema_version=schema_version,
        )
        mark_command(
            conn,
            schema,
            command_id,
            status="DONE",
            ack_meta={"ok": True, "simulated": True, "trade_id": trade_id, "closed": bool(closed), "cmd": cmd},
        )
        return

    if cmd == "TEST_FAIL_ONCE":
        prior_attempts = safe_int(cmd_row.get("attempt_count"), 0)
        if prior_attempts < 1:
            raise RuntimeError("synthetic_transient_fail_once")
        insert_log(conn, schema, "INFO", f"TEST_FAIL_ONCE recovered after attempt_count={prior_attempts}")
        mark_command(
            conn,
            schema,
            command_id,
            status="DONE",
            ack_meta={"ok": True, "test": "TEST_FAIL_ONCE", "attempt_count": prior_attempts},
        )
        return

    if cmd == "TEST_ALWAYS_FAIL":
        raise RuntimeError("synthetic_always_fail")

    insert_log(conn, schema, "INFO", f"ignored command {cmd}")
    mark_command(conn, schema, command_id, status="DONE", ack_meta={"ok": True, "ignored": True, "cmd": cmd})


def run_loop() -> None:
    role_targets = resolve_role_schemas()

    execution_mode = _env("EXECUTION_MODE", _env("NAUTILUS_MODE", "SIM")).strip().upper() or "SIM"
    engine_id = _env("ENGINE_ID", _env("ENGINE_NAME", _env("HOSTNAME", "nautilus_engine"))).strip() or "nautilus_engine"
    poll_sec = max(1, safe_int(_env("NAUTILUS_POLL_SEC", "2"), 2))
    hb_sec = max(5, safe_int(_env("HEALTH_HEARTBEAT_SEC", "15"), 15))
    default_schema_version = _env("SIGNAL_SCHEMA_VERSION", "v1")

    try:
        import nautilus_trader  # type: ignore  # noqa: F401

        print("[nautilus_engine] nautilus_trader import: OK")
    except Exception:
        print("[nautilus_engine] nautilus_trader import: unavailable (running skeleton mode)")

    print(
        f"[nautilus_engine] start execution_mode={execution_mode} targets={role_targets} poll={poll_sec}s heartbeat={hb_sec}s"
    )

    try:
        with connect() as conn:
            for _, schema in role_targets:
                ensure_schema_tables(conn, schema)
                ensure_consumer_schema(conn, schema)
    except Exception as exc:
        print(f"[nautilus_engine] schema ensure error: {type(exc).__name__}: {exc}")

    last_hb_ms: Dict[str, int] = {}

    while True:
        did_work = False
        try:
            with connect() as conn:
                loop_now_ms = now_ms()
                for role, schema in role_targets:
                    hb_key = f"{role}:{schema}"
                    if loop_now_ms - safe_int(last_hb_ms.get(hb_key), 0) >= hb_sec * 1000:
                        _emit_health_heartbeat(
                            conn,
                            role=role,
                            schema=schema,
                            engine_id=engine_id,
                            execution_mode=execution_mode,
                            schema_version=default_schema_version,
                        )
                        last_hb_ms[hb_key] = loop_now_ms

                    while True:
                        cmd_row = claim_next_pending_command(conn, schema, engine_id)
                        if not cmd_row:
                            break
                        did_work = True
                        try:
                            process_command(conn, role, schema, cmd_row, execution_mode=execution_mode)
                        except Exception as exc:
                            cid = safe_int((cmd_row or {}).get("id"), 0)
                            if cid > 0:
                                schedule_retry_or_dead_letter(conn, schema, cmd_row=cmd_row, exc=exc)
        except Exception as exc:
            print(f"[nautilus_engine] loop error: {type(exc).__name__}: {exc}")

        if not did_work:
            time.sleep(poll_sec)


def main() -> None:
    run_loop()


if __name__ == "__main__":
    main()
