from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.router import api_router
from database.base import Base
from database.engine import ensure_schema, get_db_schema, get_engine
from database.migrations import ensure_trade_features_columns


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
