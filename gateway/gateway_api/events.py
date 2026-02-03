from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import psycopg
from psycopg.rows import dict_row


DDL = """
CREATE TABLE IF NOT EXISTS shared_events (
  id BIGSERIAL PRIMARY KEY,
  bot_role TEXT NOT NULL,
  event_type TEXT NOT NULL,
  data JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_shared_events_role_time ON shared_events(bot_role, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shared_events_type_time ON shared_events(event_type, created_at DESC);
"""


def ensure_shared_events_table(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)


def insert_shared_event(
    dsn: str,
    *,
    bot_role: str,
    event_type: str,
    data: Dict[str, Any] | None = None,
) -> int:
    payload = json.dumps(data or {}, ensure_ascii=False)
    q = """
    INSERT INTO shared_events(bot_role, event_type, data)
    VALUES (%s, %s, %s::jsonb)
    RETURNING id
    """
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(q, (str(bot_role), str(event_type), payload))
            row = cur.fetchone()
            return int(row[0]) if row else 0


def fetch_shared_events(
    dsn: str,
    *,
    bot_role: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 200,
    since_id: int = 0,
    order: str = "desc",
) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 200), 1000))
    since_id = int(since_id or 0)
    order = (order or "desc").lower()
    if order not in ("asc", "desc"):
        order = "desc"

    where: list[str] = []
    params: list[Any] = []

    if bot_role:
        where.append("bot_role = %s")
        params.append(str(bot_role))
    if event_type:
        where.append("event_type = %s")
        params.append(str(event_type))
    if since_id > 0:
        where.append("id > %s")
        params.append(since_id)

    wsql = ("WHERE " + " AND ".join(where)) if where else ""

    # When streaming (since_id>0), callers usually want ascending.
    if since_id > 0 and order == "desc":
        order = "asc"

    q = f"""
    SELECT id, bot_role, event_type, data, created_at
    FROM shared_events
    {wsql}
    ORDER BY id {order}
    LIMIT %s
    """
    params.append(limit)

    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(q, tuple(params))
            return [dict(r) for r in cur.fetchall()]
