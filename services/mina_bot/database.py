"""Backward-compatible shim.

Canonical implementation moved to:
    mina_core.db.database

This file remains to avoid breaking existing imports.
"""

from mina_core.db.database import *  # noqa: F401,F403
