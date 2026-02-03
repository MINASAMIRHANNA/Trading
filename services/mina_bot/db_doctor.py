#!/usr/bin/env python3
"""Backward-compatible wrapper.

Canonical location:
  mina_core.db.tools.db_doctor

Usage unchanged:
  python db_doctor.py --db ./bot_data.db --out ./db_report
"""

from mina_core.db.tools.db_doctor import main


if __name__ == "__main__":
    raise SystemExit(main())
