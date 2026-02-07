from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlparse


def _norm_dsn(dsn: str) -> str:
    s = str(dsn or "").strip()
    if s.startswith("postgresql+psycopg://"):
        return "postgresql://" + s[len("postgresql+psycopg://") :]
    if s.startswith("postgresql+psycopg2://"):
        return "postgresql://" + s[len("postgresql+psycopg2://") :]
    return s


def _dsn_info(dsn: str) -> tuple[str, str]:
    p = urlparse(_norm_dsn(dsn))
    db_name = (p.path or "").lstrip("/") or "trading"
    host = p.hostname or "localhost"
    return db_name, host


def register_service(
    service_name: str,
    *,
    role: Optional[str] = None,
    schema_name: Optional[str] = None,
    version: Optional[str] = None,
    git_sha: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort registration into gateway.service_registry."""
    dsn = (
        os.getenv("TRADING_PG_DSN")
        or os.getenv("MINA_PG_DSN")
        or ""
    ).strip()
    if not dsn:
        return
    if _norm_dsn(dsn).startswith("sqlite"):
        return

    try:
        import psycopg  # type: ignore
    except Exception:
        return

    db_name, host = _dsn_info(dsn)
    role_norm = (str(role or "").strip().lower() or None)
    schema_norm = str(schema_name or "").strip() or (f"mina_{role_norm}" if role_norm else None)
    payload = meta or {}

    ddl = """
    CREATE SCHEMA IF NOT EXISTS gateway;
    CREATE TABLE IF NOT EXISTS gateway.service_registry (
      id           BIGSERIAL PRIMARY KEY,
      service_name TEXT NOT NULL,
      role         TEXT,
      schema_name  TEXT,
      db_name      TEXT,
      db_host      TEXT,
      started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
      version      TEXT,
      git_sha      TEXT,
      meta         JSONB
    );
    CREATE INDEX IF NOT EXISTS idx_service_registry_service_time
      ON gateway.service_registry(service_name, started_at DESC);
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        with psycopg.connect(_norm_dsn(dsn), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
                cur.execute(
                    """
                    INSERT INTO gateway.service_registry
                    (service_name, role, schema_name, db_name, db_host, started_at, version, git_sha, meta)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        str(service_name).strip(),
                        role_norm,
                        schema_norm,
                        db_name,
                        host,
                        now,
                        version or os.getenv("BOT_VERSION") or "dev",
                        git_sha or os.getenv("GIT_SHA") or "",
                        json.dumps(payload, ensure_ascii=True),
                    ),
                )
    except Exception:
        # non-fatal by design
        return

