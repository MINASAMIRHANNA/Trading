"""Postgres compatibility layer for Mina_Bot.

This module provides a sqlite3-like connection/cursor API backed by psycopg (Postgres).
It is intentionally small and only translates the sqlite patterns used in Mina_Bot.

Why this exists:
  Mina_Bot's DB layer was written against sqlite3. To migrate quickly/safely to Postgres
  without rewriting every query, we translate SQL + return row objects that behave like
  sqlite3.Row (supports both integer and string indexing).

Env variables (typically set by ops/run_*stack.sh):
  - MINA_PG_DSN (default: postgresql:///trading)
  - MINA_PG_SCHEMA (default: mina_<BOT_ROLE>)
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, List, Optional, Sequence, Tuple


try:
    import psycopg
except Exception as e:  # pragma: no cover
    psycopg = None  # type: ignore
    _IMPORT_ERR = e


_RE_QMARK = re.compile(r"\?")


def _translate_sql(sql: str) -> str:
    """Translate a subset of sqlite SQL into Postgres-friendly SQL."""
    s = sql.strip()
    if not s:
        return sql

    # sqlite pragmas are ignored
    if s.upper().startswith("PRAGMA "):
        return "-- PRAGMA ignored"

    # BEGIN IMMEDIATE is sqlite-specific
    if s.upper().startswith("BEGIN IMMEDIATE"):
        return "BEGIN"

    # Placeholders: ? -> %s (psycopg)
    # NOTE: Mina_Bot doesn't use '?' inside string literals in SQL.
    s = s.replace("?", "%s")

    # DDL tweaks
    s = re.sub(
        r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT",
        "BIGSERIAL PRIMARY KEY",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"\bAUTOINCREMENT\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bREAL\b", "DOUBLE PRECISION", s, flags=re.IGNORECASE)
    s = re.sub(r"\bBLOB\b", "BYTEA", s, flags=re.IGNORECASE)
    # If a table uses DATETIME in sqlite, TIMESTAMPTZ is a good default.
    s = re.sub(r"\bDATETIME\b", "TIMESTAMPTZ", s, flags=re.IGNORECASE)

    # Use BIGINT for epoch millisecond columns to avoid int32 overflow
    s = re.sub(r"\b(\w+_ms)\b\s+INTEGER\b", r"\1 BIGINT", s, flags=re.IGNORECASE)

    # INSERT OR IGNORE -> INSERT ... ON CONFLICT DO NOTHING
    # Works in Postgres without specifying conflict target.
    if re.match(r"^INSERT\s+OR\s+IGNORE\s+INTO\s+", s, flags=re.IGNORECASE):
        s = re.sub(r"^INSERT\s+OR\s+IGNORE\s+INTO\s+", "INSERT INTO ", s, flags=re.IGNORECASE)
        if "ON CONFLICT" not in s.upper():
            s = s.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"

    # INSERT OR REPLACE is only used by Mina_Bot for settings.
    # Translate to upsert on (key).
    if re.match(r"^INSERT\s+OR\s+REPLACE\s+INTO\s+settings\s*\(", s, flags=re.IGNORECASE):
        s = re.sub(r"^INSERT\s+OR\s+REPLACE\s+INTO\s+", "INSERT INTO ", s, flags=re.IGNORECASE)
        # Ensure we don't append twice
        if "ON CONFLICT" not in s.upper():
            s = (
                s.rstrip().rstrip(";")
                + " ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at"
            )

    return s


@dataclass
class HybridRow:
    """Row object compatible with sqlite3.Row usage patterns."""

    values: Tuple[Any, ...]
    columns: Tuple[str, ...]

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self.values[key]
        if isinstance(key, str):
            try:
                idx = self.columns.index(key)
            except ValueError:
                # sqlite3.Row raises IndexError for missing keys
                raise IndexError(key)
            return self.values[idx]
        raise TypeError("Invalid key type")

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except Exception:
            return default

    def keys(self) -> List[str]:
        return list(self.columns)

    def __iter__(self):
        return iter(self.values)


class CompatCursor:
    def __init__(self, cur: "psycopg.Cursor"):
        self._cur = cur
        self.lastrowid: Optional[int] = None

    @property
    def rowcount(self) -> int:
        try:
            return int(self._cur.rowcount or 0)
        except Exception:
            return 0

    @property
    def description(self):
        return self._cur.description

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None):
        sql2 = _translate_sql(sql)
        if sql2.strip().startswith("-- PRAGMA ignored"):
            return self
        # psycopg (Postgres) will mark the current transaction as "aborted" after
        # a failed statement. If we don't rollback, every subsequent statement will
        # raise InFailedSqlTransaction. sqlite3 doesn't behave like this, so we
        # emulate sqlite's "keep going" behaviour by rolling back on errors.
        try:
            self._cur.execute(sql2, params or ())
        except Exception:
            try:
                # psycopg.Cursor exposes .connection
                self._cur.connection.rollback()  # type: ignore[attr-defined]
            except Exception:
                pass
            raise

        # Emulate sqlite3 cursor.lastrowid for INSERTs.
        # NOTE: lastval() fails (and aborts the transaction) when no sequence
        # has been used. Use a savepoint so failures don't poison the tx.
        self.lastrowid = None
        if sql2.lstrip().upper().startswith("INSERT") and "RETURNING" not in sql2.upper():
            try:
                self._cur.execute("SAVEPOINT lastrowid")
                try:
                    # lastval() returns the last sequence value obtained in this session.
                    self._cur.execute("SELECT lastval()")
                    v = self._cur.fetchone()
                    if v and v[0] is not None:
                        self.lastrowid = int(v[0])
                finally:
                    try:
                        self._cur.execute("RELEASE SAVEPOINT lastrowid")
                    except Exception:
                        # If release fails, rollback the savepoint to clear errors.
                        try:
                            self._cur.execute("ROLLBACK TO SAVEPOINT lastrowid")
                            self._cur.execute("RELEASE SAVEPOINT lastrowid")
                        except Exception:
                            pass
            except Exception:
                self.lastrowid = None
        return self

    def executemany(self, sql: str, seq_of_params: Iterable[Sequence[Any]]):
        sql2 = _translate_sql(sql)
        if sql2.strip().startswith("-- PRAGMA ignored"):
            return self
        try:
            self._cur.executemany(sql2, seq_of_params)
        except Exception:
            try:
                self._cur.connection.rollback()  # type: ignore[attr-defined]
            except Exception:
                pass
            raise
        return self

    def fetchone(self) -> Optional[HybridRow]:
        row = self._cur.fetchone()
        if row is None:
            return None
        cols = tuple(d.name for d in (self._cur.description or []))
        return HybridRow(tuple(row), cols)

    def fetchall(self) -> List[HybridRow]:
        rows = self._cur.fetchall() or []
        cols = tuple(d.name for d in (self._cur.description or []))
        return [HybridRow(tuple(r), cols) for r in rows]

    def close(self):
        try:
            self._cur.close()
        except Exception:
            pass


class CompatConn:
    def __init__(self, conn: "psycopg.Connection", schema: str):
        self._conn = conn
        self.schema = schema
        # sqlite3 compatibility attribute (DatabaseManager sets conn.row_factory)
        self.row_factory = None

    def cursor(self) -> CompatCursor:
        return CompatCursor(self._conn.cursor())

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> CompatCursor:
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass


def connect_postgres_compat(dsn: str, schema: str) -> CompatConn:
    if psycopg is None:  # pragma: no cover
        raise RuntimeError(f"psycopg is required for Postgres backend: {_IMPORT_ERR}")

    # Use local unix socket by default (postgresql:///trading), works with peer auth.
    conn = psycopg.connect(dsn)
    c = conn.cursor()
    # Ensure schema exists and set search_path
    c.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    c.execute(f'SET search_path TO "{schema}", public')
    conn.commit()
    return CompatConn(conn, schema)
