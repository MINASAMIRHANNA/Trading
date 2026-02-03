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


_DATASET_CACHE = None
_DATASET_CACHE_TS = 0.0


def _cache_ttl_seconds() -> int:
    raw = os.getenv("DATASET_CACHE_TTL_S", "30")
    try:
        return max(0, int(raw))
    except Exception:
        return 30


def _dataset_all_cached():
    """Cached full feature dataset with TTL (default 30s)."""
    global _DATASET_CACHE, _DATASET_CACHE_TS
    ttl = _cache_ttl_seconds()
    if ttl <= 0:
        return load_feature_dataset()
    now = time.time()
    if _DATASET_CACHE is None or (now - _DATASET_CACHE_TS) > ttl:
        _DATASET_CACHE = load_feature_dataset()
        _DATASET_CACHE_TS = now
    return _DATASET_CACHE


def get_dataset(symbol: Optional[str] = None):
    """Return the feature dataset, optionally filtered by symbol."""
    df = _dataset_all_cached()
    if symbol and hasattr(df, "columns") and "symbol" in df.columns:
        return df[df["symbol"] == symbol].copy()
    return df
