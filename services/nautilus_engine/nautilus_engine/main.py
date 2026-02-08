from __future__ import annotations

import datetime as dt
import json
import os
import time
import uuid
from typing import Any, Dict, Iterable, Mapping

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


def append_event(
    conn: psycopg.Connection,
    schema: str,
    *,
    role: str,
    action: str,
    payload: Mapping[str, Any],
    trace_id: str,
    decision_id: str,
    schema_version: str,
) -> None:
    if not table_exists(conn, schema, "events"):
        return
    cols = table_columns(conn, schema, "events")

    event_payload = {
        "schema_version": schema_version,
        "trace_id": trace_id,
        "decision_id": decision_id,
        "action": action,
        **dict(payload or {}),
    }

    fields: list[str] = []
    vals: list[Any] = []

    def add(col: str, val: Any) -> None:
        if col in cols:
            fields.append(col)
            vals.append(val)

    add("event_type", "TradeEvent")
    add("type", "TradeEvent")
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
        cur.execute(f"INSERT INTO {schema}.events ({', '.join(fields)}) VALUES ({placeholders})", tuple(vals))


def append_trade_event(
    conn: psycopg.Connection,
    schema: str,
    *,
    action: str,
    payload: Mapping[str, Any],
    trace_id: str,
    decision_id: str,
    schema_version: str,
) -> None:
    if not table_exists(conn, schema, "trade_events"):
        return
    cols = table_columns(conn, schema, "trade_events")

    event_payload = {
        "schema_version": schema_version,
        "trace_id": trace_id,
        "decision_id": decision_id,
        "action": action,
        **dict(payload or {}),
    }

    fields: list[str] = []
    vals: list[Any] = []

    def add(col: str, val: Any) -> None:
        if col in cols:
            fields.append(col)
            vals.append(val)

    add("event_type", "TradeEvent")
    add("payload_json", json.dumps(event_payload, ensure_ascii=True, default=str))
    add("source", "nautilus_engine")
    add("created_at", now_iso())
    add("created_at_ms", now_ms())
    add("trace_id", trace_id)
    add("decision_id", decision_id)
    add("schema_version", schema_version)

    if not fields:
        return

    placeholders = ",".join(["%s"] * len(fields))
    with conn.cursor() as cur:
        cur.execute(f"INSERT INTO {schema}.trade_events ({', '.join(fields)}) VALUES ({placeholders})", tuple(vals))


def claim_next_pending_command(conn: psycopg.Connection, schema: str, worker_id: str) -> dict | None:
    if not table_exists(conn, schema, "commands"):
        return None
    cols = table_columns(conn, schema, "commands")
    if "id" not in cols or "cmd" not in cols:
        return None

    with conn.cursor() as cur:
        if "status" in cols:
            cur.execute(
                f"SELECT * FROM {schema}.commands WHERE UPPER(COALESCE(status,'')) = 'PENDING' ORDER BY id ASC LIMIT 1"
            )
        else:
            cur.execute(f"SELECT * FROM {schema}.commands ORDER BY id ASC LIMIT 1")
        row = cur.fetchone()

    if not row:
        return None
    cmd_row = dict(row)

    if "status" in cols:
        updates: list[str] = ["status = %s"]
        vals: list[Any] = ["CLAIMED"]

        if "claimed_by" in cols:
            updates.append("claimed_by = %s")
            vals.append(worker_id)
        if "claimed_at" in cols:
            updates.append("claimed_at = %s")
            vals.append(now_iso())
        if "claimed_at_ms" in cols:
            updates.append("claimed_at_ms = %s")
            vals.append(now_ms())

        vals.extend([int(cmd_row.get("id")), "PENDING"])
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE {schema}.commands SET {', '.join(updates)} WHERE id = %s AND UPPER(COALESCE(status,'')) = %s",
                tuple(vals),
            )
            if cur.rowcount <= 0:
                return None
            cur.execute(f"SELECT * FROM {schema}.commands WHERE id = %s", (int(cmd_row.get("id")),))
            updated = cur.fetchone() or {}
        return dict(updated)

    return cmd_row


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

    if "status" in cols:
        updates.append("status = %s")
        vals.append(str(status))
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


def process_command(conn: psycopg.Connection, role: str, schema: str, cmd_row: Mapping[str, Any]) -> None:
    command_id = safe_int(cmd_row.get("id"), 0)
    cmd = str(cmd_row.get("cmd") or "").strip().upper()
    params = safe_json_loads(cmd_row.get("params"), {})
    if not isinstance(params, dict):
        params = {}

    trace_id = str(params.get("trace_id") or cmd_row.get("trace_id") or uuid.uuid4().hex)
    decision_id = str(params.get("decision_id") or uuid.uuid4().hex)
    schema_version = str(params.get("schema_version") or _env("SIGNAL_SCHEMA_VERSION", "v1"))

    kill_switch_on = truthy(fetch_setting(conn, schema, "kill_switch", "0"))
    if kill_switch_on and is_opening_command(cmd):
        msg = f"kill_switch=1 blocked opening command {cmd}"
        insert_log(conn, schema, "WARN", msg)
        append_event(
            conn,
            schema,
            role=role,
            action="BLOCK",
            payload={"cmd": cmd, "reason": "kill_switch", "command_id": command_id},
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

    if cmd == "EXECUTE_SIGNAL":
        symbol = str(params.get("symbol") or params.get("pair") or "").strip().upper()
        if not symbol:
            symbol = "UNKNOWN"
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
            "command": cmd,
            "command_id": command_id,
            "trade_id": trade_id,
            "symbol": symbol,
            "side": side,
            "execution_mode": "PAPER",
        }
        append_trade_event(
            conn,
            schema,
            action="OPEN",
            payload=evt_payload,
            trace_id=trace_id,
            decision_id=decision_id,
            schema_version=schema_version,
        )
        append_event(
            conn,
            schema,
            role=role,
            action="OPEN",
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
            "command": cmd,
            "command_id": command_id,
            "closed": closed,
            "reason": reason,
            "execution_mode": "PAPER",
        }
        append_trade_event(
            conn,
            schema,
            action="CLOSE_ALL",
            payload=evt_payload,
            trace_id=trace_id,
            decision_id=decision_id,
            schema_version=schema_version,
        )
        append_event(
            conn,
            schema,
            role=role,
            action="CLOSE_ALL",
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
            "command": cmd,
            "command_id": command_id,
            "trade_id": trade_id,
            "closed": bool(closed),
            "reason": reason,
            "execution_mode": "PAPER",
        }
        append_trade_event(
            conn,
            schema,
            action="CLOSE",
            payload=evt_payload,
            trace_id=trace_id,
            decision_id=decision_id,
            schema_version=schema_version,
        )
        append_event(
            conn,
            schema,
            role=role,
            action="CLOSE",
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

    # Unknown command: acknowledge to keep queue moving.
    insert_log(conn, schema, "INFO", f"ignored command {cmd}")
    mark_command(conn, schema, command_id, status="DONE", ack_meta={"ok": True, "ignored": True, "cmd": cmd})


def run_loop() -> None:
    raw_roles = [x.strip().lower() for x in _env("NAUTILUS_ROLES", "paper").split(",") if x.strip()]
    roles = [r for r in raw_roles if r in ROLE_TO_SCHEMA]
    if not roles:
        roles = ["paper"]

    mode = _env("NAUTILUS_MODE", "PAPER").strip().upper()
    if mode not in {"PAPER", "SIM"}:
        print(f"[nautilus_engine] unsupported mode={mode}, forcing PAPER")
        mode = "PAPER"

    engine_id = _env("ENGINE_ID", "nautilus_engine").strip() or "nautilus_engine"
    poll_sec = max(1, safe_int(_env("NAUTILUS_POLL_SEC", "2"), 2))

    try:
        import nautilus_trader  # type: ignore  # noqa: F401

        print("[nautilus_engine] nautilus_trader import: OK")
    except Exception:
        print("[nautilus_engine] nautilus_trader import: unavailable (running skeleton mode)")

    print(f"[nautilus_engine] start mode={mode} roles={roles} poll={poll_sec}s")

    while True:
        did_work = False
        try:
            with connect() as conn:
                for role in roles:
                    schema = role_to_schema(role)
                    ensure_schema_tables(conn, schema)

                    while True:
                        cmd_row = claim_next_pending_command(conn, schema, engine_id)
                        if not cmd_row:
                            break
                        did_work = True
                        try:
                            process_command(conn, role, schema, cmd_row)
                        except Exception as exc:
                            cid = safe_int((cmd_row or {}).get("id"), 0)
                            insert_log(conn, schema, "ERROR", f"command failed id={cid}: {type(exc).__name__}: {exc}")
                            if cid > 0:
                                mark_command(
                                    conn,
                                    schema,
                                    cid,
                                    status="ERROR",
                                    ack_meta={"ok": False, "error": str(exc)},
                                    last_error=str(exc),
                                )
        except Exception as exc:
            print(f"[nautilus_engine] loop error: {type(exc).__name__}: {exc}")

        if not did_work:
            time.sleep(poll_sec)


def main() -> None:
    run_loop()


if __name__ == "__main__":
    main()
