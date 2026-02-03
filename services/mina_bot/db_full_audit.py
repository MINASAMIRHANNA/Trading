#!/usr/bin/env python3
"""Backward-compatible wrapper.

Canonical location:
  mina_core.db.tools.db_full_audit

Usage unchanged:
  python db_full_audit.py --db ./bot_data.db --out ./db_audit_out
"""

from mina_core.db.tools.db_full_audit import main


if __name__ == "__main__":
    main()
