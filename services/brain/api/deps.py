"""FastAPI dependencies for Brain API.

This module centralizes:
- SQLAlchemy session wiring for the Brain *internal* database
  (defaults to sqlite in docker-compose)
- Feature dataset loading (cached) with optional symbol filtering

Notes:
- Mina trade ingestion uses TRADING_PG_DSN inside the ingestion layer.
  The Brain API itself should use the same DB wiring as `database.session`
  so sync-state + features stay consistent.
"""

from __future__ import annotations

import os
import time
from functools import lru_cache
from typing import Generator, Optional

from sqlalchemy.orm import Session

from database.session import SessionLocal
from learning.datasets import load_feature_dataset


def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session for request-scoped DB access."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _cache_ttl_seconds() -> int:
    raw = os.getenv("DATASET_CACHE_TTL_S", "30")
    try:
        return max(0, int(raw))
    except Exception:
        return 30


def _dataset_cache_bucket() -> int:
    ttl = _cache_ttl_seconds()
    if ttl <= 0:
        return 0
    return int(time.time() // ttl)


@lru_cache(maxsize=4)
def _dataset_all_cached(bucket: int):
    """Cached full feature dataset (TTL bucketed + clearable)."""
    _ = bucket
    return load_feature_dataset()


def get_dataset(symbol: Optional[str] = None):
    """Return the feature dataset, optionally filtered by symbol."""
    df = _dataset_all_cached(_dataset_cache_bucket())
    if symbol and hasattr(df, "columns") and "symbol" in df.columns:
        return df[df["symbol"] == symbol].copy()
    return df


def clear_dataset_cache() -> None:
    _dataset_all_cached.cache_clear()


# Backward-compatible cache clear hook used by admin/sync endpoints.
get_dataset.cache_clear = clear_dataset_cache  # type: ignore[attr-defined]
