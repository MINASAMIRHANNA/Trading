"""SQLAlchemy base for Brain DB models.

Key idea for the unified Postgres DB:
- Brain stores its own tables under a dedicated schema (default: 'brain').
- We *always* qualify tables with that schema by setting it on MetaData.

This avoids relying on Postgres search_path (which can differ between drivers,
worker vs API, etc.) and fixes errors like:
  relation "trade_features" does not exist
when the table actually lives at brain.trade_features.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import declarative_base

from database.engine import get_db_schema


def _default_schema() -> str | None:
    schema = (get_db_schema() or "").strip()
    if not schema or schema.lower() in {"public", "default"}:
        return None
    return schema


metadata = MetaData(schema=_default_schema())

# All models that don't explicitly override schema will inherit from metadata.
Base = declarative_base(metadata=metadata)
