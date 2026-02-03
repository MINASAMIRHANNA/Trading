"""Backward-compatible shim.

Canonical implementation moved to:
    mina_core.db.postgres_mirror

This file remains to avoid breaking existing imports.
"""

from mina_core.db.postgres_mirror import *  # noqa: F401,F403
