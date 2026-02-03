"""Best-effort Postgres mirroring for Mina_Bot.

Why this exists
--------------
We want a *safe* path to a unified Postgres DB without breaking what already
works. So Mina_Bot keeps using SQLite as its primary store, but (optionally)
mirrors key runtime data into Postgres so other services can read it efficiently.

Mirrored now:
  - settings (key/value)
  - logs (level/msg/source)
  - events (type + JSON payload)

Enable via environment:
  - TRADING_PG_DSN: e.g. postgresql://mina:PASS@127.0.0.1:5432/trading
  - TRADING_PG_MIRROR: 1/true to enable (default: off)
  - BOT_ROLE: live|paper|pump (stored as bot_role)

This module never raises to callers (best-effort). On failure it disables itself
for a short cooldown to avoid blocking the bot.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional


def _truthy(v: Optional[str]) -> bool:
    if v is None:
        return False
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


DDL = """
CREATE TABLE IF NOT EXISTS shared_settings (
  bot_role TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (bot_role, key)
);

CREATE TABLE IF NOT EXISTS shared_logs (
  id BIGSERIAL PRIMARY KEY,
  bot_role TEXT NOT NULL,
  level TEXT NOT NULL,
  msg TEXT NOT NULL,
  source TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at_ms BIGINT
);

CREATE TABLE IF NOT EXISTS shared_events (
  id BIGSERIAL PRIMARY KEY,
  bot_role TEXT NOT NULL,
  event_type TEXT NOT NULL,
  data JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


@dataclass
class PostgresMirror:
    dsn: str
    bot_role: str
    enabled: bool = True

    _ddl_done: bool = False
    _disabled_until: float = 0.0

    @classmethod
    def from_env(cls, bot_role: Optional[str] = None) -> Optional["PostgresMirror"]:
        dsn = os.getenv("TRADING_PG_DSN") or os.getenv("POSTGRES_DSN")
        if not dsn:
            return None
        if not _truthy(os.getenv("TRADING_PG_MIRROR")):
            return None
        role = bot_role or os.getenv("BOT_ROLE") or os.getenv("SERVICE_ROLE") or "unknown"
        return cls(dsn=dsn, bot_role=role)

    def _cooldown(self) -> bool:
        return time.time() < self._disabled_until

    def _disable_for(self, seconds: int = 30) -> None:
        self._disabled_until = time.time() + seconds

    def _connect(self):
        # Import lazily so Mina_Bot can run without psycopg installed.
        import psycopg  # type: ignore

        return psycopg.connect(self.dsn, autocommit=True)

    def _ensure_ddl(self) -> None:
        if self._ddl_done:
            return
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(DDL)
            self._ddl_done = True
        except Exception:
            # If DDL fails, disable briefly; don't spam.
            self._disable_for(60)

    def upsert_setting(self, key: str, value: Any) -> None:
        if not self.enabled or self._cooldown():
            return
        try:
            self._ensure_ddl()
            v = "" if value is None else str(value)
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO shared_settings (bot_role, key, value)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (bot_role, key)
                        DO UPDATE SET value = EXCLUDED.value, updated_at = now();
                        """,
                        (self.bot_role, key, v),
                    )
        except Exception:
            self._disable_for(30)

    def insert_log(self, level: str, msg: str, source: Optional[str] = None, created_at_ms: Optional[int] = None) -> None:
        if not self.enabled or self._cooldown():
            return
        try:
            self._ensure_ddl()
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO shared_logs (bot_role, level, msg, source, created_at_ms)
                        VALUES (%s, %s, %s, %s, %s);
                        """,
                        (self.bot_role, str(level), str(msg), source, created_at_ms),
                    )
        except Exception:
            self._disable_for(30)

    def insert_event(self, event_type: str, data: Any) -> None:
        if not self.enabled or self._cooldown():
            return
        try:
            self._ensure_ddl()
            payload = None
            try:
                payload = json.dumps(data, ensure_ascii=False)
            except Exception:
                payload = json.dumps({"repr": repr(data)})
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO shared_events (bot_role, event_type, data)
                        VALUES (%s, %s, %s::jsonb);
                        """,
                        (self.bot_role, str(event_type), payload),
                    )
        except Exception:
            self._disable_for(30)
