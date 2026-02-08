from __future__ import annotations

import datetime as dt
import json
import os
import time
import uuid
from typing import Any, Dict, Iterable, Literal, Mapping, Sequence

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row


Role = Literal["paper", "live", "pump"]

_DEFAULT_DSN = "postgresql://trading:trading@postgres:5432/trading"
_ROLE_TO_SCHEMA: Dict[str, str] = {
    "paper": "mina_paper",
    "live": "mina_live",
    "pump": "mina_pump",
}
_ALLOWED_STATUS = {"RECEIVED", "PENDING_APPROVAL", "APPROVED", "REJECTED", "EXECUTED", "PENDING"}


def _normalize_dsn(raw: str) -> str:
    dsn = str(raw or "").strip()
    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn[len("postgres://") :]
    if dsn.startswith("postgresql+psycopg://"):
        dsn = "postgresql://" + dsn[len("postgresql+psycopg://") :]
    if dsn.startswith("postgresql+psycopg2://"):
        dsn = "postgresql://" + dsn[len("postgresql+psycopg2://") :]
    return dsn


def get_dsn() -> str:
    raw = os.getenv("TRADING_PG_DSN") or os.getenv("DATABASE_URL") or _DEFAULT_DSN
    return _normalize_dsn(raw)


def role_to_schema(role: str) -> str:
    r = str(role or "").strip().lower()
    if r not in _ROLE_TO_SCHEMA:
        raise ValueError(f"unknown role: {role!r}")
    return _ROLE_TO_SCHEMA[r]


def now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now_ms() -> int:
    return int(time.time() * 1000)


def _ms_to_iso(ms: int) -> str | None:
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000.0, tz=dt.timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def _parse_ts_ms(value: Any) -> int | None:
    if value is None:
        return None
    txt = str(value).strip()
    if not txt:
        return None
    try:
        n = int(float(txt))
        if n > 10_000_000_000:
            return n
        if n > 0:
            return n * 1000
    except Exception:
        pass
    try:
        ts = dt.datetime.fromisoformat(txt.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        return int(ts.astimezone(dt.timezone.utc).timestamp() * 1000)
    except Exception:
        return None


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _safe_json_loads(value: Any, default: Any) -> Any:
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


def _extract_field(payload: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload and payload.get(key) is not None and str(payload.get(key)).strip() != "":
            return payload.get(key)
    return default


def _is_missing_relation(exc: Exception) -> bool:
    if isinstance(exc, (pg_errors.UndefinedTable, pg_errors.UndefinedColumn, pg_errors.InvalidSchemaName)):
        return True
    msg = str(exc or "").lower()
    return "does not exist" in msg or "undefined table" in msg


def safe_execute(
    schema: str,
    sql: str,
    params: Sequence[Any] | None = None,
    *,
    fetch: str = "all",
    default: Any = None,
) -> Any:
    if params is None:
        params = ()
    query = str(sql).format(schema=schema)
    try:
        with psycopg.connect(get_dsn(), autocommit=True, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                if fetch == "one":
                    row = cur.fetchone()
                    return dict(row) if isinstance(row, dict) else row
                if fetch == "none":
                    return default
                rows = cur.fetchall() or []
                out = []
                for row in rows:
                    out.append(dict(row) if isinstance(row, dict) else row)
                return out
    except Exception as exc:
        if _is_missing_relation(exc):
            return default
        return default


def table_exists(schema: str, table: str) -> bool:
    row = safe_execute(
        schema,
        """
        SELECT 1 AS ok
        FROM information_schema.tables
        WHERE table_schema = %s AND table_name = %s
        LIMIT 1
        """,
        (schema, table),
        fetch="one",
        default=None,
    )
    return bool(row)


def table_columns(schema: str, table: str) -> set[str]:
    rows = safe_execute(
        schema,
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
        default=[],
    )
    return {str(r.get("column_name") or "") for r in (rows or []) if r and r.get("column_name")}


def fetch_settings(schema: str, keys: Iterable[str] | None = None) -> Dict[str, str]:
    if not table_exists(schema, "settings"):
        return {}
    cols = table_columns(schema, "settings")
    if "key" not in cols or "value" not in cols:
        return {}

    if keys is None:
        rows = safe_execute(schema, "SELECT key, value FROM {schema}.settings", default=[])
    else:
        key_list = [str(k) for k in keys if str(k or "").strip()]
        if not key_list:
            return {}
        placeholders = ",".join(["%s"] * len(key_list))
        rows = safe_execute(
            schema,
            f"SELECT key, value FROM {{schema}}.settings WHERE key IN ({placeholders})",
            tuple(key_list),
            default=[],
        )
    out: Dict[str, str] = {}
    for row in rows or []:
        k = str((row or {}).get("key") or "").strip()
        if not k:
            continue
        out[k] = str((row or {}).get("value") or "")
    return out


def fetch_setting(schema: str, key: str, default: str | None = None) -> str | None:
    data = fetch_settings(schema, [key])
    if key in data:
        return data[key]
    return default


def set_setting(schema: str, key: str, value: Any, source: str = "gateway") -> None:
    if not table_exists(schema, "settings"):
        return
    cols = table_columns(schema, "settings")
    if "key" not in cols or "value" not in cols:
        return

    fields = ["key", "value"]
    vals: list[Any] = [str(key), "" if value is None else str(value)]
    updates = ["value = EXCLUDED.value"]

    if "updated_at" in cols:
        fields.append("updated_at")
        vals.append(now_utc_iso())
        updates.append("updated_at = EXCLUDED.updated_at")
    if "source" in cols:
        fields.append("source")
        vals.append(str(source))
        updates.append("source = EXCLUDED.source")
    if "version" in cols:
        updates.append("version = COALESCE({schema}.settings.version, 0) + 1")

    placeholders = ",".join(["%s"] * len(fields))
    safe_execute(
        schema,
        f"""
        INSERT INTO {{schema}}.settings ({', '.join(fields)})
        VALUES ({placeholders})
        ON CONFLICT (key) DO UPDATE SET {', '.join(updates)}
        """,
        tuple(vals),
        fetch="none",
    )


def _signal_time_order_columns(cols: set[str]) -> tuple[str | None, str | None, str | None]:
    order_col = "received_at_ms" if "received_at_ms" in cols else ("created_at_ms" if "created_at_ms" in cols else ("id" if "id" in cols else None))
    ts_ms_col = "received_at_ms" if "received_at_ms" in cols else ("created_at_ms" if "created_at_ms" in cols else None)
    ts_iso_col = "received_at" if "received_at" in cols else ("created_at" if "created_at" in cols else None)
    return order_col, ts_ms_col, ts_iso_col


def list_signals(
    schema: str,
    *,
    limit: int = 50,
    status: str | None = None,
    source: str | None = None,
    symbol: str | None = None,
    timeframe: str | None = None,
    strategy: str | None = None,
    from_ms: int | None = None,
    to_ms: int | None = None,
) -> list[dict]:
    if not table_exists(schema, "signal_inbox"):
        return []
    cols = table_columns(schema, "signal_inbox")
    order_col, ts_ms_col, ts_iso_col = _signal_time_order_columns(cols)

    where: list[str] = []
    params: list[Any] = []

    st = str(status or "").strip().upper()
    if st and st != "ALL" and "status" in cols:
        where.append("UPPER(COALESCE(status,'')) = %s")
        params.append(st)

    src = str(source or "").strip()
    if src and "source" in cols:
        where.append("source ILIKE %s")
        params.append(f"%{src}%")

    sym = str(symbol or "").strip().upper()
    if sym and "symbol" in cols:
        where.append("UPPER(COALESCE(symbol,'')) = %s")
        params.append(sym)

    tf = str(timeframe or "").strip()
    if tf and "timeframe" in cols:
        where.append("LOWER(COALESCE(timeframe,'')) = %s")
        params.append(tf.lower())

    strat = str(strategy or "").strip()
    if strat and "strategy" in cols:
        where.append("strategy ILIKE %s")
        params.append(f"%{strat}%")

    if from_ms is not None:
        if ts_ms_col:
            where.append(f"{ts_ms_col} >= %s")
            params.append(int(from_ms))
        elif ts_iso_col:
            iso = _ms_to_iso(int(from_ms))
            if iso:
                where.append(f"{ts_iso_col} >= %s")
                params.append(iso)

    if to_ms is not None:
        if ts_ms_col:
            where.append(f"{ts_ms_col} <= %s")
            params.append(int(to_ms))
        elif ts_iso_col:
            iso = _ms_to_iso(int(to_ms))
            if iso:
                where.append(f"{ts_iso_col} <= %s")
                params.append(iso)

    query = "SELECT * FROM {schema}.signal_inbox"
    if where:
        query += " WHERE " + " AND ".join(where)
    if order_col:
        query += f" ORDER BY {order_col} DESC"
    query += " LIMIT %s"
    params.append(max(1, min(int(limit or 50), 1000)))

    rows = safe_execute(schema, query, tuple(params), default=[])
    out: list[dict] = []
    for row in rows or []:
        item = dict(row)
        payload_raw = item.get("payload")
        if payload_raw in (None, ""):
            payload_raw = item.get("payload_json")
        payload = _safe_json_loads(payload_raw, {})
        item["payload"] = payload if isinstance(payload, dict) else {}
        out.append(item)
    return out


def get_signal(schema: str, signal_id: int) -> dict | None:
    if not table_exists(schema, "signal_inbox"):
        return None
    row = safe_execute(
        schema,
        "SELECT * FROM {schema}.signal_inbox WHERE id = %s LIMIT 1",
        (int(signal_id),),
        fetch="one",
        default=None,
    )
    if not row:
        return None
    out = dict(row)
    payload = _safe_json_loads(out.get("payload") or out.get("payload_json"), {})
    out["payload"] = payload if isinstance(payload, dict) else {}
    return out


def _normalize_side(raw: Any) -> str:
    side = str(raw or "").strip().upper().replace("-", "_").replace(" ", "_")
    if side in {"BUY", "LONG", "MANUAL_BUY", "MANUAL_LONG"}:
        return "LONG"
    if side in {"SELL", "SHORT", "MANUAL_SELL", "MANUAL_SHORT"}:
        return "SHORT"
    return side


def insert_command(
    schema: str,
    cmd: str,
    params: Mapping[str, Any] | None,
    *,
    source: str = "gateway",
    trace_id: str | None = None,
) -> int:
    if not table_exists(schema, "commands"):
        return 0
    cols = table_columns(schema, "commands")
    if "cmd" not in cols:
        return 0

    fields = ["cmd"]
    values: list[Any] = [str(cmd or "").strip().upper()]

    if "params" in cols:
        fields.append("params")
        values.append(json.dumps(dict(params or {}), ensure_ascii=True))
    if "status" in cols:
        fields.append("status")
        values.append("PENDING")
    if "created_at" in cols:
        fields.append("created_at")
        values.append(now_utc_iso())
    if "created_at_ms" in cols:
        fields.append("created_at_ms")
        values.append(now_ms())
    if "source" in cols:
        fields.append("source")
        values.append(str(source))
    if "trace_id" in cols:
        fields.append("trace_id")
        values.append(str(trace_id or uuid.uuid4().hex))

    placeholders = ",".join(["%s"] * len(fields))
    if "id" in cols:
        row = safe_execute(
            schema,
            f"INSERT INTO {{schema}}.commands ({', '.join(fields)}) VALUES ({placeholders}) RETURNING id",
            tuple(values),
            fetch="one",
            default=None,
        )
        return _coerce_int((row or {}).get("id"), 0)

    safe_execute(
        schema,
        f"INSERT INTO {{schema}}.commands ({', '.join(fields)}) VALUES ({placeholders})",
        tuple(values),
        fetch="none",
    )
    return 0


def update_signal_status(schema: str, signal_id: int, status: str, note: str | None = None) -> bool:
    if not table_exists(schema, "signal_inbox"):
        return False
    cols = table_columns(schema, "signal_inbox")

    st = str(status or "").strip().upper()
    fields: list[str] = ["status = %s"]
    values: list[Any] = [st]

    if note is not None and "note" in cols:
        fields.append("note = %s")
        values.append(str(note))

    ts = now_ms()
    if st == "APPROVED" and "approved_at_ms" in cols:
        fields.append("approved_at_ms = %s")
        values.append(ts)
    if st == "REJECTED" and "rejected_at_ms" in cols:
        fields.append("rejected_at_ms = %s")
        values.append(ts)
    if st == "EXECUTED" and "executed_at_ms" in cols:
        fields.append("executed_at_ms = %s")
        values.append(ts)

    values.append(int(signal_id))
    safe_execute(
        schema,
        f"UPDATE {{schema}}.signal_inbox SET {', '.join(fields)} WHERE id = %s",
        tuple(values),
        fetch="none",
    )
    return True


def _insert_rejection(schema: str, symbol: str, reason: str) -> None:
    if not table_exists(schema, "rejections"):
        return
    cols = table_columns(schema, "rejections")

    fields: list[str] = []
    vals: list[Any] = []
    if "symbol" in cols:
        fields.append("symbol")
        vals.append(str(symbol or ""))
    if "reason" in cols:
        fields.append("reason")
        vals.append(str(reason or ""))
    if "value" in cols:
        fields.append("value")
        vals.append(0)
    if "threshold" in cols:
        fields.append("threshold")
        vals.append(0)
    if "timestamp" in cols:
        fields.append("timestamp")
        vals.append(now_utc_iso())
    if not fields:
        return

    placeholders = ",".join(["%s"] * len(fields))
    safe_execute(
        schema,
        f"INSERT INTO {{schema}}.rejections ({', '.join(fields)}) VALUES ({placeholders})",
        tuple(vals),
        fetch="none",
    )


def publish_signal(schema: str, payload: Mapping[str, Any]) -> int:
    if not table_exists(schema, "signal_inbox"):
        return 0
    cols = table_columns(schema, "signal_inbox")

    source = str(_extract_field(payload, "source", default="gateway") or "gateway")
    status = str(_extract_field(payload, "status", default="RECEIVED") or "RECEIVED").strip().upper()
    execution_allowed = payload.get("execution_allowed")
    if execution_allowed is False and status in {"RECEIVED", "OK", "PUBLISHED", "SIGNAL", "PENDING"}:
        status = "PENDING_APPROVAL"
    if status in {"OK", "PUBLISHED", "SIGNAL"}:
        status = "RECEIVED"
    if status not in _ALLOWED_STATUS:
        status = "RECEIVED"

    symbol = _extract_field(payload, "symbol", "pair", "s")
    strategy = _extract_field(payload, "strategy", "strategy_name")
    side = _extract_field(payload, "side", "signal", "direction")
    timeframe = _extract_field(payload, "timeframe", "tf")
    confidence = _extract_field(payload, "confidence", "conf", default=None)
    score = _extract_field(payload, "score", "pump_score", default=None)

    should_store = bool(symbol) or bool(strategy) or bool(side) or status in {"PENDING_APPROVAL", "APPROVED", "REJECTED", "EXECUTED"}
    if not should_store:
        return 0

    fields: list[str] = []
    values: list[Any] = []

    def add(col: str, value: Any) -> None:
        if col in cols:
            fields.append(col)
            values.append(value)

    add("received_at", now_utc_iso())
    add("received_at_ms", now_ms())
    add("created_at", now_utc_iso())
    add("created_at_ms", now_ms())
    add("source", source)
    add("status", status)
    add("symbol", str(symbol or "").upper() if symbol else None)
    add("timeframe", str(timeframe) if timeframe not in (None, "") else None)
    add("strategy", str(strategy) if strategy not in (None, "") else None)
    add("side", str(side) if side not in (None, "") else None)
    add("confidence", _coerce_float(confidence) if confidence is not None else None)
    add("score", _coerce_float(score) if score is not None else None)
    payload_json = dict(payload)
    add("payload", json.dumps(payload_json, ensure_ascii=True, default=str))

    if not fields:
        return 0

    placeholders = ",".join(["%s"] * len(fields))
    if "id" in cols:
        row = safe_execute(
            schema,
            f"INSERT INTO {{schema}}.signal_inbox ({', '.join(fields)}) VALUES ({placeholders}) RETURNING id",
            tuple(values),
            fetch="one",
            default=None,
        )
        return _coerce_int((row or {}).get("id"), 0)

    safe_execute(
        schema,
        f"INSERT INTO {{schema}}.signal_inbox ({', '.join(fields)}) VALUES ({placeholders})",
        tuple(values),
        fetch="none",
    )
    return 0


def approve_signal(schema: str, signal_id: int, note: str = "", payload: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    rec = get_signal(schema, int(signal_id))
    if not rec:
        raise ValueError("signal_not_found")

    merged: Dict[str, Any] = {}
    if isinstance(rec.get("payload"), dict):
        merged.update(rec.get("payload") or {})
    if isinstance(payload, Mapping):
        merged.update(dict(payload))

    for key in ("symbol", "side", "strategy", "timeframe", "confidence", "score"):
        if merged.get(key) in (None, "") and rec.get(key) not in (None, ""):
            merged[key] = rec.get(key)

    symbol = str(merged.get("symbol") or "").strip().upper()
    side = _normalize_side(merged.get("side") or merged.get("signal") or merged.get("direction"))
    if not symbol:
        raise ValueError("missing_symbol")
    if side not in {"LONG", "SHORT", "BUY", "SELL"}:
        raise ValueError("missing_invalid_side")

    trace_id = str(merged.get("trace_id") or uuid.uuid4().hex)
    decision_id = str(merged.get("decision_id") or uuid.uuid4().hex)
    schema_version = str(merged.get("schema_version") or "v1")

    merged["symbol"] = symbol
    merged["side"] = side
    merged["trace_id"] = trace_id
    merged["decision_id"] = decision_id
    merged["schema_version"] = schema_version
    merged["inbox_id"] = int(signal_id)
    merged["_dashboard_signal_id"] = int(signal_id)
    merged["_approved_by"] = "gateway"
    merged["_approved_at"] = now_utc_iso()

    cmd_id = insert_command(schema, "EXECUTE_SIGNAL", merged, source="gateway", trace_id=trace_id)
    update_signal_status(schema, int(signal_id), "APPROVED", note=note)

    return {
        "status": "ok",
        "id": int(signal_id),
        "command_id": int(cmd_id),
        "trace_id": trace_id,
        "decision_id": decision_id,
        "schema_version": schema_version,
    }


def reject_signal(schema: str, signal_id: int, reason: str, note: str = "") -> Dict[str, Any]:
    rec = get_signal(schema, int(signal_id))
    if not rec:
        raise ValueError("signal_not_found")

    symbol = str(
        rec.get("symbol")
        or ((rec.get("payload") or {}).get("symbol") if isinstance(rec.get("payload"), dict) else "")
        or "UNKNOWN"
    ).upper()

    update_signal_status(schema, int(signal_id), "REJECTED", note=note or reason)
    _insert_rejection(schema, symbol=symbol, reason=reason)
    return {"status": "ok", "id": int(signal_id)}


def _parse_positions_status(raw: Any) -> Dict[str, Dict[str, Any]]:
    data = _safe_json_loads(raw, {})
    if isinstance(data, dict):
        pos = data.get("positions")
        if isinstance(pos, list):
            out: Dict[str, Dict[str, Any]] = {}
            for item in pos:
                if not isinstance(item, dict):
                    continue
                sym = str(item.get("symbol") or "").strip().upper()
                if sym:
                    out[sym] = item
            return out
    return {}


def list_open_positions(schema: str, *, limit: int = 200) -> list[dict]:
    if not table_exists(schema, "trades"):
        return []

    cols = table_columns(schema, "trades")
    status_col = "status" if "status" in cols else None
    order_col = "id" if "id" in cols else ("created_at_ms" if "created_at_ms" in cols else None)

    where = " WHERE UPPER(COALESCE(status,'')) = 'OPEN'" if status_col else ""
    order = f" ORDER BY {order_col} DESC" if order_col else ""
    query = f"SELECT * FROM {{schema}}.trades{where}{order} LIMIT %s"
    rows = safe_execute(schema, query, (max(1, min(int(limit or 200), 2000)),), default=[])

    settings = fetch_settings(schema, ["positions_status"])
    pos_map = _parse_positions_status(settings.get("positions_status"))

    out: list[dict] = []
    for row in rows or []:
        item = dict(row)
        sym = str(item.get("symbol") or item.get("pair") or "").strip().upper()
        if sym and sym in pos_map:
            p = pos_map[sym]
            if item.get("mark_price") in (None, ""):
                item["mark_price"] = p.get("markPrice") or p.get("mark") or p.get("mark_price")
            if item.get("current_price") in (None, ""):
                item["current_price"] = p.get("markPrice") or p.get("mark") or p.get("mark_price")
            if item.get("unrealized_pnl") in (None, ""):
                item["unrealized_pnl"] = p.get("unrealizedProfit") or p.get("unRealizedProfit") or p.get("pnl")
            if item.get("direction") in (None, "", "UNKNOWN"):
                amt = _coerce_float(p.get("positionAmt") or 0.0, 0.0)
                if amt > 0:
                    item["direction"] = "LONG"
                elif amt < 0:
                    item["direction"] = "SHORT"
            item["verified"] = True
            item["verified_source"] = "settings.positions_status"
        out.append(item)

    return out


def _schema_meta_value(schema: str, key: str) -> str | None:
    if not table_exists(schema, "schema_meta"):
        return None
    row = safe_execute(
        schema,
        "SELECT value FROM {schema}.schema_meta WHERE key = %s LIMIT 1",
        (str(key),),
        fetch="one",
        default=None,
    )
    if not row:
        return None
    val = (row or {}).get("value")
    if val is None:
        return None
    return str(val)


def build_system_health(schema: str, role: str) -> Dict[str, Any]:
    settings = fetch_settings(
        schema,
        [
            "last_heartbeat",
            "bot_heartbeat",
            "execution_monitor_heartbeat",
            "api_latency",
            "sys_cpu",
            "sys_ram",
            "kill_switch",
            "kill_switch_reason",
            "last_error",
        ],
    )

    hb_raw = settings.get("last_heartbeat") or settings.get("bot_heartbeat")
    hb_ms = _parse_ts_ms(hb_raw)
    exec_hb_raw = settings.get("execution_monitor_heartbeat")
    exec_hb_ms = _parse_ts_ms(exec_hb_raw)

    now = now_ms()
    last_seen = 999999
    online = False

    if hb_ms:
        last_seen = max(0, int((now - hb_ms) / 1000))
        online = last_seen < 60

    exec_age = 999999
    if exec_hb_ms:
        exec_age = max(0, int((now - exec_hb_ms) / 1000))

    if not online and exec_age < 60:
        online = True
        if last_seen == 999999 or exec_age < last_seen:
            last_seen = exec_age

    logs_count = 0
    if table_exists(schema, "logs"):
        row = safe_execute(schema, "SELECT COUNT(*) AS n FROM {schema}.logs", fetch="one", default={"n": 0})
        logs_count = _coerce_int((row or {}).get("n"), 0)

    size_row = safe_execute(
        schema,
        """
        SELECT COALESCE(
            SUM(pg_total_relation_size(quote_ident(schemaname)||'.'||quote_ident(tablename))),
            0
        ) AS bytes_sz
        FROM pg_tables
        WHERE schemaname = %s
        """,
        (schema,),
        fetch="one",
        default={"bytes_sz": 0},
    )
    db_size_mb = _coerce_float((size_row or {}).get("bytes_sz"), 0.0) / (1024 * 1024)

    out = {
        "ok": True,
        "role": str(role),
        "schema": schema,
        "backend": "postgres",
        "pg_schema": schema,
        "online": bool(online),
        "last_heartbeat": _ms_to_iso(hb_ms) if hb_ms else hb_raw,
        "last_seen_seconds": int(last_seen),
        "latency": _coerce_int(settings.get("api_latency"), 0),
        "schema_version": _schema_meta_value(schema, "mina_schema_version"),
        "ddl_version": _schema_meta_value(schema, "mina_ddl_version"),
        "cpu": _coerce_float(settings.get("sys_cpu"), 0.0),
        "ram": _coerce_float(settings.get("sys_ram"), 0.0),
        "db_size": f"{db_size_mb:.2f} MB",
        "error_count": int(logs_count),
        "kill_switch": str(settings.get("kill_switch") or "0"),
        "kill_switch_reason": str(settings.get("kill_switch_reason") or ""),
        "execmon_last_seen_seconds": int(exec_age),
        "last_error": settings.get("last_error"),
    }
    return out


def get_stats(schema: str) -> Dict[str, Any]:
    if not table_exists(schema, "trades"):
        return {"trades": 0, "wins": 0, "pnl": 0.0, "win_rate": 0.0, "open_positions": 0, "total_trades": 0}

    cols = table_columns(schema, "trades")
    pnl_col = "pnl" if "pnl" in cols else ("realized_pnl" if "realized_pnl" in cols else None)
    status_col = "status" if "status" in cols else None

    where_closed = "WHERE UPPER(COALESCE(status,''))='CLOSED'" if status_col else ""
    where_open = "WHERE UPPER(COALESCE(status,''))='OPEN'" if status_col else ""

    trades = 0
    wins = 0
    pnl = 0.0
    if pnl_col:
        row = safe_execute(
            schema,
            f"SELECT COUNT(*) AS trades, COALESCE(SUM(CASE WHEN {pnl_col} > 0 THEN 1 ELSE 0 END),0) AS wins, COALESCE(SUM({pnl_col}),0) AS pnl FROM {{schema}}.trades {where_closed}",
            fetch="one",
            default={"trades": 0, "wins": 0, "pnl": 0.0},
        )
        trades = _coerce_int((row or {}).get("trades"), 0)
        wins = _coerce_int((row or {}).get("wins"), 0)
        pnl = _coerce_float((row or {}).get("pnl"), 0.0)

    row_open = safe_execute(
        schema,
        f"SELECT COUNT(*) AS n FROM {{schema}}.trades {where_open}",
        fetch="one",
        default={"n": 0},
    )
    open_positions = _coerce_int((row_open or {}).get("n"), 0)

    win_rate = round((wins / trades * 100.0), 2) if trades > 0 else 0.0
    return {
        "trades": int(trades),
        "wins": int(wins),
        "pnl": round(float(pnl), 6),
        "win_rate": float(win_rate),
        "open_positions": int(open_positions),
        "total_trades": int(trades),
    }


def list_logs(schema: str, *, limit: int = 200) -> list[dict]:
    if not table_exists(schema, "logs"):
        return []
    cols = table_columns(schema, "logs")
    order_col = "created_at_ms" if "created_at_ms" in cols else ("timestamp_ms" if "timestamp_ms" in cols else ("id" if "id" in cols else None))

    query = "SELECT * FROM {schema}.logs"
    if order_col:
        query += f" ORDER BY {order_col} DESC"
    query += " LIMIT %s"
    rows = safe_execute(schema, query, (max(1, min(int(limit or 200), 2000)),), default=[])
    return [dict(r) for r in (rows or [])]


def snapshot(role: Role, *, signal_limit: int = 10, position_limit: int = 200) -> Dict[str, Any]:
    schema = role_to_schema(role)
    return {
        "schema_version": "v2",
        "role": role,
        "schema": schema,
        "system_health": build_system_health(schema, role),
        "stats": get_stats(schema),
        "positions": list_open_positions(schema, limit=position_limit),
        "signals": list_signals(schema, limit=signal_limit),
    }
