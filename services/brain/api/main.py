import os
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.router import api_router
from database.base import Base
from database.engine import ensure_schema, get_db_schema, get_engine
from database.migrations import ensure_trade_features_columns
from database.service_registry import register_service


def bootstrap_db() -> None:
    """Create/upgrade DB objects for the Brain service.

    - On SQLite: creates the local file tables.
    - On Postgres: ensures the configured schema exists, then creates tables there.

    This keeps Brain fully self-contained and enables the unified Postgres DB setup.
    """
    engine = get_engine(echo=False)
    schema = get_db_schema()
    ensure_schema(engine, schema)
    Base.metadata.create_all(engine)
    ensure_trade_features_columns(engine, schema)


bootstrap_db()
try:
    register_service(
        "brain_api",
        schema_name=get_db_schema(),
        meta={"component": "api"},
    )
except Exception:
    pass

app = FastAPI(title="Trading Intelligence & Research Platform")

# Adjust CORS to allow the React frontend to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "brain_api"}


@app.get("/healthz")
def healthz_check():
    return health_check()


def _normalize_dsn(dsn: str) -> str:
    s = str(dsn or "").strip()
    if s.startswith("postgresql+psycopg://"):
        return "postgresql://" + s[len("postgresql+psycopg://") :]
    if s.startswith("postgresql+psycopg2://"):
        return "postgresql://" + s[len("postgresql+psycopg2://") :]
    return s


@app.get("/api/meta/datasource")
def datasource_meta():
    raw_dsn = (
        os.getenv("TRADING_PG_DSN")
        or os.getenv("BRAIN_DB_DSN")
        or os.getenv("DATABASE_URL")
        or ""
    ).strip()
    dsn = _normalize_dsn(raw_dsn)
    backend = "postgres" if dsn.startswith("postgresql://") else ("sqlite" if dsn.startswith("sqlite") else "unknown")
    parsed = urlparse(dsn) if dsn else None
    return {
        "status": "ok",
        "service": "brain_api",
        "backend": backend,
        "dsn_host": (parsed.hostname if parsed else None) or "localhost",
        "db_name": ((parsed.path or "").lstrip("/") if parsed else "") or "trading",
        "schema": os.getenv("DB_SCHEMA") or os.getenv("PG_SCHEMA") or get_db_schema(),
        "version": os.getenv("BRAIN_VERSION") or "dev",
    }
