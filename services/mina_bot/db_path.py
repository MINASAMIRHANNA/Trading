"""Backward-compatible shim.

The canonical implementation moved to:
    mina_core.utils.db_path

This file remains to avoid breaking existing imports.
"""

from mina_core.utils.db_path import *  # noqa: F401,F403
