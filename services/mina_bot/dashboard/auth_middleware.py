"""Authentication middleware for the Mina_Bot dashboard.

Extracted from dashboard.app to keep that file slimmer.

Behavior is intentionally unchanged.
"""

import os

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from dashboard.constants import PUBLIC_PATHS, SESSION_COOKIE_NAME, SESSION_COOKIE_VALUE, DASHBOARD_API_KEY_ENV, DASHBOARD_API_KEY_DEFAULT, DASHBOARD_API_KEY_HEADER


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # static + public endpoints
        if path.startswith("/static") or path in PUBLIC_PATHS:
            return await call_next(request)

        # API endpoints return JSON 401 if not authed
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        if session_token == SESSION_COOKIE_VALUE:
            return await call_next(request)

        # Optional API key for /api/* (useful for gateway/curl tests)
        expected_api_key = os.getenv(DASHBOARD_API_KEY_ENV, DASHBOARD_API_KEY_DEFAULT)
        provided_api_key = request.headers.get(DASHBOARD_API_KEY_HEADER)
        if path.startswith("/api") and provided_api_key and provided_api_key == expected_api_key:
            return await call_next(request)

        if path.startswith("/api"):
            return JSONResponse(status_code=401, content={"msg": "Unauthorized"})

        return RedirectResponse(url="/login")
