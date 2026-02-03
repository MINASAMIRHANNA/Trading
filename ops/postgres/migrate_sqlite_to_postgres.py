#!/usr/bin/env python3
"""Migrate a Mina_Bot SQLite DB into Postgres (schema-per-mode).

Safe-by-default workflow:
  1) Stop Mina services
  2) Run this script to copy data from SQLite -> Postgres schema
  3) Start Mina services (now using Postgres as primary)

This script can be run multiple times. Use --drop-schema to reset a schema.

Examples:
  python3 ops/postgres/migrate_sqlite_to_postgres.py --sqlite services/mina_bot/bot_data_live.db --schema mina_live

Requirements: psycopg (psycopg3) must be installed in the active venv.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any, Iterable

import psycopg


def _list_sqlite_tables(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [r[0] for r in cur.fetchall()]


def _sqlite_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return [r[1] for r in cur.fetchall()]


def _chunked(iterable: Iterable[Any], size: int) -> Iterable[list[Any]]:
    buf: list[Any] = []
    for x in iterable:
        buf.append(x)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", required=True, help="Path to SQLite DB file")
    ap.add_argument("--dsn", default="postgresql:///trading", help="Postgres DSN (default: local socket)")
    ap.add_argument("--schema", required=True, help="Target Postgres schema (e.g. mina_live)")
    ap.add_argument("--drop-schema", action="store_true", help="Drop & recreate schema before migrating")
    ap.add_argument("--batch", type=int, default=500, help="Insert batch size")
    args = ap.parse_args()

    sqlite_path = Path(args.sqlite).expanduser().resolve()
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite file not found: {sqlite_path}")

    # SQLite
    sconn = sqlite3.connect(str(sqlite_path))
    sconn.row_factory = sqlite3.Row

    # Postgres
    pconn = psycopg.connect(args.dsn)
    pconn.autocommit = False

    with pconn.cursor() as cur:
        if args.drop_schema:
            cur.execute(f'DROP SCHEMA IF EXISTS "{args.schema}" CASCADE')
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{args.schema}"')
        cur.execute(f'SET search_path TO "{args.schema}", public')
    pconn.commit()

    # Ensure Mina tables exist (reuse Mina_Bot DB schema by importing DB manager)
    # We invoke the table-creator inside Mina_Bot to guarantee compatibility.
    import os
    import sys

    # Make repo root importable when running from monorepo root.
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    # Configure Mina_Bot DB to Postgres primary just for schema creation.
    os.environ["MINA_DB_BACKEND"] = "postgres"
    os.environ["MINA_PG_DSN"] = args.dsn
    os.environ["MINA_PG_SCHEMA"] = args.schema

    from services.mina_bot.database import DatabaseManager  # noqa: E402

    db = DatabaseManager(db_file=str(sqlite_path))
    # force schema creation
    db.create_tables()
    try:
        db.close()
    except Exception:
        pass

    tables = _list_sqlite_tables(sconn)
    print(f"[MIGRATE] {sqlite_path.name} -> {args.dsn} schema={args.schema}")
    print(f"[MIGRATE] tables: {len(tables)}")

    with pconn.cursor() as pcur:
        pcur.execute(f'SET search_path TO "{args.schema}", public')

        for t in tables:
            cols = _sqlite_columns(sconn, t)
            if not cols:
                continue
            print(f"[MIGRATE] table {t} ({len(cols)} cols) ...", flush=True)

            scol = ",".join([f'"{c}"' for c in cols])
            placeholders = ",".join(["%s"] * len(cols))
            ins = f'INSERT INTO "{t}" ({scol}) VALUES ({placeholders})'

            srows = sconn.execute(f'SELECT {scol} FROM "{t}"').fetchall()
            if not srows:
                continue
            for chunk in _chunked(srows, args.batch):
                vals = [tuple(r[c] for c in cols) for r in chunk]
                pcur.executemany(ins, vals)

            # If table has an 'id' column, align its sequence.
            if "id" in cols:
                # Align SERIAL sequence with imported explicit ids.
                try:
                    pcur.execute(
                        f"SELECT setval(pg_get_serial_sequence('{args.schema}.{t}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM \"{t}\"), 0), true)"
                    )
                except Exception:
                    pass

        pconn.commit()

    print("[MIGRATE] done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
