"""Mina_Bot DB package (canonical location).

This package hosts the Postgres compatibility layer and mirroring utilities.
Root-level modules (database.py/pg_compat.py/postgres_mirror.py) remain as
backward-compatible shims to avoid breaking existing imports.
"""

from .pg_compat import connect_postgres_compat, CompatConn, CompatCursor, HybridRow  # noqa: F401
from .postgres_mirror import PostgresMirror  # noqa: F401
from .database import DatabaseManager  # noqa: F401
from .ddl import ensure_signal_inbox_table, bootstrap_dashboard  # noqa: F401
from .bootstrap import bootstrap_from_env, bootstrap_for_role, BootstrapResult  # noqa: F401
from .repos.signal_inbox_repo import SignalInboxRepo  # noqa: F401
from .repos.commands_repo import CommandsRepo  # noqa: F401
from .repos.trades_repo import TradesRepo  # noqa: F401
from .repos.analytics_repo import AnalyticsRepo  # noqa: F401

from .repos.reports_repo import ReportsRepo  # noqa: F401

from .repos.settings_repo import SettingsRepo  # noqa: F401
