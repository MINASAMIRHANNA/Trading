from __future__ import annotations

import datetime as dt
import json
import os
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import psycopg
from psycopg.rows import dict_row


ROLE_TO_SCHEMA = {
    "paper": "mina_paper",
    "live": "mina_live",
    "pump": "mina_pump",
}
HEARTBEAT_KEYS = (
    "last_heartbeat",
    "bot_heartbeat",
    "execution_monitor_heartbeat",
    "last_seen",
    "last_seen_at",
    "last_seen_ms",
    "engine_last_seen_ms",
)
ENGINE_NAME_KEYS = (
    "engine_id",
    "engine_name",
    "engine",
    "worker_id",
    "service_name",
)
OFFLINE_AFTER_SEC = int(os.getenv("OBSERVABILITY_OFFLINE_AFTER_SEC", "90"))


def _normalize_dsn(raw: str) -> str:
    txt = str(raw or "").strip()
    if txt.startswith("postgres://"):
        txt = "postgresql://" + txt[len("postgres://") :]
    if txt.startswith("postgresql+psycopg://"):
        txt = "postgresql://" + txt[len("postgresql+psycopg://") :]
    if txt.startswith("postgresql+psycopg2://"):
        txt = "postgresql://" + txt[len("postgresql+psycopg2://") :]
    return txt


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "y", "t"}


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


def _now_ms() -> int:
    return int(time.time() * 1000)


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ms_to_iso(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000.0, tz=dt.timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def _to_ms(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        if num <= 0:
            return None
        if num < 1e11:
            return int(num * 1000)
        return int(num)

    txt = str(value).strip()
    if not txt:
        return None
    if txt.isdigit():
        num = int(txt)
        if num <= 0:
            return None
        if num < 1e11:
            return num * 1000
        return num
    try:
        parsed = dt.datetime.fromisoformat(txt.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return int(parsed.timestamp() * 1000)
    except Exception:
        return None


def _table_exists(conn: psycopg.Connection, schema: str, table: str) -> bool:
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


def _table_columns(conn: psycopg.Connection, schema: str, table: str) -> set[str]:
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


def _fetch_settings(conn: psycopg.Connection, schema: str, keys: Iterable[str]) -> Dict[str, str]:
    if not _table_exists(conn, schema, "settings"):
        return {}
    cols = _table_columns(conn, schema, "settings")
    if "key" not in cols or "value" not in cols:
        return {}
    keys_list = [str(k) for k in keys if str(k).strip()]
    if not keys_list:
        return {}
    placeholders = ",".join(["%s"] * len(keys_list))
    with conn.cursor() as cur:
        cur.execute(f"SELECT key, value FROM {schema}.settings WHERE key IN ({placeholders})", keys_list)
        rows = cur.fetchall() or []
    out: Dict[str, str] = {}
    for row in rows:
        key = str((row or {}).get("key") or "").strip()
        if key:
            out[key] = str((row or {}).get("value") or "")
    return out


def _empty_item(role: str, schema: str) -> Dict[str, Any]:
    return {
        "role": role,
        "schema": schema,
        "engine": {
            "name": "",
            "online": False,
            "last_seen_seconds": None,
            "last_seen_at": None,
        },
        "kill_switch": {"on": False, "reason": ""},
        "live_gate": None,
        "last_claim": None,
        "last_trade": None,
    }


def _normalize_allowlist(value: Any) -> List[str]:
    raw = _safe_json_loads(value, None)
    if isinstance(raw, list):
        items = raw
    else:
        txt = str(value or "").strip()
        items = txt.split(",") if txt else []
    out: List[str] = []
    seen: set[str] = set()
    for item in items:
        sym = str(item or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


def _normalize_limits(value: Any) -> Dict[str, Any]:
    parsed = _safe_json_loads(value, {})
    if not isinstance(parsed, dict):
        parsed = {}
    return {
        "max_open_positions": max(0, _safe_int(parsed.get("max_open_positions"), 1)),
        "max_notional": max(0.0, _safe_float(parsed.get("max_notional"), 50.0)),
        "max_daily_loss": max(0.0, _safe_float(parsed.get("max_daily_loss"), 10.0)),
    }


def _last_claim(conn: psycopg.Connection, schema: str, errors: List[Dict[str, Any]], role: str) -> Optional[Dict[str, Any]]:
    if not _table_exists(conn, schema, "commands"):
        errors.append({"role": role, "schema": schema, "code": "commands_table_missing", "message": f"{schema}.commands missing"})
        return None
    cols = _table_columns(conn, schema, "commands")
    if "id" not in cols:
        errors.append({"role": role, "schema": schema, "code": "commands_id_missing", "message": f"{schema}.commands.id missing"})
        return None

    order_parts: List[str] = []
    if "claimed_at_ms" in cols:
        order_parts.append("CASE WHEN claimed_at_ms IS NULL THEN 1 ELSE 0 END")
        order_parts.append("claimed_at_ms DESC NULLS LAST")
    elif "claimed_at" in cols:
        order_parts.append("CASE WHEN claimed_at IS NULL THEN 1 ELSE 0 END")
        order_parts.append("claimed_at DESC NULLS LAST")
    if "created_at_ms" in cols:
        order_parts.append("created_at_ms DESC NULLS LAST")
    elif "created_at" in cols:
        order_parts.append("created_at DESC NULLS LAST")
    order_parts.append("id DESC")
    order_sql = ", ".join(order_parts)

    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {schema}.commands ORDER BY {order_sql} LIMIT 1")
        row = cur.fetchone() or {}
    if not row:
        return None

    claimed_at_ms = _to_ms(row.get("claimed_at_ms"))
    if claimed_at_ms is None:
        claimed_at_ms = _to_ms(row.get("claimed_at"))
    done_at_ms = _to_ms(row.get("done_at_ms"))
    if done_at_ms is None:
        done_at_ms = _to_ms(row.get("done_at"))
    if done_at_ms is None:
        done_at_ms = _to_ms(row.get("updated_at_ms"))

    return {
        "command_id": _safe_int(row.get("id"), 0) or None,
        "cmd": str(row.get("cmd") or ""),
        "status": str(row.get("status") or ""),
        "claimed_by": str(row.get("claimed_by") or ""),
        "claimed_at_ms": claimed_at_ms,
        "claimed_at": _ms_to_iso(claimed_at_ms),
        "done_at_ms": done_at_ms,
        "done_at": _ms_to_iso(done_at_ms),
        "attempt_count": _safe_int(row.get("attempt_count"), 0),
        "dead_lettered": bool(row.get("dead_lettered")) if row.get("dead_lettered") is not None else False,
        "last_error": str(row.get("last_error") or ""),
    }


def _last_trade(conn: psycopg.Connection, schema: str, errors: List[Dict[str, Any]], role: str) -> Optional[Dict[str, Any]]:
    if not _table_exists(conn, schema, "trades"):
        errors.append({"role": role, "schema": schema, "code": "trades_table_missing", "message": f"{schema}.trades missing"})
        return None
    cols = _table_columns(conn, schema, "trades")
    if "id" not in cols:
        errors.append({"role": role, "schema": schema, "code": "trades_id_missing", "message": f"{schema}.trades.id missing"})
        return None

    order_parts: List[str] = []
    if "timestamp_ms" in cols:
        order_parts.append("timestamp_ms DESC NULLS LAST")
    elif "created_at_ms" in cols:
        order_parts.append("created_at_ms DESC NULLS LAST")
    elif "timestamp" in cols:
        order_parts.append("timestamp DESC NULLS LAST")
    elif "created_at" in cols:
        order_parts.append("created_at DESC NULLS LAST")
    order_parts.append("id DESC")
    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {schema}.trades ORDER BY {', '.join(order_parts)} LIMIT 1")
        row = cur.fetchone() or {}
    if not row:
        return None

    ts_ms = _to_ms(row.get("timestamp_ms"))
    if ts_ms is None:
        ts_ms = _to_ms(row.get("created_at_ms"))
    if ts_ms is None:
        ts_ms = _to_ms(row.get("timestamp"))
    if ts_ms is None:
        ts_ms = _to_ms(row.get("created_at"))

    close_ms = _to_ms(row.get("close_timestamp_ms"))
    if close_ms is None:
        close_ms = _to_ms(row.get("closed_at_ms"))
    if close_ms is None:
        close_ms = _to_ms(row.get("closed_at"))

    symbol = str(row.get("symbol") or row.get("pair") or "")
    entry_price = _safe_float(row.get("entry_price"), _safe_float(row.get("price"), 0.0))
    close_price = _safe_float(row.get("close_price"), 0.0)

    return {
        "trade_id": _safe_int(row.get("id"), 0) or None,
        "symbol": symbol,
        "status": str(row.get("status") or ""),
        "entry_price": entry_price,
        "close_price": close_price if close_price > 0 else None,
        "timestamp_ms": ts_ms,
        "timestamp": _ms_to_iso(ts_ms),
        "close_timestamp_ms": close_ms,
        "close_timestamp": _ms_to_iso(close_ms),
    }


def _role_observability(
    conn: psycopg.Connection,
    *,
    role: str,
    schema: str,
    now_ms: int,
    offline_after_sec: int,
    errors: List[Dict[str, Any]],
) -> Dict[str, Any]:
    item = _empty_item(role, schema)
    settings_keys = [
        *HEARTBEAT_KEYS,
        *ENGINE_NAME_KEYS,
        "kill_switch",
        "kill_switch_reason",
        "live_gate_state",
        "live_testnet_only",
        "live_allow_real_execution",
        "live_symbol_allowlist",
        "live_limits",
    ]
    settings = _fetch_settings(conn, schema, settings_keys)

    last_claim = _last_claim(conn, schema, errors, role)
    last_trade = _last_trade(conn, schema, errors, role)

    heartbeat_ms_values: List[int] = []
    for key in HEARTBEAT_KEYS:
        ts_ms = _to_ms(settings.get(key))
        if ts_ms is not None:
            heartbeat_ms_values.append(ts_ms)
    if last_claim and last_claim.get("claimed_at_ms"):
        heartbeat_ms_values.append(_safe_int(last_claim.get("claimed_at_ms"), 0))

    heartbeat_ms = max(heartbeat_ms_values) if heartbeat_ms_values else None
    last_seen_seconds: Optional[int] = None
    online = False
    if heartbeat_ms is not None and heartbeat_ms > 0:
        last_seen_seconds = max(0, int((now_ms - heartbeat_ms) / 1000))
        online = bool(last_seen_seconds <= max(5, int(offline_after_sec)))

    engine_name = ""
    for key in ENGINE_NAME_KEYS:
        v = str(settings.get(key) or "").strip()
        if v:
            engine_name = v
            break
    if (not engine_name) and isinstance(last_claim, dict):
        engine_name = str(last_claim.get("claimed_by") or "").strip()

    item["engine"] = {
        "name": engine_name,
        "online": bool(online),
        "last_seen_seconds": last_seen_seconds,
        "last_seen_at": _ms_to_iso(heartbeat_ms),
    }
    item["kill_switch"] = {
        "on": _truthy(settings.get("kill_switch", "0")),
        "reason": str(settings.get("kill_switch_reason") or ""),
    }
    item["last_claim"] = last_claim
    item["last_trade"] = last_trade

    if role == "live":
        state = str(settings.get("live_gate_state") or "DISARMED").strip().upper()
        if state not in {"DISARMED", "ARMED", "CONFIRMED"}:
            state = "DISARMED"
        allowlist = _normalize_allowlist(settings.get("live_symbol_allowlist"))
        item["live_gate"] = {
            "state": state,
            "testnet_only": _truthy(settings.get("live_testnet_only", "1")),
            "allow_real_execution": _truthy(settings.get("live_allow_real_execution", "0")),
            "allowlist": allowlist,
            "allowlist_count": len(allowlist),
            "limits": _normalize_limits(settings.get("live_limits")),
        }
    else:
        item["live_gate"] = None

    return item


def build_unified_observability(
    dsn: str,
    roles: Optional[Iterable[str]] = None,
    *,
    offline_after_sec: int = OFFLINE_AFTER_SEC,
) -> Dict[str, Any]:
    wanted_roles = [str(r).strip().lower() for r in (roles or ROLE_TO_SCHEMA.keys()) if str(r).strip()]
    if not wanted_roles:
        wanted_roles = list(ROLE_TO_SCHEMA.keys())
    items: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    now_ms = _now_ms()
    generated_at = _utc_now_iso()
    dsn_norm = _normalize_dsn(dsn)

    try:
        with psycopg.connect(dsn_norm, autocommit=True, row_factory=dict_row) as conn:
            for role in wanted_roles:
                schema = ROLE_TO_SCHEMA.get(role, "")
                if not schema:
                    errors.append({"role": role, "schema": None, "code": "invalid_role", "message": f"unknown role: {role}"})
                    continue
                try:
                    item = _role_observability(
                        conn,
                        role=role,
                        schema=schema,
                        now_ms=now_ms,
                        offline_after_sec=offline_after_sec,
                        errors=errors,
                    )
                except Exception as exc:
                    item = _empty_item(role, schema)
                    errors.append(
                        {
                            "role": role,
                            "schema": schema,
                            "code": "role_read_error",
                            "message": f"{type(exc).__name__}: {exc}",
                        }
                    )
                items.append(item)
    except Exception as exc:
        for role in wanted_roles:
            schema = ROLE_TO_SCHEMA.get(role, "")
            if schema:
                items.append(_empty_item(role, schema))
        errors.append({"role": None, "schema": None, "code": "db_connect_error", "message": f"{type(exc).__name__}: {exc}"})

    return {
        "ok": True,
        "generated_at": generated_at,
        "items": items,
        "errors": errors,
    }

