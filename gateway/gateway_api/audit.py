from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, Optional, List

import psycopg
from psycopg.rows import dict_row
from psycopg import errors as pg_errors


DEFAULT_DSN = "postgresql://trading:trading@postgres:5432/trading"
AUDIT_SCHEMA = "gateway"

# shared_events is in the public schema by default (see ops/postgres/schema.sql)
SHARED_EVENTS_TABLE = "shared_events"


def _normalize_dsn(dsn: str) -> str:
    """Normalize DSN for psycopg (driverless, no SQLAlchemy prefixes)."""
    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn[len("postgres://") :]
    if dsn.startswith("postgresql+psycopg://"):
        dsn = "postgresql://" + dsn[len("postgresql+psycopg://") :]
    if dsn.startswith("postgresql+psycopg2://"):
        dsn = "postgresql://" + dsn[len("postgresql+psycopg2://") :]
    return dsn


def get_dsn() -> str:
    raw = (os.getenv("TRADING_PG_DSN") or "").strip()
    if not raw:
        raise RuntimeError(
            "TRADING_PG_DSN is required for gateway runtime. "
            "Refusing to start with implicit/fallback DSN."
        )
    dsn = _normalize_dsn(raw)
    expected = _normalize_dsn(
        os.getenv("EXPECTED_TRADING_PG_DSN", DEFAULT_DSN)
    )
    if dsn != expected:
        raise RuntimeError(
            f"TRADING_PG_DSN mismatch. expected={expected!r} got={dsn!r}"
        )
    return dsn


def ensure_audit_schema_and_table(dsn: str) -> None:
    """Idempotent DDL bootstrap for gateway audit log."""
    ddl = f"""
    CREATE SCHEMA IF NOT EXISTS {AUDIT_SCHEMA};

    CREATE TABLE IF NOT EXISTS {AUDIT_SCHEMA}.audit_log (
      id            BIGSERIAL PRIMARY KEY,
      ts_utc         TIMESTAMPTZ NOT NULL DEFAULT now(),
      actor         TEXT NOT NULL DEFAULT 'unknown',
      action        TEXT NOT NULL,
      role          TEXT,
      target_id     TEXT,
      trace_id      TEXT,
      request_json  JSONB,
      response_json JSONB,
      ok            BOOLEAN NOT NULL DEFAULT FALSE
    );

    CREATE INDEX IF NOT EXISTS idx_gateway_audit_ts ON {AUDIT_SCHEMA}.audit_log(ts_utc DESC);
    CREATE INDEX IF NOT EXISTS idx_gateway_audit_role ON {AUDIT_SCHEMA}.audit_log(role);
    CREATE INDEX IF NOT EXISTS idx_gateway_audit_action ON {AUDIT_SCHEMA}.audit_log(action);
    """
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)


def _ensure_shared_events_table(cur) -> None:
    # Minimal shared_events DDL (safe/idempotent). Matches ops/postgres/schema.sql.
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SHARED_EVENTS_TABLE} (
          id           BIGSERIAL PRIMARY KEY,
          bot_role     TEXT NOT NULL,
          event_type   TEXT NOT NULL,
          data         JSONB,
          created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    cur.execute(
        f"CREATE INDEX IF NOT EXISTS idx_shared_events_role_time ON {SHARED_EVENTS_TABLE}(bot_role, created_at DESC)"
    )
    cur.execute(
        f"CREATE INDEX IF NOT EXISTS idx_shared_events_type_time ON {SHARED_EVENTS_TABLE}(event_type, created_at DESC)"
    )


def new_trace_id() -> str:
    return uuid.uuid4().hex


def _try_insert_shared_event(
    cur,
    *,
    bot_role: str,
    event_type: str,
    data: Dict[str, Any],
) -> Optional[int]:
    """Best-effort insert into shared_events. Never raises."""
    payload = json.dumps(data or {})
    try:
        cur.execute(
            f"""
            INSERT INTO {SHARED_EVENTS_TABLE} (bot_role, event_type, data)
            VALUES (%s, %s, %s::jsonb)
            RETURNING id
            """,
            (bot_role, event_type, payload),
        )
        row = cur.fetchone()
        return int(row[0]) if row else None
    except pg_errors.UndefinedTable:
        # Table missing -> create and retry once
        try:
            _ensure_shared_events_table(cur)
            cur.execute(
                f"""
                INSERT INTO {SHARED_EVENTS_TABLE} (bot_role, event_type, data)
                VALUES (%s, %s, %s::jsonb)
                RETURNING id
                """,
                (bot_role, event_type, payload),
            )
            row = cur.fetchone()
            return int(row[0]) if row else None
        except Exception:
            return None
    except Exception:
        return None


def insert_audit_event(
    dsn: str,
    *,
    actor: str,
    action: str,
    role: Optional[str],
    target_id: Optional[str],
    trace_id: str,
    request_json: Optional[Dict[str, Any]],
    response_json: Optional[Dict[str, Any]],
    ok: bool,
) -> int:
    q = f"""
    INSERT INTO {AUDIT_SCHEMA}.audit_log(actor, action, role, target_id, trace_id, request_json, response_json, ok)
    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
    RETURNING id
    """
    req_s = json.dumps(request_json or {})
    resp_s = json.dumps(response_json or {})
    bot_role = (role or "gateway").strip() or "gateway"

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(q, (actor, action, role, target_id, trace_id, req_s, resp_s, ok))
            row = cur.fetchone()
            audit_id = int(row[0]) if row else 0

            # Mirror audit -> shared_events (Phase 4). Best effort, never breaks API.
            _try_insert_shared_event(
                cur,
                bot_role=bot_role,
                event_type=str(action),
                data={
                    "schema_version": "v1",
                    "source": "gateway_audit",
                    "audit_id": audit_id,
                    "actor": actor,
                    "role": role,
                    "target_id": target_id,
                    "trace_id": trace_id,
                    "ok": bool(ok),
                    "request_json": request_json or {},
                    "response_json": response_json or {},
                },
            )

            return audit_id


def fetch_audit_events(dsn: str, limit: int = 200) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 200), 1000))
    q = f"""
    SELECT id, ts_utc, actor, action, role, target_id, trace_id, request_json, response_json, ok
    FROM {AUDIT_SCHEMA}.audit_log
    ORDER BY ts_utc DESC, id DESC
    LIMIT %s
    """
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(q, (limit,))
            return list(cur.fetchall())


def fetch_audit_event_by_id(dsn: str, audit_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a single audit event by id."""
    try:
        audit_id = int(audit_id)
    except Exception:
        return None
    q = f"""
    SELECT id, ts_utc, actor, action, role, target_id, trace_id, request_json, response_json, ok
    FROM {AUDIT_SCHEMA}.audit_log
    WHERE id = %s
    """
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(q, (audit_id,))
            row = cur.fetchone()
            return dict(row) if row else None
