import os
import re

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

# Default to SQLite for local development
_RAW_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./trading_intelligence.db")


def _normalize_db_url(url: str) -> str:
    """Normalize DB URLs for the Brain service.

    - Convert deprecated 'postgres://' URLs to 'postgresql://'
    - If a postgres URL does not specify a driver, prefer psycopg (v3)
      because Brain ships with psycopg[binary].
    """

    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]

    if url.startswith("postgresql://") and "+psycopg" not in url and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    return url


DATABASE_URL = _normalize_db_url(_RAW_DATABASE_URL)


def get_db_schema() -> str:
    """Return default postgres schema for Brain.

    Kept for backward compatibility with earlier entrypoints.
    """

    schema = os.getenv("DB_SCHEMA") or os.getenv("PG_SCHEMA") or "brain"
    schema = schema.strip()
    return schema or "brain"


def _valid_schema_name(schema: str) -> bool:
    # 63 char max in Postgres (we use 63 incl first char)
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$", schema))


def get_engine(echo: bool = False, *, schema: str | None = None) -> Engine:
    """Create SQLAlchemy engine for Brain."""

    connect_args: dict = {}
    engine_execution_options: dict | None = None

    if DATABASE_URL.startswith("sqlite"):
        connect_args = {"check_same_thread": False}

    # For Postgres, enforce the target schema via BOTH:
    # 1) connection option (strong)
    # 2) schema_translate_map (prevents schema-less ORM queries from hitting public)
    if DATABASE_URL.startswith("postgresql"):
        target = (schema or get_db_schema()).strip()
        if not _valid_schema_name(target):
            raise ValueError(f"Invalid schema name: {target!r}")
        # Use a strict search_path (no public) to avoid accidental cross-schema access.
        connect_args = {"options": f"-csearch_path={target}"}
        engine_execution_options = {"schema_translate_map": {None: target}}

    engine = create_engine(
        DATABASE_URL,
        echo=echo,
        connect_args=connect_args,
        pool_pre_ping=True,
        execution_options=engine_execution_options or {},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        if DATABASE_URL.startswith("sqlite"):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    # Keep a best-effort SET search_path on connect (useful for drivers that ignore "options").
    if DATABASE_URL.startswith("postgresql"):
        target = (schema or get_db_schema()).strip()

        @event.listens_for(engine, "connect")
        def _set_search_path(dbapi_connection, _connection_record):
            try:
                cursor = dbapi_connection.cursor()
                cursor.execute(f'SET search_path TO "{target}"')
                cursor.close()
            except Exception:
                pass

    return engine


def ensure_schema(engine: Engine | str | None = None, schema: str | None = None) -> str:
    """Ensure a postgres schema exists.

    Backward-compatible helper: some entrypoints call ensure_schema() with:
    - ensure_schema()
    - ensure_schema("brain")
    - ensure_schema(engine)
    - ensure_schema(engine, "brain")
    """

    if isinstance(engine, str) and schema is None:
        schema = engine
        engine = None

    schema = (schema or get_db_schema()).strip()
    if not _valid_schema_name(schema):
        raise ValueError(f"Invalid schema name: {schema!r}")

    eng = engine or get_engine(schema=schema)

    if DATABASE_URL.startswith("postgresql"):
        with eng.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))

    return schema
