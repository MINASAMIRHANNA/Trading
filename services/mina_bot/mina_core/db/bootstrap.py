"""Bootstrap helpers for Mina_Bot databases.

This module provides a single place to "initialize" the DB schema for a given
role/backend. It intentionally uses the existing DatabaseManager so we don't
duplicate core table definitions.

Batch-4 goal: provide a stable entry point used by scripts and future services.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class BootstrapResult:
    backend: str
    db_id: str
    pg_dsn: Optional[str] = None
    pg_schema: Optional[str] = None


def bootstrap_from_env(db_file: str | None = None) -> BootstrapResult:
    """Bootstrap the database based on environment variables.

    Respects MINA_DB_BACKEND/TRADING_DB_BACKEND and Postgres DSN/schema envs.
    Returns a small summary for logs/health.
    """
    # Import locally to avoid any early import side effects.
    from mina_core.db.database import DatabaseManager

    db = DatabaseManager(db_file=db_file)

    # Ensure dashboard tables (kept separate so dashboards can call it too)
    try:
        from mina_core.db.ddl import bootstrap_dashboard

        bootstrap_dashboard(db.conn, lock=getattr(db, "lock", None))
    except Exception:
        pass

    backend = "postgres" if getattr(db, "is_postgres", False) else "sqlite"
    return BootstrapResult(
        backend=backend,
        db_id=str(getattr(db, "db_file", "")),
        pg_dsn=getattr(db, "pg_dsn", None),
        pg_schema=getattr(db, "pg_schema", None),
    )


def bootstrap_for_role(role: str, dsn: str | None = None, schema: str | None = None) -> BootstrapResult:
    """Bootstrap Postgres schema for a specific bot role.

    This is useful for ops to pre-create schemas before starting services.
    """
    role = (role or "").strip().lower()
    if role == "arena":
        role = "paper"

    os.environ["BOT_ROLE"] = role
    os.environ["MINA_DB_BACKEND"] = "postgres"

    if dsn:
        os.environ["MINA_PG_DSN"] = dsn
    if schema:
        os.environ["MINA_PG_SCHEMA"] = schema
    else:
        os.environ["MINA_PG_SCHEMA"] = f"mina_{role}"

    return bootstrap_from_env()


def bootstrap_all_from_env(db_file: str | None = None) -> BootstrapResult:
    """Bootstrap full shared schema (core + learning + dashboard inbox) using env."""
    # uses the same path as bootstrap_from_env (kept for explicit naming)
    return bootstrap_from_env(db_file=db_file)
