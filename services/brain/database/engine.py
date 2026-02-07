import os
import re

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

_ALLOW_SQLITE_DEV = str(
    os.getenv("BRAIN_ALLOW_SQLITE_DEV")
    or os.getenv("ALLOW_SQLITE_DEV")
    or "0"
).strip().lower() in {"1", "true", "yes", "on"}

_EXPECTED_TRADING_PG_DSN = "postgresql://trading:trading@postgres:5432/trading"
_EXPECTED_TRADING_PG_DSN = str(
    os.getenv("EXPECTED_TRADING_PG_DSN") or _EXPECTED_TRADING_PG_DSN
).strip()


def _normalize_compare_dsn(url: str) -> str:
    s = str(url or "").strip()
    if s.startswith("postgres://"):
        s = "postgresql://" + s[len("postgres://") :]
    if s.startswith("postgresql+psycopg://"):
        s = "postgresql://" + s[len("postgresql+psycopg://") :]
    if s.startswith("postgresql+psycopg2://"):
        s = "postgresql://" + s[len("postgresql+psycopg2://") :]
    return s


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


def _require_single_db_runtime() -> str:
    if _ALLOW_SQLITE_DEV:
        # Explicit local-dev escape hatch.
        return os.getenv("DATABASE_URL", "sqlite:///./brain.db")

    trading_dsn = str(os.getenv("TRADING_PG_DSN") or "").strip()
    if not trading_dsn:
        raise RuntimeError(
            "TRADING_PG_DSN is required for Brain service startup "
            "(single-DB mode enforced)."
        )
    normalized_trading = _normalize_compare_dsn(trading_dsn)
    normalized_expected = _normalize_compare_dsn(_EXPECTED_TRADING_PG_DSN)
    if normalized_trading != normalized_expected:
        raise RuntimeError(
            f"TRADING_PG_DSN mismatch for Brain. expected={normalized_expected!r} got={normalized_trading!r}"
        )

    database_url = str(os.getenv("DATABASE_URL") or trading_dsn).strip()
    normalized_db = _normalize_compare_dsn(database_url)
    if normalized_db != normalized_expected:
        raise RuntimeError(
            f"DATABASE_URL mismatch for Brain. expected={normalized_expected!r} got={normalized_db!r}"
        )
    return database_url


_RAW_DATABASE_URL = _require_single_db_runtime()
DATABASE_URL = _normalize_db_url(_RAW_DATABASE_URL)

if DATABASE_URL.startswith("sqlite") and not _ALLOW_SQLITE_DEV:
    raise RuntimeError(
        "SQLite backend is disabled for Brain. Set DATABASE_URL to Postgres or set BRAIN_ALLOW_SQLITE_DEV=1 for local-only development."
    )


def get_db_schema() -> str:
    """Return default postgres schema for Brain.

    Kept for backward compatibility with earlier entrypoints.
    """

    schema = (os.getenv("DB_SCHEMA") or os.getenv("PG_SCHEMA") or "brain").strip() or "brain"
    if schema != "brain":
        raise RuntimeError(f"Invalid Brain schema {schema!r}. Expected 'brain'.")
    return schema


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
