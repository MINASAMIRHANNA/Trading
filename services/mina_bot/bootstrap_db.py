"""Bootstrap Mina_Bot DB (SQLite or Postgres PRIMARY).

Usage
-----
# Use current env (recommended in Docker)
python bootstrap_db.py

# Bootstrap a role explicitly (Postgres)
python bootstrap_db.py --role paper --dsn postgresql://trading:trading@localhost:5432/trading

Notes
-----
- This script is safe to run multiple times (idempotent).
- It uses DatabaseManager (existing DDL) and then ensures dashboard tables.
"""

from __future__ import annotations

import argparse
import json


def main() -> int:
    p = argparse.ArgumentParser(description="Bootstrap Mina_Bot DB schema")
    p.add_argument("--role", default=None, help="Bot role to bootstrap (paper/live/pump)")
    p.add_argument("--dsn", default=None, help="Postgres DSN (optional)")
    p.add_argument("--schema", default=None, help="Postgres schema (optional)")
    p.add_argument("--db-file", default=None, help="SQLite DB file override (optional)")
    args = p.parse_args()

    try:
        if args.role:
            from mina_core.db.bootstrap import bootstrap_for_role

            res = bootstrap_for_role(args.role, dsn=args.dsn, schema=args.schema)
        else:
            from mina_core.db.bootstrap import bootstrap_from_env

            res = bootstrap_from_env(db_file=args.db_file)

        print(json.dumps(res.__dict__, ensure_ascii=False))
        return 0
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
