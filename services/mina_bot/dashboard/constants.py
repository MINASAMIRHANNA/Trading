"""Dashboard constants.

Kept in a separate module to reduce the size/noise of dashboard.app.
"""

import os
import secrets

# Public paths that do not require authentication.
PUBLIC_PATHS = {
    "/login",
    "/health",
    "/healthz",
    "/api/healthz",
    "/api/db_ready",
    "/status",
    "/publish",
}

# Auth cookie used by the dashboard.
SESSION_COOKIE_NAME = "session_token"
# Prefer explicit secret, otherwise generate a per-process random token.
# This makes cookie forgery harder in dev/test environments.
_SESSION_SECRET = os.getenv("DASHBOARD_SESSION_SECRET")
if not _SESSION_SECRET:
    _SESSION_SECRET = secrets.token_urlsafe(32)
SESSION_COOKIE_VALUE = _SESSION_SECRET

# Optional API Key auth for /api/* requests (for curl/tests).
DASHBOARD_API_KEY_ENV = "DASHBOARD_API_KEY"
DASHBOARD_API_KEY_DEFAULT = "trading-dev"
DASHBOARD_API_KEY_HEADER = "X-API-Key"
