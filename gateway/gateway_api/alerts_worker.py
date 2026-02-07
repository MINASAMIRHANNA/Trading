from __future__ import annotations

import json
import os
import time
import hashlib
import datetime as dt
from typing import Any, Dict, List

import httpx
import psycopg
from psycopg.rows import dict_row

from gateway_api.crypto import decrypt_json


def _env(name: str, default: str | None = None) -> str:
    val = os.getenv(name)
    if val is None or str(val).strip() == "":
        return default if default is not None else ""
    return str(val)


def _normalize_dsn(dsn: str) -> str:
    s = str(dsn or "").strip()
    if s.startswith("postgresql+psycopg://"):
        s = "postgresql://" + s[len("postgresql+psycopg://") :]
    if s.startswith("postgresql+psycopg2://"):
        s = "postgresql://" + s[len("postgresql+psycopg2://") :]
    return s


EXPECTED_DSN = _normalize_dsn(
    _env("EXPECTED_TRADING_PG_DSN", "postgresql://trading:trading@postgres:5432/trading")
)
DSN = _normalize_dsn(_env("TRADING_PG_DSN"))
if not DSN:
    raise RuntimeError("TRADING_PG_DSN is required for gateway alerts worker.")
if DSN != EXPECTED_DSN:
    raise RuntimeError(f"TRADING_PG_DSN mismatch for alerts worker. expected={EXPECTED_DSN!r} got={DSN!r}")
MASTER_KEY = _env("TRADING_MASTER_KEY", "")
TICK_SEC = int(float(_env("ALERTS_TICK_SEC", "5")))


def _ensure_tables() -> None:
    ddl = """
    CREATE SCHEMA IF NOT EXISTS gateway;
    CREATE TABLE IF NOT EXISTS gateway.alert_settings (
      encrypted_json TEXT NOT NULL,
      updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS gateway.alert_rules (
      id          BIGSERIAL PRIMARY KEY,
      enabled     BOOLEAN NOT NULL DEFAULT TRUE,
      filters     JSONB,
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS gateway.alert_delivery_log (
      id          BIGSERIAL PRIMARY KEY,
      channel     TEXT NOT NULL,
      payload     JSONB,
      status      TEXT,
      error       TEXT,
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS shared_events (
      id           BIGSERIAL PRIMARY KEY,
      bot_role     TEXT NOT NULL,
      event_type   TEXT NOT NULL,
      data         JSONB,
      created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """
    with psycopg.connect(DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)


def _load_settings() -> Dict[str, Any]:
    _ensure_tables()
    with psycopg.connect(DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT encrypted_json FROM gateway.alert_settings ORDER BY updated_at DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return {}
            return decrypt_json(MASTER_KEY, row[0])


def _load_rules() -> List[Dict[str, Any]]:
    _ensure_tables()
    with psycopg.connect(DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM gateway.alert_rules WHERE enabled = TRUE ORDER BY id DESC")
            return list(cur.fetchall())


def _dedupe_exists(conn, h: str, window_s: int = 60) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM gateway.alert_delivery_log
            WHERE (payload->>'hash') = %s
              AND created_at > (now() - (%s || ' seconds')::interval)
            LIMIT 1
            """,
            (h, int(window_s)),
        )
        return cur.fetchone() is not None


def _log_delivery(conn, channel: str, payload: Dict[str, Any], status: str, error: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO gateway.alert_delivery_log(channel, payload, status, error) VALUES (%s, %s::jsonb, %s, %s)",
            (channel, json.dumps(payload), status, error),
        )


def _match_rule(rule: Dict[str, Any], event: Dict[str, Any]) -> bool:
    filters = rule.get("filters") or {}
    role = filters.get("role")
    if role and str(event.get("bot_role")) != str(role):
        return False
    types = filters.get("event_types")
    if isinstance(types, list) and types:
        if str(event.get("event_type")) not in types:
            return False
    return True


def _send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    httpx.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=8.0)


def main() -> None:
    _ensure_tables()
    last_id = 0
    while True:
        try:
            settings = _load_settings()
            token = str(settings.get("TELEGRAM_BOT_TOKEN") or settings.get("token") or "")
            chat_id = str(settings.get("TELEGRAM_CHAT_ID") or settings.get("chat_id") or "")
            if not token or not chat_id:
                time.sleep(max(2, TICK_SEC))
                continue

            rules = _load_rules()
            if not rules:
                time.sleep(max(2, TICK_SEC))
                continue

            with psycopg.connect(DSN, autocommit=True, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, bot_role, event_type, data, created_at FROM shared_events WHERE id > %s ORDER BY id ASC LIMIT 200",
                        (int(last_id),),
                    )
                    rows = list(cur.fetchall())
                for row in rows:
                    last_id = max(last_id, int(row.get("id") or 0))
                    for rule in rules:
                        if not _match_rule(rule, row):
                            continue
                        msg = f"🔔 {row.get('event_type')} ({row.get('bot_role')})"
                        h = hashlib.sha256(msg.encode("utf-8")).hexdigest()
                        if _dedupe_exists(conn, h):
                            continue
                        try:
                            _send_telegram(token, chat_id, msg)
                            _log_delivery(conn, "telegram", {"hash": h, "msg": msg}, "sent")
                        except Exception as e:
                            _log_delivery(conn, "telegram", {"hash": h, "msg": msg}, "error", str(e))
        except Exception:
            pass
        time.sleep(max(2, TICK_SEC))


if __name__ == "__main__":
    main()
