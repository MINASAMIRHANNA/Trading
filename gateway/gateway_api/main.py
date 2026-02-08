from __future__ import annotations

import os
import json
import asyncio
import uuid
import time
import math
import hmac
import hashlib
import csv
import io
import datetime as dt
from pathlib import Path
from urllib.parse import urlencode, urlparse

from typing import Literal, Optional, Dict, Any

import httpx
import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, HTTPException, Request, Response, Query
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from gateway_api.contracts_v1 import json_schema as contracts_v1_schema
from gateway_api import mina_pg

from gateway_api.audit import ensure_audit_schema_and_table, get_dsn as _audit_get_dsn, insert_audit_event, new_trace_id, fetch_audit_events, fetch_audit_event_by_id
from gateway_api.crypto import encrypt_json, decrypt_json, hash_secret


Role = Literal["paper", "live", "pump"]

def _actor_from_request(request: Request) -> str:
    return (
        request.headers.get("X-Actor")
        or request.headers.get("X-User")
        or request.headers.get("X-Forwarded-User")
        or "ui"
    )

def _trace_id_from_request(request: Request) -> str:
    return request.headers.get("X-Trace-Id") or new_trace_id()


def _json_loads_safe(raw: str) -> Any:
    txt = str(raw or "").strip()
    if not txt:
        return {}
    try:
        return json.loads(txt)
    except Exception:
        return {"raw": _clip_text(txt, 2000)}


def _ui_action_role(path: str, body: Dict[str, Any], query: Dict[str, Any]) -> str | None:
    p = str(path or "").strip().lower()
    for role_name in ("paper", "live", "pump"):
        if f"/{role_name}/" in p or p.endswith(f"/{role_name}"):
            return role_name
    role = str((body or {}).get("role") or (query or {}).get("role") or "").strip().lower()
    if role in {"paper", "live", "pump"}:
        return role
    return None


def _insert_ui_action(
    *,
    trace_id: str,
    actor: str,
    page: str,
    button_id: str,
    method: str,
    path: str,
    role: str | None,
    request_json: Dict[str, Any],
    result_json: Dict[str, Any],
    status_code: int,
) -> None:
    _ensure_gateway_phase4_tables(AUDIT_DSN)
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO gateway.ui_actions
                (trace_id, actor, page, button_id, method, path, role, request_json, result_json, status_code)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                """,
                (
                    str(trace_id or "").strip() or None,
                    str(actor or "").strip() or "ui",
                    str(page or "").strip() or None,
                    str(button_id or "").strip() or None,
                    str(method or "").strip().upper(),
                    str(path or "").strip(),
                    str(role or "").strip() or None,
                    json.dumps(request_json or {}, ensure_ascii=True),
                    json.dumps(result_json or {}, ensure_ascii=True),
                    int(status_code or 0),
                ),
            )

async def _audit_write(
    *,
    request: Request,
    action: str,
    role: Optional[str],
    target_id: Optional[str],
    trace_id: str,
    request_json: Optional[Dict[str, Any]],
    response_json: Optional[Dict[str, Any]],
    ok: bool,
) -> int:
    if not AUDIT_ENABLED:
        return 0
    actor = _actor_from_request(request)
    try:
        return await asyncio.to_thread(
            insert_audit_event,
            AUDIT_DSN,
            actor=actor,
            action=action,
            role=role,
            target_id=target_id,
            trace_id=trace_id,
            request_json=request_json,
            response_json=response_json,
            ok=ok,
        )
    except Exception as e:
        # Non-fatal
        print(f"⚠️ [gateway] audit insert failed: {e}")
        return 0

async def _audited_post_json(
    *,
    request: Request,
    action: str,
    role: Optional[str],
    target_id: Optional[str],
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
):
    trace_id = _trace_id_from_request(request)

    # Always forward trace_id to downstream so dashboards/bots can persist/link it.
    try:
        headers = dict(headers or {})
    except Exception:
        headers = {}
    headers.setdefault("X-Trace-Id", trace_id)

    # Also include trace_id in JSON body when it is a dict.
    try:
        if isinstance(json_body, dict) and "trace_id" not in json_body:
            json_body = {**json_body, "trace_id": trace_id}
    except Exception:
        pass
    audit_id = 0
    try:
        result = await _post_json(url, headers=headers, json_body=json_body, params=params)
        audit_id = await _audit_write(
            request=request,
            action=action,
            role=role,
            target_id=target_id,
            trace_id=trace_id,
            request_json=json_body,
            response_json=result if isinstance(result, dict) else {"result": result},
            ok=True,
        )
        if isinstance(result, dict):
            result = {**result, "trace_id": trace_id, "audit_id": audit_id}
        return result
    except HTTPException as e:
        await _audit_write(
            request=request,
            action=action,
            role=role,
            target_id=target_id,
            trace_id=trace_id,
            request_json=json_body,
            response_json={"error": e.detail},
            ok=False,
        )
        raise


async def _audited_post_params(
    *,
    request: Request,
    action: str,
    role: Optional[str],
    target_id: Optional[str],
    url: str,
    params: Optional[Dict[str, Any]] = None,
):
    trace_id = _trace_id_from_request(request)
    headers = {"X-Trace-Id": trace_id}
    req_json = {"params": params or {}}
    try:
        result = await _post_json(url, headers=headers, params=params)
        audit_id = await _audit_write(
            request=request,
            action=action,
            role=role,
            target_id=target_id,
            trace_id=trace_id,
            request_json=req_json,
            response_json=result if isinstance(result, dict) else {"result": result},
            ok=True,
        )
        if isinstance(result, dict):
            result = {**result, "trace_id": trace_id, "audit_id": audit_id}
        return result
    except HTTPException as e:
        await _audit_write(
            request=request,
            action=action,
            role=role,
            target_id=target_id,
            trace_id=trace_id,
            request_json=req_json,
            response_json={"error": e.detail},
            ok=False,
        )
        raise


async def _audited_get_json(
    *,
    request: Request,
    action: str,
    role: Optional[str],
    target_id: Optional[str],
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
):
    trace_id = _trace_id_from_request(request)
    try:
        headers = dict(headers or {})
    except Exception:
        headers = {}
    headers.setdefault("X-Trace-Id", trace_id)
    req_json = {"params": params or {}}
    try:
        result = await _fetch_json(url, headers=headers, params=params)
        audit_id = await _audit_write(
            request=request,
            action=action,
            role=role,
            target_id=target_id,
            trace_id=trace_id,
            request_json=req_json,
            response_json=result if isinstance(result, dict) else {"result": result},
            ok=True,
        )
        if isinstance(result, dict):
            result = {**result, "trace_id": trace_id, "audit_id": audit_id}
        return result
    except HTTPException as e:
        await _audit_write(
            request=request,
            action=action,
            role=role,
            target_id=target_id,
            trace_id=trace_id,
            request_json=req_json,
            response_json={"error": e.detail},
            ok=False,
        )
        raise

def _env(name: str, default: str) -> str:
    v = os.getenv(name)
    return v.strip() if v and v.strip() else default

BRAIN_API_URL = _env("BRAIN_API_URL", "http://brain_api:8100")
DASHBOARD_API_KEY = _env("DASHBOARD_API_KEY", "trading-dev")
TRADING_MASTER_KEY = os.getenv("TRADING_MASTER_KEY", "").strip()
EXPECTED_TRADING_PG_DSN = _env("EXPECTED_TRADING_PG_DSN", "postgresql://trading:trading@postgres:5432/trading")

AUDIT_DSN = _audit_get_dsn()
AUDIT_ENABLED = True

MINA_PAPER_URL = _env("MINA_PAPER_URL", "http://mina_dashboard_paper:8000")
MINA_LIVE_URL = _env("MINA_LIVE_URL", "http://mina_dashboard_live:8001")
MINA_PUMP_URL = _env("MINA_PUMP_URL", "http://mina_dashboard_pump:8002")
MINA_SCHEMA_PREFIX = _env("MINA_SCHEMA_PREFIX", "mina_")
API_DOCS_REGISTRY_PATH = Path(_env("API_DOCS_REGISTRY_PATH", "/app/gateway/gateway_api/api_docs_registry.json"))
try:
    UPSTREAM_RETRY_ATTEMPTS = max(1, int(float(_env("UPSTREAM_RETRY_ATTEMPTS", "3"))))
except Exception:
    UPSTREAM_RETRY_ATTEMPTS = 3
try:
    UPSTREAM_RETRY_BACKOFF_SEC = max(0.1, float(_env("UPSTREAM_RETRY_BACKOFF_SEC", "0.4")))
except Exception:
    UPSTREAM_RETRY_BACKOFF_SEC = 0.4
try:
    HEALTH_EVENT_WINDOW_SEC = max(15, int(float(_env("HEALTH_EVENT_WINDOW_SEC", "90"))))
except Exception:
    HEALTH_EVENT_WINDOW_SEC = 90

ROLE_URLS: Dict[str, str] = {
    "paper": MINA_PAPER_URL,
    "live": MINA_LIVE_URL,
    "pump": MINA_PUMP_URL,
}


def _redact_dsn(dsn: str) -> str:
    raw = str(dsn or "").strip()
    if raw.startswith("postgresql+psycopg://"):
        raw = "postgresql://" + raw[len("postgresql+psycopg://") :]
    if raw.startswith("postgresql+psycopg2://"):
        raw = "postgresql://" + raw[len("postgresql+psycopg2://") :]
    if not raw:
        return ""
    p = urlparse(raw)
    host = p.hostname or "localhost"
    port = f":{p.port}" if p.port else ""
    db_name = (p.path or "").lstrip("/") or "trading"
    user = p.username or "trading"
    return f"postgresql://{user}:***@{host}{port}/{db_name}"


def _assert_gateway_single_db_contract() -> None:
    def _norm(v: str) -> str:
        out = str(v or "").strip()
        if out.startswith("postgresql+psycopg://"):
            out = "postgresql://" + out[len("postgresql+psycopg://") :]
        if out.startswith("postgresql+psycopg2://"):
            out = "postgresql://" + out[len("postgresql+psycopg2://") :]
        return out

    raw = str(os.getenv("TRADING_PG_DSN") or "").strip()
    if not raw:
        raise RuntimeError(
            "TRADING_PG_DSN is required for Gateway startup. "
            "Refusing to run with implicit DB fallback."
        )
    got = _norm(raw)
    expected = _norm(EXPECTED_TRADING_PG_DSN)
    if got != expected:
        raise RuntimeError(
            f"TRADING_PG_DSN mismatch. expected={_redact_dsn(expected)!r} got={_redact_dsn(got)!r}"
        )
    # Mina schemas are fixed by contract.
    expected_prefix = "mina_"
    if MINA_SCHEMA_PREFIX != expected_prefix:
        raise RuntimeError(
            f"MINA_SCHEMA_PREFIX mismatch. expected={expected_prefix!r} got={MINA_SCHEMA_PREFIX!r}"
        )

def _validate_role(role: str) -> str:
    r = str(role or "").strip().lower()
    if r not in ROLE_URLS:
        raise HTTPException(status_code=404, detail="Unknown role")
    return r

def _schema_for_role(role: str) -> str:
    r = _validate_role(role)
    return f"{MINA_SCHEMA_PREFIX}{r}"

def _dash_url(role: str, path: str) -> str:
    r = _validate_role(role)
    base = ROLE_URLS[r].rstrip("/")
    p = "/" + str(path or "").lstrip("/")
    return f"{base}{p}"


async def _dashboard_get_json(role: str, path: str, params: dict | None = None) -> Any:
    """GET JSON from the Mina dashboard service for the given role."""
    r = _validate_role(role)
    url = f"{ROLE_URLS[r]}{path}"
    headers: dict[str, str] = {}
    if DASHBOARD_API_KEY:
        headers["X-API-Key"] = DASHBOARD_API_KEY
    return await _fetch_json(url, headers=headers, params=params)

async def _brain_get_json(path: str, params: dict | None = None) -> Any:
    """GET JSON from Brain API service."""
    url = f"{BRAIN_API_URL}{path}"
    return await _fetch_json(url, headers={}, params=params)

_assert_gateway_single_db_contract()

app = FastAPI(title="Trading Gateway", version="0.2.2")

# UI templates (Mina-style server-rendered dashboard)
UI_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
UI_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
templates = Jinja2Templates(directory=UI_TEMPLATES_DIR)
if os.path.isdir(UI_STATIC_DIR):
    app.mount("/ui/static", StaticFiles(directory=UI_STATIC_DIR), name="ui-static")

# ---- Browser auth (Batch-28): header OR secure cookie ----
# Disabled by default; set GATEWAY_API_KEY to enable.

# CORS (needed if UI calls Gateway directly). In dev, UI typically uses Vite proxy.
_GW_CORS_RAW = os.getenv("GATEWAY_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").strip()
if _GW_CORS_RAW == "*":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    _origins = [o.strip() for o in _GW_CORS_RAW.split(",") if o.strip()]
    if _origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

# Optional: protect gateway endpoints with an API key.
# Disabled by default; set GATEWAY_API_KEY to enable.
GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", "").strip()
GATEWAY_REQUIRE_API_KEY = bool(GATEWAY_API_KEY)

# Cookie auth settings (only used when GATEWAY_API_KEY is enabled)
GATEWAY_AUTH_COOKIE = os.getenv("GATEWAY_AUTH_COOKIE", "gateway_session").strip() or "gateway_session"
GATEWAY_COOKIE_SECRET = os.getenv("GATEWAY_COOKIE_SECRET", "trading-dev-cookie-secret").strip() or "trading-dev-cookie-secret"
GATEWAY_COOKIE_TTL_S = int(os.getenv("GATEWAY_COOKIE_TTL_S", "604800"))  # 7 days
GATEWAY_COOKIE_SECURE = os.getenv("GATEWAY_COOKIE_SECURE", "0").strip().lower() in ("1", "true", "yes", "on")
GATEWAY_COOKIE_SAMESITE = os.getenv("GATEWAY_COOKIE_SAMESITE", "lax").strip().lower() or "lax"


def _ct_eq(a: str, b: str) -> bool:
    try:
        import hmac as _h
        return _h.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
    except Exception:
        return a == b


def _cookie_make_token(api_key: str) -> str:
    ts = int(time.time())
    msg = f"{api_key}:{ts}".encode("utf-8")
    sig = hmac.new(GATEWAY_COOKIE_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"{ts}.{sig}"


def _cookie_validate_token(token: str, api_key: str) -> bool:
    try:
        ts_str, sig = token.split(".", 1)
        ts = int(ts_str)
    except Exception:
        return False
    now = int(time.time())
    if ts > now + 300:
        return False
    if now - ts > GATEWAY_COOKIE_TTL_S:
        return False
    msg = f"{api_key}:{ts}".encode("utf-8")
    expected = hmac.new(GATEWAY_COOKIE_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return _ct_eq(sig, expected)


def _auth_method(request: Request) -> str:
    if not GATEWAY_REQUIRE_API_KEY:
        return "none"

    hdr = request.headers.get("X-API-Key") or request.headers.get("x-api-key") or ""
    if hdr and _ct_eq(hdr, GATEWAY_API_KEY):
        return "header"

    cookie = request.cookies.get(GATEWAY_AUTH_COOKIE) or ""
    if cookie and _cookie_validate_token(cookie, GATEWAY_API_KEY):
        return "cookie"

    return "none"


@app.middleware("http")
async def _gateway_auth(request: Request, call_next):
    if not GATEWAY_REQUIRE_API_KEY:
        return await call_next(request)

    p = request.url.path

    # Allow liveness + docs + auth endpoints without auth.
    if p in ("/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc") or p.startswith("/api/auth"):
        return await call_next(request)

    # Protect all /api/* endpoints.
    if p.startswith("/api/"):
        if _auth_method(request) == "none":
            return JSONResponse({"msg": "Unauthorized"}, status_code=401)

    return await call_next(request)


@app.middleware("http")
async def _ui_action_provenance_middleware(request: Request, call_next):
    method = str(request.method or "").upper()
    path = str(request.url.path or "")
    is_api_write = (
        path.startswith("/api/")
        and method not in {"GET", "HEAD", "OPTIONS"}
        and "/stream" not in path
    )
    if not is_api_write:
        return await call_next(request)

    body_bytes = await request.body()
    request_json: Dict[str, Any]
    if body_bytes:
        request_json = _json_loads_safe(body_bytes.decode("utf-8", errors="ignore"))
        if not isinstance(request_json, dict):
            request_json = {"body": request_json}
    else:
        request_json = {}

    async def _receive() -> dict:
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    req = Request(request.scope, _receive)
    response = await call_next(req)

    response_body = b""
    try:
        async for chunk in response.body_iterator:
            response_body += chunk
    except Exception:
        response_body = b""

    result_json = _json_loads_safe(response_body.decode("utf-8", errors="ignore")) if response_body else {}
    if not isinstance(result_json, dict):
        result_json = {"result": result_json}

    actor = _actor_from_request(request) or "ui"
    trace_id = (
        request.headers.get("X-Trace-Id")
        or str(request_json.get("trace_id") or result_json.get("trace_id") or "").strip()
        or new_trace_id()
    )
    page = (
        request.headers.get("X-UI-Page")
        or str(request_json.get("ui_page") or "").strip()
        or str(request.url.path)
    )
    button_id = (
        request.headers.get("X-UI-Button-Id")
        or str(request_json.get("ui_button_id") or "").strip()
        or f"{method}:{path}"
    )
    role = _ui_action_role(path, request_json, dict(request.query_params))
    try:
        await asyncio.to_thread(
            _insert_ui_action,
            trace_id=trace_id,
            actor=actor,
            page=page,
            button_id=button_id,
            method=method,
            path=path,
            role=role,
            request_json=request_json,
            result_json=result_json,
            status_code=int(getattr(response, "status_code", 0) or 0),
        )
    except Exception as e:
        print(f"⚠️ [gateway] ui action audit failed: {e}")

    return Response(
        content=response_body,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
        background=response.background,
    )

# Reuse a single client for performance.
_client: Optional[httpx.AsyncClient] = None

@app.on_event("startup")
async def _startup():
    global _client, AUDIT_ENABLED
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=8.0), follow_redirects=True)

    # Audit log DDL bootstrap (non-fatal)
    try:
        await asyncio.to_thread(ensure_audit_schema_and_table, AUDIT_DSN)
        await asyncio.to_thread(_ensure_gateway_phase4_tables, AUDIT_DSN)
        await asyncio.to_thread(_ensure_strategy_risk_tables)
        await asyncio.to_thread(_ensure_live_policy_defaults)
        await asyncio.to_thread(_ensure_default_alert_rules)
        await asyncio.to_thread(
            _register_service_row,
            service_name=os.getenv("SERVICE_NAME", "gateway_api"),
            schema_name="gateway",
            meta={"component": "gateway"},
        )
    except Exception as e:
        AUDIT_ENABLED = False
        print(f"⚠️ [gateway] audit bootstrap disabled: {e}")

@app.on_event("shutdown")

async def _shutdown():
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


@app.get("/api/contracts")
async def api_contracts_index():
    """Contracts index."""
    return {
        "ok": True,
        "available": ["v1"],
        "default": "v1",
    }

@app.get("/api/contracts/v1")
async def api_contracts_v1():
    """Return JSON Schema for Contracts v1."""
    return {"ok": True, "schema_version": "v1", "schema": contracts_v1_schema()}

# ---- Auth endpoints (cookie session) ----
@app.get("/api/auth/status")
async def api_auth_status(request: Request):
    """Return whether gateway auth is enabled and whether the caller is authenticated."""
    enabled = GATEWAY_REQUIRE_API_KEY
    method = _auth_method(request)
    authenticated = (not enabled) or (method != "none")
    return {
        "ok": True,
        "enabled": enabled,
        "required": enabled,
        "authenticated": authenticated,
        "method": method,
        "cookie_name": GATEWAY_AUTH_COOKIE,
    }


@app.post("/api/auth/login")
async def api_auth_login(request: Request):
    """Exchange API key for an HttpOnly cookie session."""
    if not GATEWAY_REQUIRE_API_KEY:
        return {"ok": True, "enabled": False, "message": "auth_disabled"}

    try:
        body = await request.json()
    except Exception:
        body = {}

    key = str(body.get("api_key") or "").strip()
    if not key or not _ct_eq(key, GATEWAY_API_KEY):
        return JSONResponse({"ok": False, "msg": "Unauthorized"}, status_code=401)

    token = _cookie_make_token(key)
    resp = JSONResponse({"ok": True, "message": "logged_in", "method": "cookie"})
    resp.set_cookie(
        key=GATEWAY_AUTH_COOKIE,
        value=token,
        httponly=True,
        max_age=GATEWAY_COOKIE_TTL_S,
        samesite=GATEWAY_COOKIE_SAMESITE,
        secure=GATEWAY_COOKIE_SECURE,
        path="/",
    )
    return resp


@app.post("/api/auth/logout")
async def api_auth_logout():
    """Clear the auth cookie."""
    resp = JSONResponse({"ok": True, "message": "logged_out"})
    resp.delete_cookie(key=GATEWAY_AUTH_COOKIE, path="/")
    return resp


@app.get("/health")
def health():
    return {"status": "ok", "service": "gateway"}


@app.get("/api/meta/datasource")
def datasource_meta():
    dsn = (AUDIT_DSN or "").strip()
    normalized = _normalize_dsn_for_psycopg(dsn) if dsn else ""
    backend = "postgres" if normalized.startswith("postgresql://") else ("sqlite" if normalized.startswith("sqlite") else "unknown")
    db_name, host = _dsn_info(normalized) if normalized else ("trading", "localhost")
    return {
        "status": "ok",
        "service": "gateway_api",
        "backend": backend,
        "dsn_host": host,
        "db_name": db_name,
        "schema": "gateway",
        "version": os.getenv("GATEWAY_VERSION") or "dev",
    }

def _client_or_raise() -> httpx.AsyncClient:
    if _client is None:
        # Should not happen (startup), but keep safe.
        raise HTTPException(status_code=500, detail="HTTP client not initialized")
    return _client

def _clip_text(s: str, limit: int = 500) -> str:
    s = (s or "").replace("\r", "")
    if len(s) <= limit:
        return s
    return s[:limit] + "…"

def _http_exc_detail(e: HTTPException) -> Dict[str, Any]:
    # Normalize detail into a dict for consistent UI consumption.
    if isinstance(e.detail, dict):
        return e.detail
    return {"error": str(e.detail)}

async def _request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
) -> httpx.Response:
    c = _client_or_raise()
    last_exc: Exception | None = None
    attempts = max(1, int(UPSTREAM_RETRY_ATTEMPTS))
    for attempt in range(1, attempts + 1):
        try:
            return await c.request(method, url, headers=headers, params=params, json=json_body)
        except httpx.RequestError as e:
            last_exc = e
            if attempt >= attempts:
                break
            await asyncio.sleep(UPSTREAM_RETRY_BACKOFF_SEC * attempt)
    raise HTTPException(
        status_code=502,
        detail={"error": "upstream_request_error", "url": url, "exception": repr(last_exc)},
    )

def _raise_upstream_http_error(r: httpx.Response, url: str) -> None:
    raise HTTPException(
        status_code=502,
        detail={
            "error": "upstream_http_error",
            "upstream_status": r.status_code,
            "url": url,
            "content_type": r.headers.get("content-type"),
            "body": _clip_text(getattr(r, "text", ""), 600),
        },
    )

def _parse_json_or_raise(r: httpx.Response, url: str) -> Any:
    try:
        return r.json()
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "upstream_non_json",
                "upstream_status": r.status_code,
                "url": url,
                "content_type": r.headers.get("content-type"),
                "body": _clip_text(getattr(r, "text", ""), 600),
                "exception": repr(e),
            },
        )

async def _fetch_json(url: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None):
    r = await _request("GET", url, headers=headers, params=params)
    if r.status_code >= 400:
        _raise_upstream_http_error(r, url)
    return _parse_json_or_raise(r, url)

async def _post_json(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
):
    r = await _request("POST", url, headers=headers, params=params, json_body=json_body)
    if r.status_code >= 400:
        _raise_upstream_http_error(r, url)
    # Some endpoints may return plain text; wrap it.
    try:
        return r.json()
    except Exception:
        return {"ok": True, "text": r.text}



@app.get("/api/overview")
async def api_overview():
    # Proxy Brain API overview
    return await _fetch_json(f"{BRAIN_API_URL}/api/overview")

@app.get("/api/decision")
async def api_decision(request: Request):
    """Proxy Brain decision endpoint."""
    params = dict(request.query_params)
    return await _fetch_json(f"{BRAIN_API_URL}/api/decision", params=params)

@app.get("/api/ai-coach")
async def api_ai_coach(request: Request):
    params = dict(request.query_params)
    return await _fetch_json(f"{BRAIN_API_URL}/api/ai-coach", params=params)

@app.get("/api/daily-summary")
async def api_daily_summary(request: Request):
    params = dict(request.query_params)
    return await _fetch_json(f"{BRAIN_API_URL}/api/daily-summary", params=params)

@app.get("/api/daily-education")
async def api_daily_education(request: Request):
    params = dict(request.query_params)
    return await _fetch_json(f"{BRAIN_API_URL}/api/daily-education", params=params)

@app.get("/api/ml/importance")
async def api_ml_importance(request: Request):
    params = dict(request.query_params)
    return await _fetch_json(f"{BRAIN_API_URL}/api/ml/importance", params=params)

@app.get("/api/strategy-compare")
async def api_strategy_compare(request: Request):
    params = dict(request.query_params)
    return await _fetch_json(f"{BRAIN_API_URL}/api/strategy-compare", params=params)

@app.get("/api/strategy-ranking")
async def api_strategy_ranking(request: Request):
    params = dict(request.query_params)
    return await _fetch_json(f"{BRAIN_API_URL}/api/strategy-ranking", params=params)

@app.get("/api/execution-status")
async def api_execution_status(request: Request):
    params = dict(request.query_params)
    return await _fetch_json(f"{BRAIN_API_URL}/api/execution-status", params=params)

@app.get("/api/performance/by-regime")
async def api_perf_by_regime(request: Request):
    params = dict(request.query_params)
    return await _fetch_json(f"{BRAIN_API_URL}/api/performance/by-regime", params=params)

@app.post("/api/ai-chat")
async def api_ai_chat(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await _post_json(f"{BRAIN_API_URL}/api/ai-chat", json_body=body)

@app.post("/api/simulate")
async def api_simulate(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await _post_json(f"{BRAIN_API_URL}/api/simulate", json_body=body)

@app.get("/api/stack/health")
async def api_stack_health():
    # Aggregate health from brain + DB-backed Mina role snapshots.
    out = {"gateway": "ok", "brain": None, "dashboards": {}}
    # Brain
    try:
        out["brain"] = await _fetch_json(f"{BRAIN_API_URL}/api/overview")
    except HTTPException as e:
        out["brain"] = _http_exc_detail(e)

    # Mina role health is sourced from Postgres (dashboard-free).
    for role in ("paper", "live", "pump"):
        try:
            schema = _schema_for_role(role)
            out["dashboards"][role] = mina_pg.build_system_health(schema, role)
        except Exception as e:
            out["dashboards"][role] = {"ok": False, "error": str(e), "schema": _schema_for_role(role)}
    return out


@app.get("/api/system/db_wiring")
async def api_system_db_wiring():
    """Proof endpoint: all services should point to one unified Postgres DB."""
    try:
        return _db_wiring_snapshot()
    except Exception as e:
        return {"ok": False, "error": f"db_wiring_failed: {type(e).__name__}: {e}"}


@app.get("/api/ops/db_fingerprint")
async def api_ops_db_fingerprint():
    """Return DB fingerprint proving single-DB contract at runtime."""
    roles = {"paper": "mina_paper", "live": "mina_live", "pump": "mina_pump", "brain": "brain"}
    db_name, db_host = _dsn_info(AUDIT_DSN)
    with psycopg.connect(_normalize_dsn_for_psycopg(AUDIT_DSN), autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  current_database() AS current_database,
                  inet_server_addr()::text AS inet_server_addr,
                  version() AS version
                """
            )
            fp = dict(cur.fetchone() or {})
    return {
        "ok": True,
        "dsn": {"host": db_host, "db": db_name},
        "schemas": roles,
        "fingerprint": fp,
        "timestamp_utc": _utc_iso_now(),
    }


def _runtime_row_for_role(role: str) -> Dict[str, Any]:
    schema = _schema_for_role(role)
    settings = _fetch_settings(
        schema,
        [
            "execution_monitor_heartbeat",
            "last_heartbeat",
            "bot_heartbeat",
            "last_decision",
            "last_error",
            "kill_switch",
            "BOT_VERSION",
            "bot_version",
        ],
    )
    hb = _role_heartbeat_snapshot(schema, role, window_sec=HEALTH_EVENT_WINDOW_SEC)
    db_state: Dict[str, Any] = {}
    if role == "pump" and _table_exists(schema, "pump_hunter_state"):
        with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM {schema}.pump_hunter_state ORDER BY id DESC LIMIT 1")
                db_state = dict(cur.fetchone() or {})

    rows: list[dict] = []
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, service_name, role, schema_name, started_at, version, meta
                FROM gateway.service_registry
                WHERE COALESCE(role,'') = %s
                ORDER BY started_at DESC, id DESC
                LIMIT 20
                """,
                (str(role),),
            )
            rows = [dict(r) for r in (cur.fetchall() or [])]

    pref = ["pump_hunter", "mina_bot", "mina_monitor", "mina_dashboard"] if role == "pump" else ["mina_bot", "mina_monitor", "mina_dashboard", "pump_hunter"]
    chosen: dict | None = None
    for service_name in pref:
        chosen = next((r for r in rows if str(r.get("service_name") or "") == service_name), None)
        if chosen:
            break
    if not chosen and rows:
        chosen = rows[0]
    meta = chosen.get("meta") if isinstance(chosen, dict) else {}
    if isinstance(meta, str):
        meta = _safe_json_loads(meta, {})
    if not isinstance(meta, dict):
        meta = {}
    entrypoint = str(meta.get("entrypoint") or "").strip()
    if "/" in entrypoint:
        entrypoint = entrypoint.rsplit("/", 1)[-1]
    if role == "pump" and (not entrypoint):
        entrypoint = "pump_hunter.py"
    return {
        "role": role,
        "schema": schema,
        "service_name": str((chosen or {}).get("service_name") or ""),
        "version": str((chosen or {}).get("version") or settings.get("BOT_VERSION") or settings.get("bot_version") or ""),
        "entrypoint": entrypoint,
        "last_heartbeat": hb.get("last_heartbeat"),
        "last_seen_seconds": hb.get("last_seen_seconds"),
        "online": bool(hb.get("online")),
        "heartbeat_source": hb.get("heartbeat_source"),
        "last_decision": settings.get("last_decision"),
        "last_error": settings.get("last_error") or db_state.get("last_error"),
        "kill_switch": str(settings.get("kill_switch") or "0"),
        "db_state": db_state if role == "pump" else {},
    }


@app.get("/api/ops/runtime")
async def api_ops_runtime(role: str = "all"):
    roles = _resolve_roles(role)
    items = {r: _runtime_row_for_role(r) for r in roles}
    if len(items) == 1:
        only = items[roles[0]]
        return {"ok": True, "role": roles[0], **only}
    return {"ok": True, "role": role, "items": items, "timestamp_utc": _utc_iso_now()}


@app.get("/api/ops/ui_actions")
async def api_ops_ui_actions(
    limit: int = 100,
    role: str | None = None,
    page: str | None = None,
    button_id: str | None = None,
    trace_id: str | None = None,
):
    _ensure_gateway_phase4_tables(AUDIT_DSN)
    lim = max(1, min(int(limit or 100), 500))
    where: list[str] = []
    params: list[Any] = []
    if role:
        where.append("role = %s")
        params.append(str(role).strip().lower())
    if page:
        where.append("COALESCE(page,'') ILIKE %s")
        params.append(f"%{str(page).strip()}%")
    if button_id:
        where.append("COALESCE(button_id,'') ILIKE %s")
        params.append(f"%{str(button_id).strip()}%")
    if trace_id:
        where.append("COALESCE(trace_id,'') = %s")
        params.append(str(trace_id).strip())

    q = "SELECT * FROM gateway.ui_actions"
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY id DESC LIMIT %s"
    params.append(lim)
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(q, params)
            rows = [dict(r) for r in (cur.fetchall() or [])]
    return {"ok": True, "items": rows, "count": len(rows)}

@app.get("/api/audit")
async def api_audit(limit: int = 200):
    """Return the latest gateway audit log events."""
    if not AUDIT_ENABLED:
        return {"ok": False, "error": "audit_disabled"}
    try:
        rows = await asyncio.to_thread(fetch_audit_events, AUDIT_DSN, limit)
        return {"ok": True, "items": rows}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/audit_log")
async def api_audit_log(limit: int = 200):
    # Backward/alternate alias
    return await api_audit(limit=limit)



# -----------------------------
# Phase 4: Unified Event Stream
# -----------------------------

EVENTS_TABLE = os.getenv("TRADING_EVENTS_TABLE", "shared_events")
GATEWAY_SETTINGS_TABLE = "gateway.shared_settings"

AUTOPILOT_MODES = ("OFF", "SHADOW", "TESTNET", "LIVE")
AUTOPILOT_KEYS = {
    "global": "autopilot_global_mode",
    "paper": "autopilot_paper_mode",
    "live": "autopilot_live_mode",
    "pump": "autopilot_pump_mode",
}

LIVE_POLICY_KEYS = {
    "execution_enabled": "live_execution_enabled",
    "double_confirm_required": "live_double_confirm_required",
    "pin_enabled": "live_pin_enabled",
    "pin_hash": "live_pin_hash",
    "max_daily_loss": "live_max_daily_loss",
    "max_open_positions": "live_max_open_positions",
    "max_leverage": "live_max_leverage",
    "max_notional": "live_max_notional",
    "cooldown_sec": "live_cooldown_sec",
    "rollout_stage": "live_rollout_stage",
}

LIVE_ROLLOUT_STAGES = ("LIVE-0", "LIVE-1", "LIVE-2")
LIVE_OPENING_COMMANDS = {
    "EXECUTE_SIGNAL",
    "OPEN_TRADE",
    "OPEN_POSITION",
    "PLACE_ORDER",
    "BUY",
    "SELL",
    "MANUAL_BUY",
    "MANUAL_SELL",
    "ENTER_POSITION",
}
LIVE_CLOSING_COMMANDS = {
    "CLOSE_TRADE",
    "CLOSE_ALL_POSITIONS",
    "REDUCE_POSITION",
    "UPDATE_SLTP",
}
RUNTIME_EXECUTION_MODES = ("PAPER", "TEST")

def _ensure_events_table(dsn: str) -> None:
    ddl = f"""
    CREATE TABLE IF NOT EXISTS {EVENTS_TABLE} (
      id           BIGSERIAL PRIMARY KEY,
      bot_role     TEXT NOT NULL,
      event_type   TEXT NOT NULL,
      data         JSONB,
      created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_shared_events_role_time ON {EVENTS_TABLE}(bot_role, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_shared_events_type_time ON {EVENTS_TABLE}(event_type, created_at DESC);
    """
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)

def _ensure_gateway_settings_table(dsn: str) -> None:
    ddl = f"""
    CREATE SCHEMA IF NOT EXISTS gateway;
    CREATE TABLE IF NOT EXISTS {GATEWAY_SETTINGS_TABLE} (
      key         TEXT PRIMARY KEY,
      value       TEXT NOT NULL,
      updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_by  TEXT
    );
    """
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
            try:
                cur.execute(
                    "INSERT INTO gateway.schema_meta(version) VALUES (%s) ON CONFLICT (version) DO NOTHING",
                    ("phase4_v1",),
                )
            except Exception:
                pass

def _ensure_gateway_phase4_tables(dsn: str) -> None:
    ddl = """
    CREATE SCHEMA IF NOT EXISTS gateway;

    CREATE TABLE IF NOT EXISTS gateway.schema_meta (
      version     TEXT PRIMARY KEY,
      applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS gateway.integration_secrets (
      name         TEXT PRIMARY KEY,
      encrypted_json TEXT NOT NULL,
      created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS gateway.webhooks (
      id          BIGSERIAL PRIMARY KEY,
      url         TEXT NOT NULL,
      secret_hash TEXT,
      event_types JSONB,
      enabled     BOOLEAN NOT NULL DEFAULT TRUE,
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS gateway.webhook_deliveries (
      id          BIGSERIAL PRIMARY KEY,
      webhook_id  BIGINT,
      event_type  TEXT,
      payload     JSONB,
      status      TEXT,
      attempts    INTEGER DEFAULT 0,
      last_error  TEXT,
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS gateway.command_queue (
      id          BIGSERIAL PRIMARY KEY,
      role        TEXT NOT NULL,
      target      TEXT NOT NULL,
      action      TEXT NOT NULL,
      payload     JSONB,
      status      TEXT NOT NULL DEFAULT 'queued',
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      acked_at    TIMESTAMPTZ,
      executed_at TIMESTAMPTZ,
      trace_id    TEXT,
      dedupe_key  TEXT
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_gateway_command_dedupe ON gateway.command_queue(dedupe_key) WHERE dedupe_key IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_gateway_command_role ON gateway.command_queue(role, created_at DESC);

    CREATE TABLE IF NOT EXISTS gateway.alert_settings (
      encrypted_json TEXT NOT NULL,
      updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS gateway.alert_rules (
      id          BIGSERIAL PRIMARY KEY,
      enabled     BOOLEAN NOT NULL DEFAULT TRUE,
      filters     JSONB,
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS gateway.alert_delivery_log (
      id          BIGSERIAL PRIMARY KEY,
      channel     TEXT NOT NULL,
      payload     JSONB,
      status      TEXT,
      error       TEXT,
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS gateway.settings_audit (
      id          BIGSERIAL PRIMARY KEY,
      ts_utc      TIMESTAMPTZ NOT NULL DEFAULT now(),
      actor       TEXT,
      key         TEXT,
      old_value   TEXT,
      new_value   TEXT,
      trace_id    TEXT
    );

    CREATE TABLE IF NOT EXISTS gateway.service_registry (
      id           BIGSERIAL PRIMARY KEY,
      service_name TEXT NOT NULL,
      role         TEXT,
      schema_name  TEXT,
      db_name      TEXT,
      db_host      TEXT,
      started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
      version      TEXT,
      git_sha      TEXT,
      meta         JSONB
    );
    CREATE INDEX IF NOT EXISTS idx_service_registry_service_time
      ON gateway.service_registry(service_name, started_at DESC);

    CREATE TABLE IF NOT EXISTS gateway.ui_actions (
      id          BIGSERIAL PRIMARY KEY,
      ts_utc      TIMESTAMPTZ NOT NULL DEFAULT now(),
      trace_id    TEXT,
      actor       TEXT NOT NULL DEFAULT 'ui',
      page        TEXT,
      button_id   TEXT,
      method      TEXT NOT NULL,
      path        TEXT NOT NULL,
      role        TEXT,
      request_json JSONB,
      result_json JSONB,
      status_code INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_gateway_ui_actions_ts
      ON gateway.ui_actions(ts_utc DESC);
    CREATE INDEX IF NOT EXISTS idx_gateway_ui_actions_trace
      ON gateway.ui_actions(trace_id);
    CREATE INDEX IF NOT EXISTS idx_gateway_ui_actions_role
      ON gateway.ui_actions(role, ts_utc DESC);
    """
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)


def _normalize_dsn_for_psycopg(dsn: str) -> str:
    s = str(dsn or "").strip()
    if s.startswith("postgresql+psycopg://"):
        return "postgresql://" + s[len("postgresql+psycopg://") :]
    if s.startswith("postgresql+psycopg2://"):
        return "postgresql://" + s[len("postgresql+psycopg2://") :]
    return s


def _dsn_info(dsn: str) -> tuple[str, str]:
    p = urlparse(_normalize_dsn_for_psycopg(dsn))
    db_name = (p.path or "").lstrip("/") or "trading"
    db_host = p.hostname or "localhost"
    return db_name, db_host


def _register_service_row(
    *,
    service_name: str,
    role: str | None = None,
    schema_name: str | None = None,
    version: str | None = None,
    git_sha: str | None = None,
    meta: Dict[str, Any] | None = None,
) -> None:
    _ensure_gateway_phase4_tables(AUDIT_DSN)
    db_name, db_host = _dsn_info(AUDIT_DSN)
    with psycopg.connect(_normalize_dsn_for_psycopg(AUDIT_DSN), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO gateway.service_registry
                (service_name, role, schema_name, db_name, db_host, started_at, version, git_sha, meta)
                VALUES (%s, %s, %s, %s, %s, now(), %s, %s, %s::jsonb)
                """,
                (
                    str(service_name).strip(),
                    (str(role).strip().lower() or None) if role else None,
                    str(schema_name or "").strip() or None,
                    db_name,
                    db_host,
                    version or os.getenv("GATEWAY_VERSION") or "dev",
                    git_sha or os.getenv("GIT_SHA") or "",
                    json.dumps(meta or {}, ensure_ascii=True),
                ),
            )


def _db_wiring_snapshot() -> Dict[str, Any]:
    _ensure_gateway_phase4_tables(AUDIT_DSN)
    db_name_expected, db_host_expected = _dsn_info(AUDIT_DSN)

    with psycopg.connect(_normalize_dsn_for_psycopg(AUDIT_DSN), autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database() AS db_name")
            row = cur.fetchone() or {}
            current_db = str(row.get("db_name") or db_name_expected)

            cur.execute(
                """
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name IN ('mina_paper','mina_live','mina_pump','brain','gateway')
                ORDER BY schema_name
                """
            )
            schemas = [str(r.get("schema_name")) for r in (cur.fetchall() or []) if r.get("schema_name")]

            cur.execute(
                """
                SELECT DISTINCT ON (service_name, COALESCE(role,''))
                  id, service_name, role, schema_name, db_name, db_host, started_at, version, git_sha, meta
                FROM gateway.service_registry
                ORDER BY service_name, COALESCE(role,''), started_at DESC, id DESC
                """
            )
            services = [dict(r) for r in (cur.fetchall() or [])]

    by_service: Dict[str, list[Dict[str, Any]]] = {}
    for r in services:
        by_service.setdefault(str(r.get("service_name") or "unknown"), []).append(r)

    same_db = all(str(r.get("db_name") or "") == current_db for r in services) if services else False
    required = {
        ("gateway_api", None),
        ("brain_api", None),
        ("mina_dashboard", "paper"),
        ("mina_dashboard", "live"),
        ("mina_dashboard", "pump"),
    }
    optional = {
        ("brain_sync_worker", None),
        ("mina_bot", "paper"),
        ("mina_bot", "live"),
        ("mina_monitor", "paper"),
        ("mina_monitor", "live"),
        ("mina_monitor", "pump"),
        ("pump_hunter", "pump"),
    }
    present = {(str(r.get("service_name") or ""), str(r.get("role") or "") or None) for r in services}
    missing_required = [
        {"service_name": s, "role": role}
        for (s, role) in sorted(required)
        if (s, role) not in present
    ]
    missing_optional = [
        {"service_name": s, "role": role}
        for (s, role) in sorted(optional)
        if (s, role) not in present
    ]

    return {
        "ok": bool(same_db and not missing_required and len(schemas) >= 5),
        "database_name": current_db,
        "host": db_host_expected,
        "schemas": schemas,
        "same_db": same_db,
        "service_registry": services,
        "by_service": by_service,
        "missing_services": missing_required,
        "missing_optional_services": missing_optional,
    }


def _mode_rank(mode: str) -> int:
    m = str(mode or "").strip().upper()
    if m == "OFF":
        return 0
    if m == "SHADOW":
        return 1
    if m == "TESTNET":
        return 2
    if m == "LIVE":
        return 3
    return 0


def _mode_from_rank(rank: int) -> str:
    return ("OFF", "SHADOW", "TESTNET", "LIVE")[max(0, min(int(rank), 3))]


def _normalize_mode(mode: str) -> str:
    m = str(mode or "").strip().upper()
    if m not in AUTOPILOT_MODES:
        raise HTTPException(status_code=400, detail=f"invalid_mode: {mode}")
    return m


def _effective_mode(global_mode: str, role_mode: str) -> str:
    g = _mode_rank(global_mode)
    r = _mode_rank(role_mode)
    return _mode_from_rank(min(g, r))


def _get_gateway_setting(key: str, default: str = "OFF") -> str:
    _ensure_gateway_settings_table(AUDIT_DSN)
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT value FROM {GATEWAY_SETTINGS_TABLE} WHERE key = %s", (key,))
            row = cur.fetchone()
            if not row:
                return default
            return str(row[0] or default)


def _set_gateway_setting(key: str, value: str, updated_by: Optional[str] = None) -> None:
    _ensure_gateway_settings_table(AUDIT_DSN)
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {GATEWAY_SETTINGS_TABLE} (key, value, updated_by)
                VALUES (%s, %s, %s)
                ON CONFLICT (key)
                DO UPDATE SET value = EXCLUDED.value, updated_at = now(), updated_by = EXCLUDED.updated_by;
                """,
                (key, value, updated_by),
            )


def _gateway_settings_bulk(keys: list[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    unique_keys = [str(k) for k in keys if str(k or "").strip()]
    if not unique_keys:
        return out
    _ensure_gateway_settings_table(AUDIT_DSN)
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT key, value FROM {GATEWAY_SETTINGS_TABLE} WHERE key = ANY(%s)",
                (unique_keys,),
            )
            for row in (cur.fetchall() or []):
                k = str(row.get("key") or "")
                if k:
                    out[k] = str(row.get("value") or "")
    return out


def _set_gateway_setting_if_missing(key: str, value: str, updated_by: Optional[str] = None) -> None:
    _ensure_gateway_settings_table(AUDIT_DSN)
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {GATEWAY_SETTINGS_TABLE} (key, value, updated_by)
                VALUES (%s, %s, %s)
                ON CONFLICT (key) DO NOTHING
                """,
                (key, str(value), updated_by),
            )


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "on", "y", "t"}:
        return True
    if s in {"0", "false", "no", "off", "n", "f"}:
        return False
    return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _live_policy_defaults() -> Dict[str, str]:
    return {
        LIVE_POLICY_KEYS["execution_enabled"]: "0",
        LIVE_POLICY_KEYS["double_confirm_required"]: "1",
        LIVE_POLICY_KEYS["pin_enabled"]: "0",
        LIVE_POLICY_KEYS["pin_hash"]: "",
        LIVE_POLICY_KEYS["max_daily_loss"]: "0",
        LIVE_POLICY_KEYS["max_open_positions"]: "1",
        LIVE_POLICY_KEYS["max_leverage"]: "5",
        LIVE_POLICY_KEYS["max_notional"]: "1000",
        LIVE_POLICY_KEYS["cooldown_sec"]: "60",
        LIVE_POLICY_KEYS["rollout_stage"]: "LIVE-0",
        AUTOPILOT_KEYS["global"]: "OFF",
        AUTOPILOT_KEYS["live"]: "SHADOW",
    }


def _ensure_live_policy_defaults() -> None:
    defaults = _live_policy_defaults()
    for k, v in defaults.items():
        _set_gateway_setting_if_missing(k, v, updated_by="gateway.bootstrap")
    # Also keep role-level setting for compatibility with existing services.
    live_schema = _schema_for_role("live")
    try:
        if _table_exists(live_schema, "settings"):
            cols = _table_columns(live_schema, "settings")
            if "key" in cols and "value" in cols:
                with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""
                            INSERT INTO {live_schema}.settings(key, value, source)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (key) DO NOTHING
                            """,
                            ("live_execution_enabled", "0", "gateway.bootstrap"),
                        )
    except Exception:
        pass


def _get_live_safety_policy(*, mask_pin: bool = True) -> Dict[str, Any]:
    _ensure_live_policy_defaults()
    raw = _gateway_settings_bulk(list(LIVE_POLICY_KEYS.values()))
    pin_hash = str(raw.get(LIVE_POLICY_KEYS["pin_hash"]) or "")
    policy = {
        "execution_enabled": _as_bool(raw.get(LIVE_POLICY_KEYS["execution_enabled"]), False),
        "double_confirm_required": _as_bool(raw.get(LIVE_POLICY_KEYS["double_confirm_required"]), True),
        "pin_enabled": _as_bool(raw.get(LIVE_POLICY_KEYS["pin_enabled"]), False),
        "has_pin": bool(pin_hash),
        "max_daily_loss": _as_float(raw.get(LIVE_POLICY_KEYS["max_daily_loss"]), 0.0),
        "max_open_positions": _as_int(raw.get(LIVE_POLICY_KEYS["max_open_positions"]), 1),
        "max_leverage": _as_float(raw.get(LIVE_POLICY_KEYS["max_leverage"]), 0.0),
        "max_notional": _as_float(raw.get(LIVE_POLICY_KEYS["max_notional"]), 0.0),
        "cooldown_sec": _as_int(raw.get(LIVE_POLICY_KEYS["cooldown_sec"]), 0),
        "rollout_stage": str(raw.get(LIVE_POLICY_KEYS["rollout_stage"]) or "LIVE-0").upper(),
    }
    if policy["rollout_stage"] not in LIVE_ROLLOUT_STAGES:
        policy["rollout_stage"] = "LIVE-0"
    if not mask_pin:
        policy["pin_hash"] = pin_hash
    return policy


def _live_confirmation_flags(body: Dict[str, Any], request: Request) -> tuple[bool, bool, str]:
    body = body or {}
    c1 = body.get("live_confirm")
    if c1 is None:
        c1 = request.headers.get("X-Live-Confirm")
    c2 = body.get("live_confirm_ack")
    if c2 is None:
        c2 = body.get("live_double_confirm")
    if c2 is None:
        c2 = request.headers.get("X-Live-Confirm-Ack")
    pin = body.get("live_pin")
    if pin is None:
        pin = request.headers.get("X-Live-Pin")
    return _as_bool(c1, False), _as_bool(c2, False), str(pin or "")


def _enforce_live_write_confirmation(*, role: str, action: str, body: Dict[str, Any], request: Request) -> None:
    if str(role or "").lower() != "live":
        return
    policy = _get_live_safety_policy(mask_pin=False)
    c1, c2, pin = _live_confirmation_flags(body, request)

    if bool(policy.get("double_confirm_required")) and not (c1 and c2):
        raise HTTPException(
            status_code=412,
            detail={
                "error": "live_double_confirm_required",
                "message": "LIVE action requires double confirmation from Unified Dashboard.",
                "action": action,
                "policy": _get_live_safety_policy(mask_pin=True),
            },
        )

    pin_enabled = bool(policy.get("pin_enabled"))
    pin_hash = str(policy.get("pin_hash") or "")
    if pin_enabled and pin_hash:
        if not pin:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "live_pin_required",
                    "message": "LIVE action requires PIN confirmation.",
                    "action": action,
                },
            )
        got = hash_secret(str(pin))
        if not hmac.compare_digest(got, pin_hash):
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "live_pin_invalid",
                    "message": "Invalid LIVE safety PIN.",
                    "action": action,
                },
            )


def _autopilot_state() -> Dict[str, Any]:
    global_mode = _get_gateway_setting(AUTOPILOT_KEYS["global"], "OFF")
    roles = {}
    for role in ("paper", "live", "pump"):
        role_mode = _get_gateway_setting(AUTOPILOT_KEYS[role], "OFF")
        roles[role] = {
            "role_mode": role_mode,
            "effective_mode": _effective_mode(global_mode, role_mode),
        }
    return {"global_mode": global_mode, "roles": roles}


def _table_columns(schema: str, table: str) -> set[str]:
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                """,
                (schema, table),
            )
            return {r["column_name"] for r in (cur.fetchall() or [])}


def _table_exists(schema: str, table: str) -> bool:
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s
                """,
                (schema, table),
            )
            return cur.fetchone() is not None


def _fetch_settings(schema: str, keys: list[str]) -> Dict[str, Any]:
    if not _table_exists(schema, "settings"):
        return {}
    cols = _table_columns(schema, "settings")
    if "key" not in cols or "value" not in cols:
        return {}
    placeholders = ",".join(["%s"] * len(keys))
    q = f"SELECT key, value FROM {schema}.settings WHERE key IN ({placeholders})"
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(q, keys)
            rows = cur.fetchall() or []
            return {r["key"]: r["value"] for r in rows if r.get("key")}


def _set_setting(schema: str, key: str, value: str, source: str = "gateway") -> None:
    if not _table_exists(schema, "settings"):
        return
    cols = _table_columns(schema, "settings")
    if "key" not in cols or "value" not in cols:
        return
    now_iso = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    fields = ["key", "value"]
    vals: list[object] = [key, value]
    if "updated_at" in cols:
        fields.append("updated_at")
        vals.append(now_iso)
    if "source" in cols:
        fields.append("source")
        vals.append(source)
    placeholders = ",".join(["%s"] * len(fields))
    update_parts = ["value = EXCLUDED.value"]
    if "updated_at" in cols:
        update_parts.append("updated_at = EXCLUDED.updated_at")
    if "source" in cols:
        update_parts.append("source = EXCLUDED.source")
    if "version" in cols:
        update_parts.append("version = COALESCE(settings.version, 0) + 1")
    q = f"""
    INSERT INTO {schema}.settings ({', '.join(fields)})
    VALUES ({placeholders})
    ON CONFLICT (key) DO UPDATE SET {', '.join(update_parts)}
    """
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(q, vals)


def _safe_ts_value(row: Dict[str, Any], cols: set[str], candidates: list[str]) -> Any:
    for c in candidates:
        if c in cols:
            return row.get(c)
    return None


def _resolve_roles(role: str | None) -> list[str]:
    if role is None:
        return ["paper", "live", "pump"]
    r = str(role).strip().lower()
    if r in ("all", "*"):
        return ["paper", "live", "pump"]
    return [_validate_role(r)]


def _utc_iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ms_now() -> int:
    return int(time.time() * 1000)


def _safe_json_loads(value: Any, fallback: Any = None) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return fallback


def _now_utc_start_ms() -> int:
    start = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000)


def _safe_iso_from_ms(ms: int | None) -> str | None:
    if ms is None:
        return None
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000.0, tz=dt.timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def _live_runtime_snapshot(proposed_payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    schema = _schema_for_role("live")
    policy = _get_live_safety_policy(mask_pin=True)
    settings = _fetch_settings(schema, ["kill_switch", "kill_switch_reason", "live_execution_enabled"])
    kill_switch_on = _as_bool(settings.get("kill_switch"), False)

    out: Dict[str, Any] = {
        "policy": policy,
        "schema": schema,
        "kill_switch": {
            "enabled": kill_switch_on,
            "reason": str(settings.get("kill_switch_reason") or ""),
        },
        "open_positions": 0,
        "open_notional": 0.0,
        "daily_realized_pnl": 0.0,
        "max_open_leverage": 0.0,
        "last_trade_action_ms": None,
        "last_trade_action_utc": None,
        "proposed": {},
        "violations": [],
    }

    if not _table_exists(schema, "trades"):
        return out

    cols = _table_columns(schema, "trades")
    status_col = "status" if "status" in cols else None
    open_where = "UPPER(COALESCE(status,''))='OPEN'" if status_col else "TRUE"
    closed_where = "UPPER(COALESCE(status,''))='CLOSED'" if status_col else "TRUE"
    pnl_col = "pnl" if "pnl" in cols else ("realized_pnl" if "realized_pnl" in cols else None)
    qty_col = "qty" if "qty" in cols else ("quantity" if "quantity" in cols else ("size" if "size" in cols else None))
    entry_col = "entry_price" if "entry_price" in cols else ("entry" if "entry" in cols else ("price" if "price" in cols else None))
    notional_col = "notional" if "notional" in cols else ("position_notional" if "position_notional" in cols else None)
    lev_col = "leverage" if "leverage" in cols else None
    time_num_col = "closed_at_ms" if "closed_at_ms" in cols else ("updated_at_ms" if "updated_at_ms" in cols else ("timestamp_ms" if "timestamp_ms" in cols else None))
    time_txt_col = "closed_at" if "closed_at" in cols else ("updated_at" if "updated_at" in cols else ("timestamp" if "timestamp" in cols else None))

    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM {schema}.trades WHERE {open_where}")
            out["open_positions"] = int((cur.fetchone() or {}).get("n") or 0)

            if notional_col:
                cur.execute(
                    f"SELECT COALESCE(SUM(ABS(COALESCE({notional_col},0))),0) AS s FROM {schema}.trades WHERE {open_where}"
                )
                out["open_notional"] = float((cur.fetchone() or {}).get("s") or 0.0)
            elif qty_col and entry_col:
                cur.execute(
                    f"SELECT COALESCE(SUM(ABS(COALESCE({qty_col},0) * COALESCE({entry_col},0))),0) AS s FROM {schema}.trades WHERE {open_where}"
                )
                out["open_notional"] = float((cur.fetchone() or {}).get("s") or 0.0)

            if lev_col:
                cur.execute(f"SELECT COALESCE(MAX({lev_col}),0) AS m FROM {schema}.trades WHERE {open_where}")
                out["max_open_leverage"] = float((cur.fetchone() or {}).get("m") or 0.0)

            if pnl_col:
                day_start_ms = _now_utc_start_ms()
                day_start_iso = _safe_iso_from_ms(day_start_ms)
                where_parts = [closed_where]
                params: list[Any] = []
                if time_num_col:
                    where_parts.append(f"{time_num_col} >= %s")
                    params.append(day_start_ms)
                elif time_txt_col and day_start_iso:
                    where_parts.append(f"{time_txt_col} >= %s")
                    params.append(day_start_iso)
                where_sql = " AND ".join(where_parts)
                cur.execute(
                    f"SELECT COALESCE(SUM(COALESCE({pnl_col},0)),0) AS s FROM {schema}.trades WHERE {where_sql}",
                    params,
                )
                out["daily_realized_pnl"] = float((cur.fetchone() or {}).get("s") or 0.0)

            # Last action timestamp for cooldown guard.
            if time_num_col:
                cur.execute(f"SELECT COALESCE(MAX({time_num_col}),0) AS last_ms FROM {schema}.trades")
                last_ms = int((cur.fetchone() or {}).get("last_ms") or 0)
                out["last_trade_action_ms"] = last_ms if last_ms > 0 else None
            elif time_txt_col:
                cur.execute(f"SELECT {time_txt_col} AS t FROM {schema}.trades ORDER BY id DESC LIMIT 1")
                row = cur.fetchone() or {}
                out["last_trade_action_ms"] = _parse_ts_ms(str(row.get("t") or "")) if row.get("t") else None

    if out.get("last_trade_action_ms"):
        out["last_trade_action_utc"] = _safe_iso_from_ms(int(out["last_trade_action_ms"]))

    proposed = proposed_payload or {}
    proposed_leverage = _as_float(
        proposed.get("leverage")
        or proposed.get("target_leverage")
        or proposed.get("lev")
        or 0.0,
        0.0,
    )
    proposed_notional = _as_float(
        proposed.get("notional")
        or proposed.get("position_notional")
        or proposed.get("quote_qty")
        or 0.0,
        0.0,
    )
    if proposed_notional <= 0:
        qty = _as_float(proposed.get("qty") or proposed.get("quantity") or proposed.get("size") or 0.0, 0.0)
        px = _as_float(proposed.get("entry_price") or proposed.get("price") or proposed.get("mark_price") or 0.0, 0.0)
        if qty > 0 and px > 0:
            proposed_notional = abs(qty * px)
    out["proposed"] = {
        "symbol": str(proposed.get("symbol") or "").upper(),
        "side": str(proposed.get("side") or "").upper(),
        "notional": proposed_notional,
        "leverage": proposed_leverage,
    }

    caps = {
        "execution_enabled": bool(policy.get("execution_enabled")),
        "max_daily_loss": _as_float(policy.get("max_daily_loss"), 0.0),
        "max_open_positions": _as_int(policy.get("max_open_positions"), 0),
        "max_leverage": _as_float(policy.get("max_leverage"), 0.0),
        "max_notional": _as_float(policy.get("max_notional"), 0.0),
        "cooldown_sec": _as_int(policy.get("cooldown_sec"), 0),
    }

    violations: list[dict[str, Any]] = []
    if not caps["execution_enabled"]:
        violations.append({"code": "live_execution_disabled", "message": "Live execution is OFF."})
    if kill_switch_on:
        violations.append({"code": "kill_switch_on", "message": "Kill switch is enabled; opening trades is blocked."})
    if caps["max_daily_loss"] > 0 and out["daily_realized_pnl"] <= -abs(caps["max_daily_loss"]):
        violations.append(
            {
                "code": "daily_loss_cap",
                "message": f"Daily loss cap reached: pnl={out['daily_realized_pnl']:.2f}, cap={caps['max_daily_loss']:.2f}",
            }
        )
    if caps["max_open_positions"] > 0 and int(out["open_positions"] or 0) >= caps["max_open_positions"]:
        violations.append(
            {
                "code": "max_open_positions",
                "message": f"Open positions cap reached: {out['open_positions']}/{caps['max_open_positions']}",
            }
        )
    if caps["max_leverage"] > 0 and proposed_leverage > 0 and proposed_leverage > caps["max_leverage"]:
        violations.append(
            {
                "code": "max_leverage",
                "message": f"Proposed leverage {proposed_leverage:g} exceeds cap {caps['max_leverage']:g}",
            }
        )
    if caps["max_notional"] > 0:
        total_notional = float(out["open_notional"] or 0.0) + float(proposed_notional or 0.0)
        if total_notional > caps["max_notional"]:
            violations.append(
                {
                    "code": "max_notional",
                    "message": f"Projected notional {total_notional:.2f} exceeds cap {caps['max_notional']:.2f}",
                }
            )
    if caps["cooldown_sec"] > 0 and out.get("last_trade_action_ms"):
        age_sec = max(0, int((_ms_now() - int(out["last_trade_action_ms"])) / 1000))
        if age_sec < caps["cooldown_sec"]:
            violations.append(
                {
                    "code": "cooldown_active",
                    "message": f"Cooldown active ({age_sec}s elapsed, need {caps['cooldown_sec']}s).",
                }
            )

    out["violations"] = violations
    out["caps"] = caps
    return out


def _is_opening_command(cmd: str) -> bool:
    c = str(cmd or "").strip().upper()
    if c in LIVE_OPENING_COMMANDS:
        return True
    return c.startswith("OPEN_") or c.startswith("ENTER_")


def _is_closing_command(cmd: str) -> bool:
    c = str(cmd or "").strip().upper()
    if c in LIVE_CLOSING_COMMANDS:
        return True
    return c.startswith("CLOSE_") or c.startswith("REDUCE_")


def _enforce_live_opening_policy(cmd: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if not _is_opening_command(cmd):
        return _live_runtime_snapshot()
    runtime = _live_runtime_snapshot(params or {})
    violations = list(runtime.get("violations") or [])
    if violations:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "live_risk_block",
                "message": "Live safety policy blocked this opening action.",
                "cmd": str(cmd or "").strip().upper(),
                "violations": violations,
                "runtime": runtime,
            },
        )
    return runtime


def _fetch_all_settings(schema: str) -> Dict[str, str]:
    if not _table_exists(schema, "settings"):
        return {}
    cols = _table_columns(schema, "settings")
    if "key" not in cols or "value" not in cols:
        return {}
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT key, value FROM {schema}.settings")
            rows = cur.fetchall() or []
            return {str(r.get("key") or ""): str(r.get("value") or "") for r in rows if r.get("key")}


def _upsert_settings(schema: str, payload: Dict[str, Any], source: str = "gateway") -> Dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    updated: Dict[str, str] = {}
    for key, value in payload.items():
        k = str(key or "").strip()
        if not k:
            continue
        v = "" if value is None else str(value)
        _set_setting(schema, k, v, source=source)
        updated[k] = v
    return updated


def _as_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    txt = str(value).strip()
    if not txt:
        return None
    try:
        return float(txt)
    except Exception:
        return None


def _strategy_registry_defaults() -> list[dict[str, Any]]:
    return [
        {
            "strategy_id": "BASELINE_SCALP",
            "name": "Baseline Scalp",
            "role_scope": ["paper", "live"],
            "version": "v1",
            "description": "Short-horizon baseline strategy for rapid entries/exits.",
            "tags": ["baseline", "scalp"],
        },
        {
            "strategy_id": "BASELINE_SWING",
            "name": "Baseline Swing",
            "role_scope": ["paper", "live"],
            "version": "v1",
            "description": "Swing-oriented baseline strategy for multi-candle opportunities.",
            "tags": ["baseline", "swing"],
        },
        {
            "strategy_id": "PUMP_HUNTER_PROMOTE",
            "name": "Pump Hunter Promote",
            "role_scope": ["pump", "paper", "live"],
            "version": "v1",
            "description": "Signal-only pump candidate promotion flow from pump to execution roles.",
            "tags": ["pump", "promote"],
        },
        {
            "strategy_id": "NO_TRADE",
            "name": "No Trade Gate",
            "role_scope": ["paper", "live", "pump"],
            "version": "v1",
            "description": "Protective gate that explicitly vetoes trading in invalid conditions.",
            "tags": ["gate", "safety"],
        },
    ]


def _risk_profile_defaults() -> list[dict[str, Any]]:
    return [
        {
            "profile_id": "paper_conservative",
            "name": "Paper Conservative",
            "params_json": {
                "account_size_usd": 10000,
                "max_concurrent_positions": 3,
                "max_notional_per_trade": 750,
                "max_daily_loss_pct": 6.0,
                "max_drawdown_pct": 15.0,
                "max_loss_streak": 4,
                "cooldown_sec": 30,
                "min_confidence": 0.55,
                "min_score": 0.55,
                "atr_pct_min": 0.0005,
                "atr_pct_max": 0.12,
                "regime_allow": ["TREND_UP", "TREND_MIXED", "RANGE"],
            },
        },
        {
            "profile_id": "live_shadow",
            "name": "Live Shadow (TEST-only)",
            "params_json": {
                "account_size_usd": 5000,
                "max_concurrent_positions": 1,
                "max_notional_per_trade": 250,
                "max_daily_loss_pct": 2.0,
                "max_drawdown_pct": 5.0,
                "max_loss_streak": 2,
                "cooldown_sec": 90,
                "min_confidence": 0.70,
                "min_score": 0.70,
                "atr_pct_min": 0.0005,
                "atr_pct_max": 0.08,
                "regime_allow": ["TREND_UP", "RANGE"],
            },
        },
        {
            "profile_id": "pump_signal_only",
            "name": "Pump Signal Only",
            "params_json": {
                "max_concurrent_positions": 0,
                "max_notional_per_trade": 0,
                "max_daily_loss_pct": 0,
                "max_drawdown_pct": 0,
                "max_loss_streak": 0,
                "cooldown_sec": 0,
                "min_confidence": 0.0,
                "min_score": 0.0,
                "regime_allow": [],
            },
        },
    ]


def _role_runtime_defaults() -> list[dict[str, Any]]:
    return [
        {
            "role": "paper",
            "active_risk_profile": "paper_conservative",
            "execution_mode": "PAPER",
            "allow_auto_approve": False,
            "allow_manual_execute": True,
        },
        {
            "role": "live",
            "active_risk_profile": "live_shadow",
            "execution_mode": "TEST",
            "allow_auto_approve": False,
            "allow_manual_execute": True,
        },
        {
            "role": "pump",
            "active_risk_profile": "pump_signal_only",
            "execution_mode": "TEST",
            "allow_auto_approve": False,
            "allow_manual_execute": False,
        },
    ]


def _strategy_config_defaults() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for role in ("paper", "live", "pump"):
        rows.append(
            {
                "strategy_id": "BASELINE_SCALP",
                "role": role,
                "enabled": role in {"paper", "live"},
                "params_json": {},
                "min_confidence": 0.55 if role == "paper" else 0.7,
                "min_score": 0.55 if role == "paper" else 0.7,
                "max_positions": 3 if role == "paper" else 1,
                "cooldown_sec": 30 if role == "paper" else 90,
            }
        )
        rows.append(
            {
                "strategy_id": "BASELINE_SWING",
                "role": role,
                "enabled": role in {"paper", "live"},
                "params_json": {},
                "min_confidence": 0.52 if role == "paper" else 0.68,
                "min_score": 0.52 if role == "paper" else 0.68,
                "max_positions": 3 if role == "paper" else 1,
                "cooldown_sec": 60 if role == "paper" else 120,
            }
        )
        rows.append(
            {
                "strategy_id": "PUMP_HUNTER_PROMOTE",
                "role": role,
                "enabled": role in {"pump", "paper", "live"},
                "params_json": {},
                "min_confidence": 0.6,
                "min_score": 0.6,
                "max_positions": 2 if role == "paper" else 1,
                "cooldown_sec": 20,
            }
        )
        rows.append(
            {
                "strategy_id": "NO_TRADE",
                "role": role,
                "enabled": False,
                "params_json": {},
                "min_confidence": None,
                "min_score": None,
                "max_positions": None,
                "cooldown_sec": None,
            }
        )
    return rows


def _ensure_strategy_risk_tables() -> None:
    ddl = """
    CREATE SCHEMA IF NOT EXISTS brain;
    CREATE TABLE IF NOT EXISTS brain.strategy_registry (
      strategy_id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      role_scope TEXT[] NOT NULL DEFAULT ARRAY['paper'],
      version TEXT NOT NULL DEFAULT 'v1',
      description TEXT,
      tags JSONB NOT NULL DEFAULT '[]'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS brain.strategy_config (
      strategy_id TEXT NOT NULL,
      role TEXT NOT NULL,
      enabled BOOLEAN NOT NULL DEFAULT TRUE,
      params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
      min_confidence DOUBLE PRECISION,
      min_score DOUBLE PRECISION,
      max_positions INTEGER,
      cooldown_sec INTEGER,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY(strategy_id, role)
    );
    CREATE TABLE IF NOT EXISTS brain.risk_profile (
      profile_id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS brain.role_runtime (
      role TEXT PRIMARY KEY,
      active_risk_profile TEXT,
      execution_mode TEXT NOT NULL DEFAULT 'PAPER',
      allow_auto_approve BOOLEAN NOT NULL DEFAULT FALSE,
      allow_manual_execute BOOLEAN NOT NULL DEFAULT TRUE,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_brain_strategy_config_role
      ON brain.strategy_config(role, strategy_id);
    """
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
            for row in _strategy_registry_defaults():
                cur.execute(
                    """
                    INSERT INTO brain.strategy_registry
                    (strategy_id, name, role_scope, version, description, tags)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (strategy_id) DO UPDATE
                    SET name = EXCLUDED.name,
                        role_scope = EXCLUDED.role_scope,
                        version = EXCLUDED.version,
                        description = EXCLUDED.description,
                        tags = EXCLUDED.tags
                    """,
                    (
                        str(row["strategy_id"]),
                        str(row["name"]),
                        list(row.get("role_scope") or []),
                        str(row.get("version") or "v1"),
                        str(row.get("description") or ""),
                        json.dumps(row.get("tags") or [], ensure_ascii=True),
                    ),
                )
            for row in _risk_profile_defaults():
                cur.execute(
                    """
                    INSERT INTO brain.risk_profile
                    (profile_id, name, params_json)
                    VALUES (%s, %s, %s::jsonb)
                    ON CONFLICT (profile_id) DO UPDATE
                    SET name = EXCLUDED.name,
                        params_json = EXCLUDED.params_json,
                        updated_at = now()
                    """,
                    (
                        str(row["profile_id"]),
                        str(row["name"]),
                        json.dumps(row.get("params_json") or {}, ensure_ascii=True),
                    ),
                )
            for row in _role_runtime_defaults():
                cur.execute(
                    """
                    INSERT INTO brain.role_runtime
                    (role, active_risk_profile, execution_mode, allow_auto_approve, allow_manual_execute)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (role) DO NOTHING
                    """,
                    (
                        str(row["role"]),
                        str(row["active_risk_profile"]),
                        str(row["execution_mode"]),
                        bool(row.get("allow_auto_approve", False)),
                        bool(row.get("allow_manual_execute", True)),
                    ),
                )
            for row in _strategy_config_defaults():
                cur.execute(
                    """
                    INSERT INTO brain.strategy_config
                    (strategy_id, role, enabled, params_json, min_confidence, min_score, max_positions, cooldown_sec)
                    VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                    ON CONFLICT (strategy_id, role) DO NOTHING
                    """,
                    (
                        str(row["strategy_id"]),
                        str(row["role"]),
                        bool(row.get("enabled", True)),
                        json.dumps(row.get("params_json") or {}, ensure_ascii=True),
                        _as_optional_float(row.get("min_confidence")),
                        _as_optional_float(row.get("min_score")),
                        (None if row.get("max_positions") is None else int(row.get("max_positions"))),
                        (None if row.get("cooldown_sec") is None else int(row.get("cooldown_sec"))),
                    ),
                )


def _strategy_registry_rows() -> list[dict[str, Any]]:
    _ensure_strategy_risk_tables()
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM brain.strategy_registry ORDER BY strategy_id ASC")
            rows = [dict(r) for r in (cur.fetchall() or [])]
    out: list[dict[str, Any]] = []
    for row in rows:
        rr = dict(row)
        rr["role_scope"] = list(rr.get("role_scope") or [])
        tags = rr.get("tags")
        if not isinstance(tags, list):
            tags = _safe_json_loads(tags, [])
        rr["tags"] = tags if isinstance(tags, list) else []
        out.append(rr)
    return out


def _strategy_config_rows(role: str | None = None) -> list[dict[str, Any]]:
    _ensure_strategy_risk_tables()
    where = ""
    params: list[Any] = []
    if role and role not in {"all", "*"}:
        where = "WHERE role = %s"
        params.append(_validate_role(role))
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM brain.strategy_config {where} ORDER BY role ASC, strategy_id ASC", params)
            rows = [dict(r) for r in (cur.fetchall() or [])]
    out: list[dict[str, Any]] = []
    for row in rows:
        rr = dict(row)
        rr["enabled"] = bool(rr.get("enabled"))
        params_json = rr.get("params_json")
        if not isinstance(params_json, dict):
            params_json = _safe_json_loads(params_json, {})
        rr["params_json"] = params_json if isinstance(params_json, dict) else {}
        out.append(rr)
    return out


def _risk_profile_rows() -> list[dict[str, Any]]:
    _ensure_strategy_risk_tables()
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM brain.risk_profile ORDER BY profile_id ASC")
            rows = [dict(r) for r in (cur.fetchall() or [])]
    out: list[dict[str, Any]] = []
    for row in rows:
        rr = dict(row)
        params_json = rr.get("params_json")
        if not isinstance(params_json, dict):
            params_json = _safe_json_loads(params_json, {})
        rr["params_json"] = params_json if isinstance(params_json, dict) else {}
        out.append(rr)
    return out


def _risk_profile_by_id(profile_id: str | None) -> dict[str, Any]:
    rows = _risk_profile_rows()
    pid = str(profile_id or "").strip()
    for row in rows:
        if str(row.get("profile_id") or "") == pid:
            return row
    return {"profile_id": pid, "name": pid or "unknown", "params_json": {}}


def _role_runtime_rows(role: str | None = None) -> list[dict[str, Any]]:
    _ensure_strategy_risk_tables()
    where = ""
    params: list[Any] = []
    if role and role not in {"all", "*"}:
        where = "WHERE role = %s"
        params.append(_validate_role(role))
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT role, active_risk_profile, execution_mode, allow_auto_approve, allow_manual_execute, updated_at
                FROM brain.role_runtime
                {where}
                ORDER BY role ASC
                """,
                params,
            )
            rows = [dict(r) for r in (cur.fetchall() or [])]
    out: list[dict[str, Any]] = []
    for row in rows:
        rr = dict(row)
        rr["allow_auto_approve"] = bool(rr.get("allow_auto_approve"))
        rr["allow_manual_execute"] = bool(rr.get("allow_manual_execute"))
        rr["execution_mode"] = str(rr.get("execution_mode") or "PAPER").upper()
        out.append(rr)
    return out


def _role_runtime_get(role: str) -> dict[str, Any]:
    r = _validate_role(role)
    rows = _role_runtime_rows(r)
    if rows:
        return rows[0]
    fallback = next((x for x in _role_runtime_defaults() if x.get("role") == r), None) or {}
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO brain.role_runtime
                (role, active_risk_profile, execution_mode, allow_auto_approve, allow_manual_execute)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (role) DO NOTHING
                """,
                (
                    r,
                    str(fallback.get("active_risk_profile") or "paper_conservative"),
                    str(fallback.get("execution_mode") or "PAPER"),
                    bool(fallback.get("allow_auto_approve", False)),
                    bool(fallback.get("allow_manual_execute", True)),
                ),
            )
    rows = _role_runtime_rows(r)
    return rows[0] if rows else {
        "role": r,
        "active_risk_profile": str(fallback.get("active_risk_profile") or "paper_conservative"),
        "execution_mode": str(fallback.get("execution_mode") or "PAPER"),
        "allow_auto_approve": bool(fallback.get("allow_auto_approve", False)),
        "allow_manual_execute": bool(fallback.get("allow_manual_execute", True)),
    }


def _strategy_config_map(role: str) -> Dict[str, Dict[str, Any]]:
    rows = _strategy_config_rows(role)
    return {str(r.get("strategy_id") or "").upper(): r for r in rows}


def _role_trade_runtime_metrics(role: str) -> Dict[str, Any]:
    schema = _schema_for_role(role)
    out: Dict[str, Any] = {
        "role": role,
        "schema": schema,
        "open_positions": 0,
        "daily_realized_pnl": 0.0,
        "loss_streak": 0,
        "drawdown_pct": 0.0,
        "last_trade_action_ms": None,
        "last_trade_action_age_sec": None,
    }
    if not _table_exists(schema, "trades"):
        return out
    cols = _table_columns(schema, "trades")
    status_col = "status" if "status" in cols else None
    pnl_col = "pnl" if "pnl" in cols else ("realized_pnl" if "realized_pnl" in cols else None)
    time_num_col = "closed_at_ms" if "closed_at_ms" in cols else ("updated_at_ms" if "updated_at_ms" in cols else ("timestamp_ms" if "timestamp_ms" in cols else None))
    time_txt_col = "closed_at" if "closed_at" in cols else ("updated_at" if "updated_at" in cols else ("timestamp" if "timestamp" in cols else None))
    open_where = "UPPER(COALESCE(status,''))='OPEN'" if status_col else "TRUE"
    closed_where = "UPPER(COALESCE(status,''))='CLOSED'" if status_col else "TRUE"

    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM {schema}.trades WHERE {open_where}")
            out["open_positions"] = int((cur.fetchone() or {}).get("n") or 0)

            if pnl_col:
                day_start_ms = _now_utc_start_ms()
                day_start_iso = _safe_iso_from_ms(day_start_ms)
                where_parts = [closed_where]
                params: list[Any] = []
                if time_num_col:
                    where_parts.append(f"{time_num_col} >= %s")
                    params.append(day_start_ms)
                elif time_txt_col and day_start_iso:
                    where_parts.append(f"{time_txt_col} >= %s")
                    params.append(day_start_iso)
                cur.execute(
                    f"SELECT COALESCE(SUM(COALESCE({pnl_col},0)),0) AS pnl FROM {schema}.trades WHERE {' AND '.join(where_parts)}",
                    params,
                )
                out["daily_realized_pnl"] = float((cur.fetchone() or {}).get("pnl") or 0.0)

                cur.execute(
                    f"SELECT COALESCE({pnl_col},0) AS pnl FROM {schema}.trades WHERE {closed_where} ORDER BY id DESC LIMIT 50"
                )
                seq = [float((r or {}).get("pnl") or 0.0) for r in (cur.fetchall() or [])]
                streak = 0
                for pnl in seq:
                    if pnl < 0:
                        streak += 1
                    else:
                        break
                out["loss_streak"] = streak

                cur.execute(
                    f"SELECT COALESCE({pnl_col},0) AS pnl FROM {schema}.trades WHERE {closed_where} ORDER BY id ASC LIMIT 2000"
                )
                pnl_rows = [float((r or {}).get("pnl") or 0.0) for r in (cur.fetchall() or [])]
                eq = 0.0
                peak = 0.0
                max_dd = 0.0
                for pnl in pnl_rows:
                    eq += pnl
                    peak = max(peak, eq)
                    if peak > 0:
                        dd = ((peak - eq) / peak) * 100.0
                        max_dd = max(max_dd, dd)
                out["drawdown_pct"] = round(max_dd, 4)

            last_ms: int | None = None
            if time_num_col:
                cur.execute(f"SELECT COALESCE(MAX({time_num_col}),0) AS m FROM {schema}.trades")
                m = int((cur.fetchone() or {}).get("m") or 0)
                if m > 0:
                    last_ms = m
            elif time_txt_col:
                cur.execute(f"SELECT {time_txt_col} AS t FROM {schema}.trades ORDER BY id DESC LIMIT 1")
                row = cur.fetchone() or {}
                last_ms = _parse_ts_ms(str(row.get("t") or ""))
            out["last_trade_action_ms"] = last_ms
            if last_ms:
                out["last_trade_action_age_sec"] = max(0, int((_ms_now() - int(last_ms)) / 1000))
    return out


def _strategy_risk_eval(role: str, signal: Dict[str, Any], *, action: str) -> Dict[str, Any]:
    r = _validate_role(role)
    _ensure_strategy_risk_tables()
    strategy_id = str(signal.get("strategy") or signal.get("strategy_tag") or "").strip().upper() or "BASELINE_SCALP"
    confidence = _as_float(signal.get("confidence"), 0.0)
    score = _as_float(signal.get("score"), confidence)
    proposed_notional = _as_float(signal.get("amount_usd") or signal.get("notional"), 0.0)
    regime = str(signal.get("regime") or signal.get("regime_label") or "").strip().upper()
    atr_pct = _as_optional_float(signal.get("atr_pct"))
    volume = _as_optional_float(signal.get("volume"))

    runtime_cfg = _role_runtime_get(r)
    runtime_metrics = _role_trade_runtime_metrics(r)
    strategy_map = _strategy_config_map(r)
    strategy_cfg = strategy_map.get(strategy_id) or {}
    risk_profile = _risk_profile_by_id(runtime_cfg.get("active_risk_profile"))
    params = risk_profile.get("params_json")
    if not isinstance(params, dict):
        params = {}

    violations: list[dict[str, Any]] = []
    mode = str(runtime_cfg.get("execution_mode") or "PAPER").upper()
    if mode not in RUNTIME_EXECUTION_MODES:
        violations.append(
            {"code": "execution_mode_block", "message": f"Role execution_mode={mode} is not allowed in pre-LIVE mode."}
        )
    if str(action).upper() == "MANUAL_EXECUTE" and not bool(runtime_cfg.get("allow_manual_execute", True)):
        violations.append({"code": "manual_execute_disabled", "message": "Manual execution is disabled for this role."})

    settings = _fetch_settings(_schema_for_role(r), ["kill_switch"])
    if _as_bool(settings.get("kill_switch"), False):
        violations.append({"code": "kill_switch_on", "message": "Kill switch is enabled; opening trades is blocked."})

    if strategy_cfg:
        if not bool(strategy_cfg.get("enabled", True)):
            violations.append({"code": "strategy_disabled", "message": f"Strategy {strategy_id} is disabled for role={r}."})
        min_conf_cfg = _as_optional_float(strategy_cfg.get("min_confidence"))
        if min_conf_cfg is not None and confidence < min_conf_cfg:
            violations.append(
                {"code": "strategy_min_confidence", "message": f"confidence {confidence:.4f} < strategy min_confidence {min_conf_cfg:.4f}"}
            )
        min_score_cfg = _as_optional_float(strategy_cfg.get("min_score"))
        if min_score_cfg is not None and score < min_score_cfg:
            violations.append(
                {"code": "strategy_min_score", "message": f"score {score:.4f} < strategy min_score {min_score_cfg:.4f}"}
            )
        max_pos_cfg = strategy_cfg.get("max_positions")
        if max_pos_cfg is not None and str(max_pos_cfg).strip() != "":
            max_pos = int(max(0, _as_int(max_pos_cfg, 0)))
            if max_pos > 0 and int(runtime_metrics.get("open_positions") or 0) >= max_pos:
                violations.append({"code": "strategy_max_positions", "message": f"open_positions reached strategy cap {max_pos}"})
        cooldown_cfg = strategy_cfg.get("cooldown_sec")
        if cooldown_cfg is not None and str(cooldown_cfg).strip() != "":
            cool = int(max(0, _as_int(cooldown_cfg, 0)))
            age_sec = _as_int(runtime_metrics.get("last_trade_action_age_sec"), 0)
            if cool > 0 and age_sec < cool:
                violations.append({"code": "strategy_cooldown", "message": f"strategy cooldown active ({age_sec}s/{cool}s)"})

    max_concurrent = int(max(0, _as_int(params.get("max_concurrent_positions"), 0)))
    if max_concurrent > 0 and int(runtime_metrics.get("open_positions") or 0) >= max_concurrent:
        violations.append({"code": "max_concurrent_positions", "message": f"open_positions reached risk cap {max_concurrent}"})

    max_notional = _as_float(params.get("max_notional_per_trade"), 0.0)
    if max_notional > 0 and proposed_notional > 0 and proposed_notional > max_notional:
        violations.append(
            {"code": "max_notional_per_trade", "message": f"notional {proposed_notional:.2f} exceeds cap {max_notional:.2f}"}
        )

    account_size = max(1.0, _as_float(params.get("account_size_usd"), 10000.0))
    daily_loss_pct = _as_float(params.get("max_daily_loss_pct"), 0.0)
    daily_pnl_pct = (float(runtime_metrics.get("daily_realized_pnl") or 0.0) / account_size) * 100.0
    runtime_metrics["daily_pnl_pct"] = round(daily_pnl_pct, 4)
    if daily_loss_pct > 0 and daily_pnl_pct <= -abs(daily_loss_pct):
        violations.append(
            {"code": "max_daily_loss_pct", "message": f"daily pnl {daily_pnl_pct:.2f}% breached {daily_loss_pct:.2f}%"}
        )

    max_dd_pct = _as_float(params.get("max_drawdown_pct"), 0.0)
    if max_dd_pct > 0 and _as_float(runtime_metrics.get("drawdown_pct"), 0.0) > max_dd_pct:
        violations.append(
            {
                "code": "max_drawdown_pct",
                "message": f"drawdown {_as_float(runtime_metrics.get('drawdown_pct'), 0.0):.2f}% > {max_dd_pct:.2f}%",
            }
        )

    max_loss_streak = int(max(0, _as_int(params.get("max_loss_streak"), 0)))
    if max_loss_streak > 0 and int(runtime_metrics.get("loss_streak") or 0) >= max_loss_streak:
        violations.append(
            {"code": "max_loss_streak", "message": f"loss_streak={runtime_metrics.get('loss_streak')} >= {max_loss_streak}"}
        )

    cooldown_sec = int(max(0, _as_int(params.get("cooldown_sec"), 0)))
    if cooldown_sec > 0:
        age_sec = _as_int(runtime_metrics.get("last_trade_action_age_sec"), 0)
        if age_sec < cooldown_sec:
            violations.append({"code": "risk_cooldown", "message": f"cooldown active ({age_sec}s/{cooldown_sec}s)"})

    min_conf = _as_optional_float(params.get("min_confidence"))
    if min_conf is not None and confidence < min_conf:
        violations.append({"code": "risk_min_confidence", "message": f"confidence {confidence:.4f} < {min_conf:.4f}"})
    min_score = _as_optional_float(params.get("min_score"))
    if min_score is not None and score < min_score:
        violations.append({"code": "risk_min_score", "message": f"score {score:.4f} < {min_score:.4f}"})

    regime_allow = params.get("regime_allow")
    if isinstance(regime_allow, list) and regime_allow and regime:
        allowed = {str(x).strip().upper() for x in regime_allow if str(x).strip()}
        if allowed and regime not in allowed:
            violations.append({"code": "regime_filter", "message": f"regime {regime} not in allowed set"})

    atr_pct_min = _as_optional_float(params.get("atr_pct_min"))
    atr_pct_max = _as_optional_float(params.get("atr_pct_max"))
    if atr_pct is not None and atr_pct_min is not None and atr_pct < atr_pct_min:
        violations.append({"code": "atr_pct_min", "message": f"atr_pct {atr_pct:.6f} < {atr_pct_min:.6f}"})
    if atr_pct is not None and atr_pct_max is not None and atr_pct > atr_pct_max:
        violations.append({"code": "atr_pct_max", "message": f"atr_pct {atr_pct:.6f} > {atr_pct_max:.6f}"})

    min_volume = _as_optional_float(params.get("min_volume"))
    if min_volume is not None and volume is not None and volume < min_volume:
        violations.append({"code": "min_volume", "message": f"volume {volume:.2f} < {min_volume:.2f}"})

    return {
        "ok": len(violations) == 0,
        "role": r,
        "action": str(action),
        "strategy_id": strategy_id,
        "strategy_config": strategy_cfg,
        "runtime": runtime_cfg,
        "risk_profile": risk_profile,
        "metrics": runtime_metrics,
        "violations": violations,
    }


def _insert_decision_trace(role: str, signal: Dict[str, Any], eval_out: Dict[str, Any], *, trace_id: str, gate: str, decision: str) -> int:
    schema = _schema_for_role(role)
    if not _table_exists(schema, "decision_traces"):
        return 0
    cols = _table_columns(schema, "decision_traces")
    now_iso = _utc_iso_now()
    now_ms = _ms_now()
    strategy_id = str(eval_out.get("strategy_id") or signal.get("strategy") or "").strip().upper()
    confidence = _as_float(signal.get("confidence"), 0.0)
    score = _as_float(signal.get("score"), confidence)
    risk_profile = eval_out.get("risk_profile")
    if not isinstance(risk_profile, dict):
        risk_profile = {}
    min_conf = _as_optional_float(
        (eval_out.get("strategy_config") or {}).get("min_confidence")
    )
    if min_conf is None:
        min_conf = _as_optional_float((risk_profile.get("params_json") or {}).get("min_confidence"))

    trace_payload = {
        "trace_id": trace_id,
        "decision_id": f"{trace_id}:{signal.get('inbox_id') or signal.get('id') or ''}",
        "signal_id": int(signal.get("inbox_id") or signal.get("id") or 0),
        "symbol": str(signal.get("symbol") or "").upper(),
        "side": str(signal.get("side") or signal.get("signal") or "").upper(),
        "action": eval_out.get("action"),
        "gate": gate,
        "decision": decision,
        "strategy_id": strategy_id,
        "runtime": eval_out.get("runtime") or {},
        "risk_profile": risk_profile,
        "metrics": eval_out.get("metrics") or {},
        "violations": eval_out.get("violations") or [],
        "enabled_strategies": {
            str(k): bool(v.get("enabled"))
            for k, v in _strategy_config_map(role).items()
        },
        "computed_indicators": {
            "confidence": confidence,
            "score": score,
            "rsi": _as_optional_float(signal.get("rsi")),
            "adx": _as_optional_float(signal.get("adx")),
            "atr_pct": _as_optional_float(signal.get("atr_pct")),
            "pump_score": _as_optional_float(signal.get("pump_score")),
        },
    }

    fields: list[str] = []
    values: list[Any] = []

    def _add(col: str, val: Any) -> None:
        if col in cols:
            fields.append(col)
            values.append(val)

    _add("created_at", now_iso)
    _add("created_at_ms", now_ms)
    _add("symbol", str(signal.get("symbol") or "").upper())
    _add("interval", str(signal.get("timeframe") or signal.get("interval") or ""))
    _add("market_type", str(signal.get("market") or signal.get("market_type") or "futures"))
    _add("strategy", strategy_id)
    _add("gate", str(gate))
    _add("exit_profile", str((risk_profile.get("profile_id") or "risk_profile")))
    _add("decision", str(decision))
    _add("conf_pct", confidence * 100.0)
    _add("min_conf", min_conf)
    _add("final_score", score)
    _add("rule_signal", str(signal.get("side") or signal.get("signal") or ""))
    _add("ai_vote", str(signal.get("ai_vote") or decision))
    _add("ai_confidence", confidence)
    _add("pump_score", _as_optional_float(signal.get("pump_score")))
    _add("rsi", _as_optional_float(signal.get("rsi")))
    _add("adx", _as_optional_float(signal.get("adx")))
    _add("funding", _as_optional_float(signal.get("funding")))
    _add("oi_change", _as_optional_float(signal.get("oi_change")))
    _add("trace", json.dumps(trace_payload, ensure_ascii=True, default=str))

    if not fields:
        return 0
    placeholders = ",".join(["%s"] * len(fields))
    returning = " RETURNING id" if "id" in cols else ""
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {schema}.decision_traces ({', '.join(fields)}) VALUES ({placeholders}){returning}",
                values,
            )
            if "id" in cols:
                row = cur.fetchone() or {}
                return int(row.get("id") or 0)
    return 0


def _fetch_signal_rows(
    schema: str,
    *,
    status: str | None = None,
    source: str | None = None,
    symbol: str | None = None,
    timeframe: str | None = None,
    strategy: str | None = None,
    from_ms: int | None = None,
    to_ms: int | None = None,
    limit: int = 30,
) -> list[dict]:
    if not _table_exists(schema, "signal_inbox"):
        return []
    cols = _table_columns(schema, "signal_inbox")
    order_col = "received_at_ms" if "received_at_ms" in cols else ("id" if "id" in cols else None)
    ts_ms_col = "received_at_ms" if "received_at_ms" in cols else ("created_at_ms" if "created_at_ms" in cols else None)
    ts_text_col = "received_at" if "received_at" in cols else ("created_at" if "created_at" in cols else None)
    where: list[str] = []
    params: list[Any] = []

    st = str(status or "").strip().upper()
    if st and st != "ALL" and "status" in cols:
        where.append("UPPER(COALESCE(status,'')) = %s")
        params.append(st)

    src = str(source or "").strip()
    if src and "source" in cols:
        where.append("source ILIKE %s")
        params.append(f"%{src}%")

    sym = str(symbol or "").strip().upper()
    if sym and "symbol" in cols:
        where.append("UPPER(COALESCE(symbol,'')) = %s")
        params.append(sym)

    tf = str(timeframe or "").strip()
    if tf and "timeframe" in cols:
        where.append("LOWER(COALESCE(timeframe,'')) = %s")
        params.append(tf.lower())

    strat = str(strategy or "").strip()
    if strat and "strategy" in cols:
        where.append("strategy ILIKE %s")
        params.append(f"%{strat}%")

    if from_ms is not None:
        if ts_ms_col:
            where.append(f"{ts_ms_col} >= %s")
            params.append(int(from_ms))
        elif ts_text_col:
            where.append(f"{ts_text_col} >= %s")
            params.append(_ms_to_iso(int(from_ms)))

    if to_ms is not None:
        if ts_ms_col:
            where.append(f"{ts_ms_col} <= %s")
            params.append(int(to_ms))
        elif ts_text_col:
            where.append(f"{ts_text_col} <= %s")
            params.append(_ms_to_iso(int(to_ms)))

    q = f"SELECT * FROM {schema}.signal_inbox"
    if where:
        q += " WHERE " + " AND ".join(where)
    if order_col:
        q += f" ORDER BY {order_col} DESC"
    q += " LIMIT %s"
    params.append(int(max(1, min(limit, 1000))))
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(q, params)
            rows = [dict(r) for r in (cur.fetchall() or [])]
    for row in rows:
        payload_raw = row.get("payload")
        if payload_raw in (None, ""):
            payload_raw = row.get("payload_json")
        payload = _safe_json_loads(payload_raw, {})
        row["payload"] = payload if isinstance(payload, dict) else {}
    return rows


def _latest_role_health_event(schema: str, role: str) -> Dict[str, Any] | None:
    if not _table_exists(schema, "events"):
        return None
    cols = _table_columns(schema, "events")
    event_col = "event_type" if "event_type" in cols else ("type" if "type" in cols else None)
    if not event_col:
        return None
    source_col = "source" if "source" in cols else None
    payload_col = next((c for c in ("payload_json", "payload", "data", "meta") if c in cols), None)
    ts_ms_col = "created_at_ms" if "created_at_ms" in cols else ("timestamp_ms" if "timestamp_ms" in cols else None)
    ts_text_col = "created_at" if "created_at" in cols else ("timestamp" if "timestamp" in cols else None)
    role_col = "bot_role" if "bot_role" in cols else None
    order_col = ts_ms_col or ("id" if "id" in cols else None)

    where: list[str] = [f"UPPER(COALESCE({event_col},'')) IN ('HEALTHEVENT','HEALTH_EVENT','HEARTBEAT','HEARTBEAT_EVENT','HEALTH')"]
    params: list[Any] = []
    if role_col:
        where.append(f"(LOWER(COALESCE({role_col},'')) = %s OR COALESCE({role_col},'') = '')")
        params.append(str(role).strip().lower())

    q = f"SELECT * FROM {schema}.events WHERE {' AND '.join(where)}"
    if order_col:
        q += f" ORDER BY {order_col} DESC"
    q += " LIMIT 20"

    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(q, params)
            rows = [dict(r) for r in (cur.fetchall() or [])]

    for row in rows:
        payload = _safe_json_loads(row.get(payload_col), {}) if payload_col else {}
        if not isinstance(payload, dict):
            payload = {}
        payload_inner = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        heartbeat_ms = _as_int(payload.get("heartbeat_ms"), 0) or _as_int(payload_inner.get("heartbeat_ms"), 0)
        if heartbeat_ms <= 0 and ts_ms_col:
            heartbeat_ms = _as_int(row.get(ts_ms_col), 0)
        if heartbeat_ms <= 0 and ts_text_col:
            heartbeat_ms = _parse_ts_ms(str(row.get(ts_text_col) or "")) or 0
        if heartbeat_ms <= 0:
            continue
        return {
            "heartbeat_ms": int(heartbeat_ms),
            "last_heartbeat": _ms_to_iso(int(heartbeat_ms)),
            "source": str(row.get(source_col) or payload.get("source") or payload_inner.get("source") or "events"),
            "component": str(payload.get("component") or payload_inner.get("component") or ""),
            "event_type": str(row.get(event_col) or ""),
        }
    return None


def _latest_shared_health_event(role: str) -> Dict[str, Any] | None:
    role_v = str(role or "").strip().lower()
    if not role_v:
        return None
    try:
        _ensure_events_table(AUDIT_DSN)
        with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, bot_role, event_type, data, created_at
                    FROM {EVENTS_TABLE}
                    WHERE LOWER(COALESCE(bot_role,'')) = %s
                      AND UPPER(COALESCE(event_type,'')) IN ('HEALTHEVENT','HEALTH_EVENT','HEARTBEAT','HEARTBEAT_EVENT','HEALTH')
                    ORDER BY id DESC
                    LIMIT 5
                    """,
                    (role_v,),
                )
                rows = [dict(r) for r in (cur.fetchall() or [])]
    except Exception:
        return None

    for row in rows:
        data = row.get("data")
        if isinstance(data, str):
            data = _safe_json_loads(data, {})
        if not isinstance(data, dict):
            data = {}
        payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
        heartbeat_ms = _as_int(data.get("created_at_ms"), 0) or _as_int(payload.get("heartbeat_ms"), 0)
        if heartbeat_ms <= 0:
            heartbeat_ms = _parse_ts_ms(str(row.get("created_at") or "")) or 0
        if heartbeat_ms <= 0:
            continue
        return {
            "heartbeat_ms": int(heartbeat_ms),
            "last_heartbeat": _ms_to_iso(int(heartbeat_ms)),
            "source": str(data.get("source") or payload.get("source") or "shared_events"),
            "component": str(payload.get("component") or ""),
            "event_type": str(row.get("event_type") or ""),
        }
    return None


def _role_heartbeat_snapshot(schema: str, role: str, *, window_sec: int = HEALTH_EVENT_WINDOW_SEC) -> Dict[str, Any]:
    settings = _fetch_settings(schema, ["execution_monitor_heartbeat", "last_heartbeat", "bot_heartbeat"])
    setting_hb_raw = settings.get("execution_monitor_heartbeat") or settings.get("last_heartbeat") or settings.get("bot_heartbeat")
    setting_ms = _parse_ts_ms(str(setting_hb_raw or "")) if setting_hb_raw else None
    event_hb = _latest_role_health_event(schema, role) or _latest_shared_health_event(role)

    heartbeat_ms = _as_int((event_hb or {}).get("heartbeat_ms"), 0)
    source = "events" if heartbeat_ms > 0 else "settings"
    component = str((event_hb or {}).get("component") or "")
    event_type = str((event_hb or {}).get("event_type") or "")

    if heartbeat_ms <= 0 and setting_ms is not None:
        heartbeat_ms = int(setting_ms)
        component = ""
        event_type = ""

    if heartbeat_ms <= 0:
        return {
            "online": False,
            "last_heartbeat": setting_hb_raw,
            "last_seen_seconds": None,
            "heartbeat_source": "none",
            "heartbeat_component": component,
            "heartbeat_event_type": event_type,
        }

    age_sec = max(0, int((_ms_now() - int(heartbeat_ms)) / 1000))
    return {
        "online": age_sec <= max(5, int(window_sec or 90)),
        "last_heartbeat": _ms_to_iso(int(heartbeat_ms)),
        "last_seen_seconds": age_sec,
        "heartbeat_source": source,
        "heartbeat_component": component,
        "heartbeat_event_type": event_type,
    }


def _fetch_signal_one(schema: str, signal_id: int) -> Optional[dict]:
    if not _table_exists(schema, "signal_inbox"):
        return None
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {schema}.signal_inbox WHERE id = %s LIMIT 1", (int(signal_id),))
            row = cur.fetchone()
            if not row:
                return None
            out = dict(row)
    payload = _safe_json_loads(out.get("payload"), {})
    out["payload"] = payload if isinstance(payload, dict) else {}
    return out


def _update_signal_status(schema: str, signal_id: int, status: str, note: str | None = None) -> None:
    if not _table_exists(schema, "signal_inbox"):
        return
    cols = _table_columns(schema, "signal_inbox")
    st = str(status or "").strip().upper()
    fields: list[str] = ["status = %s"]
    values: list[Any] = [st]
    if note is not None and "note" in cols:
        fields.append("note = %s")
        values.append(str(note))
    now_ms = _ms_now()
    if st == "APPROVED" and "approved_at_ms" in cols:
        fields.append("approved_at_ms = %s")
        values.append(now_ms)
    if st == "REJECTED" and "rejected_at_ms" in cols:
        fields.append("rejected_at_ms = %s")
        values.append(now_ms)
    if st == "EXECUTED" and "executed_at_ms" in cols:
        fields.append("executed_at_ms = %s")
        values.append(now_ms)
    values.append(int(signal_id))
    q = f"UPDATE {schema}.signal_inbox SET {', '.join(fields)} WHERE id = %s"
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(q, values)


def _insert_rejection(schema: str, symbol: str, reason: str) -> None:
    if not _table_exists(schema, "rejections"):
        return
    cols = _table_columns(schema, "rejections")
    fields: list[str] = []
    values: list[Any] = []
    if "symbol" in cols:
        fields.append("symbol")
        values.append(symbol)
    if "reason" in cols:
        fields.append("reason")
        values.append(reason)
    if "value" in cols:
        fields.append("value")
        values.append(0)
    if "threshold" in cols:
        fields.append("threshold")
        values.append(0)
    if "timestamp" in cols:
        fields.append("timestamp")
        values.append(_utc_iso_now())
    if not fields:
        return
    ph = ",".join(["%s"] * len(fields))
    q = f"INSERT INTO {schema}.rejections ({', '.join(fields)}) VALUES ({ph})"
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(q, values)


def _normalize_side(value: Any) -> str:
    side = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    if side in {"BUY", "LONG", "MANUAL_BUY", "MANUAL_LONG"}:
        return "LONG"
    if side in {"SELL", "SHORT", "MANUAL_SELL", "MANUAL_SHORT"}:
        return "SHORT"
    return side


def _insert_mina_command(schema: str, cmd: str, params: Dict[str, Any] | None, trace_id: str, source: str = "gateway") -> int:
    if not _table_exists(schema, "commands"):
        raise HTTPException(status_code=503, detail=f"{schema}.commands_missing")
    cols = _table_columns(schema, "commands")
    if "cmd" not in cols:
        raise HTTPException(status_code=503, detail=f"{schema}.commands_cmd_missing")
    fields = ["cmd"]
    values: list[Any] = [str(cmd).strip().upper()]
    if "params" in cols:
        fields.append("params")
        values.append(json.dumps(params or {}, ensure_ascii=True))
    if "trace_id" in cols:
        fields.append("trace_id")
        values.append(trace_id)
    if "status" in cols:
        fields.append("status")
        values.append("PENDING")
    if "created_at" in cols:
        fields.append("created_at")
        values.append(_utc_iso_now())
    if "created_at_ms" in cols:
        fields.append("created_at_ms")
        values.append(_ms_now())
    if "source" in cols:
        fields.append("source")
        values.append(source)
    ph = ",".join(["%s"] * len(fields))
    q = f"INSERT INTO {schema}.commands ({', '.join(fields)}) VALUES ({ph}) RETURNING id"
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(q, values)
            row = cur.fetchone()
            return int((row or {}).get("id") or 0)


def _queue_role_command(
    *,
    role: str,
    cmd: str,
    params: Dict[str, Any] | None,
    trace_id: str,
    request_payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    cmd_upper = str(cmd).strip().upper()
    if str(role or "").lower() == "live":
        _enforce_live_opening_policy(cmd_upper, params or {})
    schema = _schema_for_role(role)
    command_id = _insert_mina_command(schema, cmd=cmd_upper, params=params or {}, trace_id=trace_id)
    queue_row = _insert_command_queue(
        role=role,
        target="bot",
        action=cmd_upper,
        payload=request_payload or {"cmd": cmd_upper, "params": params or {}},
        trace_id=trace_id,
        dedupe_key=None,
        force=False,
    )
    return {"command_id": command_id, "queue": queue_row}


def _approve_signal_from_db(role: str, signal_id: int, note: str = "", payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    schema = _schema_for_role(role)
    rec = _fetch_signal_one(schema, int(signal_id))
    if not rec:
        raise HTTPException(status_code=404, detail="signal_not_found")
    merged: Dict[str, Any] = {}
    if isinstance(rec.get("payload"), dict):
        merged.update(rec.get("payload") or {})
    if isinstance(payload, dict):
        merged.update(payload)
    for key in ("symbol", "side", "strategy", "timeframe", "confidence", "score"):
        if merged.get(key) in (None, "") and rec.get(key) not in (None, ""):
            merged[key] = rec.get(key)
    merged["symbol"] = str(merged.get("symbol") or "").strip().upper()
    merged["side"] = _normalize_side(merged.get("side") or merged.get("signal") or merged.get("direction"))
    if not merged["symbol"]:
        raise HTTPException(status_code=400, detail="missing_symbol")
    if merged["side"] not in {"LONG", "SHORT", "BUY", "SELL"}:
        raise HTTPException(status_code=400, detail="missing_invalid_side")
    merged["inbox_id"] = int(signal_id)
    merged["_dashboard_signal_id"] = int(signal_id)
    merged["_approved_by"] = "gateway"
    merged["_approved_at"] = _utc_iso_now()
    trace_id = uuid.uuid4().hex
    eval_out = _strategy_risk_eval(role, merged, action="SIGNAL_APPROVE")
    if not bool(eval_out.get("ok")):
        first_msg = str(((eval_out.get("violations") or [{}])[0] or {}).get("message") or "strategy/risk gate blocked this signal")
        _update_signal_status(schema, int(signal_id), "REJECTED", note=f"VETO: {first_msg}")
        _insert_rejection(schema, symbol=str(merged.get("symbol") or "UNKNOWN"), reason=first_msg)
        trace_row_id = _insert_decision_trace(
            role,
            merged,
            eval_out,
            trace_id=trace_id,
            gate="BLOCK",
            decision="NO_TRADE",
        )
        raise HTTPException(
            status_code=409,
            detail={
                "error": "strategy_risk_veto",
                "message": "Signal approval blocked by strategy/risk policy.",
                "trace_id": trace_id,
                "decision_trace_id": trace_row_id,
                "evaluation": jsonable_encoder(eval_out),
            },
        )
    queued = _queue_role_command(
        role=role,
        cmd="EXECUTE_SIGNAL",
        params=merged,
        trace_id=trace_id,
        request_payload={"signal_id": int(signal_id), "note": note, "payload": merged},
    )
    _update_signal_status(schema, int(signal_id), "APPROVED", note=note)
    decision_trace_id = _insert_decision_trace(
        role,
        merged,
        eval_out,
        trace_id=trace_id,
        gate="PASS",
        decision="EXECUTE_SIGNAL",
    )
    return {
        "ok": True,
        "status": "ok",
        "id": int(signal_id),
        "role": role,
        "schema": schema,
        "trace_id": trace_id,
        "decision_trace_id": decision_trace_id,
        "evaluation": eval_out,
        **queued,
    }


def _reject_signal_from_db(role: str, signal_id: int, reason: str, note: str = "") -> Dict[str, Any]:
    schema = _schema_for_role(role)
    rec = _fetch_signal_one(schema, int(signal_id))
    if not rec:
        raise HTTPException(status_code=404, detail="signal_not_found")
    symbol = str((rec.get("symbol") or ((rec.get("payload") or {}).get("symbol") if isinstance(rec.get("payload"), dict) else "")) or "UNKNOWN")
    _update_signal_status(schema, int(signal_id), "REJECTED", note=(note or reason))
    _insert_rejection(schema, symbol=symbol, reason=reason)
    return {"ok": True, "status": "ok", "id": int(signal_id), "role": role, "schema": schema}


def _save_integration_secret(name: str, payload: Dict[str, Any]) -> None:
    _ensure_gateway_phase4_tables(AUDIT_DSN)
    enc = encrypt_json(TRADING_MASTER_KEY, payload)
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO gateway.integration_secrets(name, encrypted_json, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (name)
                DO UPDATE SET encrypted_json = EXCLUDED.encrypted_json, updated_at = now()
                """,
                (name, enc),
            )


def _load_integration_secret(name: str) -> Dict[str, Any]:
    _ensure_gateway_phase4_tables(AUDIT_DSN)
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT encrypted_json FROM gateway.integration_secrets WHERE name = %s", (name,))
            row = cur.fetchone()
            if not row:
                return {}
            return decrypt_json(TRADING_MASTER_KEY, row[0])


def _save_alert_settings(payload: Dict[str, Any]) -> None:
    _ensure_gateway_phase4_tables(AUDIT_DSN)
    enc = encrypt_json(TRADING_MASTER_KEY, payload)
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM gateway.alert_settings")
            cur.execute(
                "INSERT INTO gateway.alert_settings(encrypted_json, updated_at) VALUES (%s, now())",
                (enc,),
            )


def _load_alert_settings() -> Dict[str, Any]:
    _ensure_gateway_phase4_tables(AUDIT_DSN)
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT encrypted_json FROM gateway.alert_settings ORDER BY updated_at DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return {}
            return decrypt_json(TRADING_MASTER_KEY, row[0])


def _ensure_default_alert_rules() -> None:
    _ensure_gateway_phase4_tables(AUDIT_DSN)
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM gateway.alert_rules")
            n = int((cur.fetchone() or {}).get("n") or 0)
            if n > 0:
                return
            filters = {
                "event_types": [
                    "INCIDENT_SERVICE_DOWN",
                    "INCIDENT_SERVICE_WARN",
                    "INCIDENT_SYNC_LAG",
                    "INCIDENT_DD_BREACH",
                    "INCIDENT_KILL_SWITCH",
                    "INCIDENT_WARN",
                ]
            }
            cur.execute(
                "INSERT INTO gateway.alert_rules(enabled, filters) VALUES (%s, %s::jsonb)",
                (True, json.dumps(filters, ensure_ascii=True)),
            )


def _audit_settings_change(key: str, old_val: str | None, new_val: str | None, trace_id: str, actor: str) -> None:
    try:
        _ensure_gateway_phase4_tables(AUDIT_DSN)
        with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO gateway.settings_audit(actor, key, old_value, new_value, trace_id) VALUES (%s, %s, %s, %s, %s)",
                    (actor, key, old_val, new_val, trace_id),
                )
    except Exception:
        pass


def _insert_command_queue(
    *,
    role: str,
    target: str,
    action: str,
    payload: Dict[str, Any] | None,
    trace_id: str,
    dedupe_key: str | None,
    force: bool = False,
) -> Dict[str, Any]:
    _ensure_gateway_phase4_tables(AUDIT_DSN)
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            if dedupe_key and not force:
                cur.execute(
                    "SELECT * FROM gateway.command_queue WHERE dedupe_key = %s ORDER BY id DESC LIMIT 1",
                    (dedupe_key,),
                )
                row = cur.fetchone()
                if row:
                    return dict(row)

            cur.execute(
                """
                INSERT INTO gateway.command_queue(role, target, action, payload, trace_id, dedupe_key)
                VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                RETURNING *
                """,
                (role, target, action, json.dumps(payload or {}), trace_id, dedupe_key),
            )
            row = cur.fetchone()
            return dict(row) if row else {}


def _mirror_command_to_mina(schema: str, cmd: str, params: Dict[str, Any] | None, trace_id: str) -> None:
    if not _table_exists(schema, "commands"):
        return
    cols = _table_columns(schema, "commands")
    if "cmd" not in cols:
        return
    payload = json.dumps(params or {})
    now_iso = dt.datetime.utcnow().isoformat() + "Z"
    now_ms = int(time.time() * 1000)

    fields = ["cmd"]
    values: list[Any] = [cmd]
    if "params" in cols:
        fields.append("params")
        values.append(payload)
    if "status" in cols:
        fields.append("status")
        values.append("PENDING")
    if "created_at" in cols:
        fields.append("created_at")
        values.append(now_iso)
    if "created_at_ms" in cols:
        fields.append("created_at_ms")
        values.append(now_ms)
    if "source" in cols:
        fields.append("source")
        values.append("gateway")
    if "trace_id" in cols:
        fields.append("trace_id")
        values.append(trace_id)

    placeholders = ",".join(["%s"] * len(fields))
    q = f"INSERT INTO {schema}.commands ({', '.join(fields)}) VALUES ({placeholders})"
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(q, values)


def _fetch_logs(schema: str, *, level: str | None = None, contains: str | None = None, since_ms: int | None = None, limit: int = 200) -> list[dict]:
    if not _table_exists(schema, "logs"):
        return []
    cols = _table_columns(schema, "logs")
    level_col = "level" if "level" in cols else None
    msg_col = "message" if "message" in cols else ("msg" if "msg" in cols else None)
    time_col = None
    for cand in ("timestamp_ms", "timestamp", "time", "created_at", "created_at_ms"):
        if cand in cols:
            time_col = cand
            break
    where: list[str] = []
    params: list[object] = []
    if level and level_col:
        where.append(f"{level_col} ILIKE %s")
        params.append(f"%{level}%")
    if contains and msg_col:
        where.append(f"{msg_col} ILIKE %s")
        params.append(f"%{contains}%")
    if since_ms is not None and time_col:
        where.append(f"{time_col} >= %s")
        params.append(int(since_ms))

    q = f"SELECT * FROM {schema}.logs"
    if where:
        q += " WHERE " + " AND ".join(where)
    if time_col:
        q += f" ORDER BY {time_col} DESC"
    q += " LIMIT %s"
    params.append(int(limit))
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(q, params)
            return list(cur.fetchall())

async def _events_fetch(
    *,
    limit: int = 200,
    bot_role: str | None = None,
    event_type: str | None = None,
    since_id: int | None = None,
    order: str | None = None,
):
    limit = max(1, min(int(limit or 200), 1000))
    order = (order or "desc").lower()
    if order not in ("asc", "desc"):
        order = "desc"

    def _run():
        _ensure_events_table(AUDIT_DSN)
        where = []
        params: list[object] = []
        if bot_role:
            where.append("bot_role = %s")
            params.append(bot_role)
        if event_type:
            where.append("event_type = %s")
            params.append(event_type)
        if since_id is not None:
            where.append("id > %s")
            params.append(int(since_id))

        wsql = ("WHERE " + " AND ".join(where)) if where else ""
        sql = f"""
        SELECT id, bot_role, event_type, data, created_at
        FROM {EVENTS_TABLE}
        {wsql}
        ORDER BY id {order}
        LIMIT %s
        """
        params.append(limit)
        with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())

    return await asyncio.to_thread(_run)


def _events_last_id() -> int:
    _ensure_events_table(AUDIT_DSN)
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COALESCE(MAX(id), 0) FROM {EVENTS_TABLE}")
            row = cur.fetchone()
            return int(row[0] or 0)


def _normalize_trade_status_filter(status: str) -> tuple[str, list]:
    s = str(status or "").strip().upper()
    if not s or s == "ALL":
        return "", []
    if s == "OPEN":
        return "UPPER(status) = 'OPEN'", []
    if s in ("CLOSED", "CLOSE", "DONE", "FILLED"):
        return "UPPER(status) = 'CLOSED'", []
    return "UPPER(status) = %s", [s]


async def _trades_fetch(
    *,
    role: str,
    limit: int = 50,
    status: str | None = None,
    symbol: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
):
    role = _validate_role(role)
    schema = _schema_for_role(role)
    limit = max(1, min(int(limit or 50), 1000))

    def _run():
        with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = 'trades'
                    """,
                    (schema,),
                )
                cols = {r["column_name"] for r in (cur.fetchall() or [])}
                if not cols:
                    raise RuntimeError("trades_table_missing")

                where: list[str] = []
                params: list[object] = []
                if status:
                    if "status" not in cols:
                        raise RuntimeError("status_filter_not_supported")
                    clause, extra = _normalize_trade_status_filter(status)
                    if clause:
                        where.append(clause)
                        params.extend(extra)

                if symbol:
                    sym = str(symbol).strip().upper()
                    if sym:
                        if "symbol" in cols:
                            where.append("symbol = %s")
                            params.append(sym)
                        elif "pair" in cols:
                            where.append("pair = %s")
                            params.append(sym)
                        else:
                            raise RuntimeError("symbol_filter_not_supported")

                from_ms = _parse_ts_ms(from_ts)
                to_ms = _parse_ts_ms(to_ts)
                time_num_col = "closed_at_ms" if "closed_at_ms" in cols else ("created_at_ms" if "created_at_ms" in cols else ("timestamp_ms" if "timestamp_ms" in cols else None))
                time_txt_col = "closed_at" if "closed_at" in cols else ("created_at" if "created_at" in cols else ("timestamp" if "timestamp" in cols else None))
                if time_num_col:
                    if from_ms is not None:
                        where.append(f"{time_num_col} >= %s")
                        params.append(int(from_ms))
                    if to_ms is not None:
                        where.append(f"{time_num_col} <= %s")
                        params.append(int(to_ms))
                elif time_txt_col:
                    if from_ts:
                        where.append(f"{time_txt_col} >= %s")
                        params.append(_ms_to_iso(from_ms) if from_ms is not None else str(from_ts))
                    if to_ts:
                        where.append(f"{time_txt_col} <= %s")
                        params.append(_ms_to_iso(to_ms) if to_ms is not None else str(to_ts))

                order_col = None
                for cand in ("id", "closed_at_ms", "closed_at", "timestamp"):
                    if cand in cols:
                        order_col = cand
                        break

                q = f"SELECT * FROM {schema}.trades"
                if where:
                    q += " WHERE " + " AND ".join(where)
                if order_col:
                    q += f" ORDER BY {order_col} DESC"
                q += " LIMIT %s"
                params.append(limit)
                cur.execute(q, params)
                return list(cur.fetchall())

    try:
        return await asyncio.to_thread(_run)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "trades_query_failed", "detail": str(e)})


async def _trade_fetch_one(role: str, trade_id: int):
    role = _validate_role(role)
    schema = _schema_for_role(role)
    try:
        trade_id = int(trade_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_trade_id")

    def _run():
        with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = 'trades'
                    """,
                    (schema,),
                )
                cols = {r["column_name"] for r in (cur.fetchall() or [])}
                if not cols:
                    raise RuntimeError("trades_table_missing")
                id_col = "id" if "id" in cols else ("trade_id" if "trade_id" in cols else None)
                if not id_col:
                    raise RuntimeError("trade_id_column_missing")
                q = f"SELECT * FROM {schema}.trades WHERE {id_col} = %s LIMIT 1"
                cur.execute(q, (trade_id,))
                return cur.fetchone()

    try:
        return await asyncio.to_thread(_run)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "trade_query_failed", "detail": str(e)})


def _parse_ts_ms(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.isdigit():
        n = int(s)
        # if seconds, convert to ms
        if n < 10**12:
            n *= 1000
        return n
    # ISO datetime/date support (UTC by default for naive values).
    try:
        ss = s
        if ss.endswith("Z"):
            ss = ss[:-1] + "+00:00"
        if "T" not in ss and " " not in ss and len(ss) == 10 and ss.count("-") == 2:
            ss = ss + "T00:00:00+00:00"
        parsed = dt.datetime.fromisoformat(ss)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return int(parsed.astimezone(dt.timezone.utc).timestamp() * 1000)
    except Exception:
        pass
    return None


def _ms_to_iso(ms: int) -> str:
    try:
        return dt.datetime.fromtimestamp(ms / 1000.0, tz=dt.timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return str(ms)


async def _equity_history_fetch(
    *,
    role: str,
    limit: int = 200,
    from_ts: str | None = None,
    to_ts: str | None = None,
):
    role = _validate_role(role)
    schema = _schema_for_role(role)
    limit = max(1, min(int(limit or 200), 2000))

    def _run():
        with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = 'equity_history'
                    """,
                    (schema,),
                )
                cols = {r["column_name"] for r in (cur.fetchall() or [])}
                if not cols:
                    raise RuntimeError("equity_history_table_missing")

                num_col = "timestamp_ms" if "timestamp_ms" in cols else None
                text_col = None
                for cand in ("timestamp", "created_at", "date_utc"):
                    if cand in cols:
                        text_col = cand
                        break

                where: list[str] = []
                params: list[object] = []
                f_ms = _parse_ts_ms(from_ts)
                t_ms = _parse_ts_ms(to_ts)
                if num_col:
                    if f_ms is not None:
                        where.append(f"{num_col} >= %s")
                        params.append(int(f_ms))
                    if t_ms is not None:
                        where.append(f"{num_col} <= %s")
                        params.append(int(t_ms))
                elif text_col:
                    if from_ts:
                        params.append(_ms_to_iso(f_ms) if f_ms is not None else str(from_ts))
                        where.append(f"{text_col} >= %s")
                    if to_ts:
                        params.append(_ms_to_iso(t_ms) if t_ms is not None else str(to_ts))
                        where.append(f"{text_col} <= %s")

                order_col = num_col or text_col or "id"
                q = f"SELECT * FROM {schema}.equity_history"
                if where:
                    q += " WHERE " + " AND ".join(where)
                q += f" ORDER BY {order_col} ASC"
                q += " LIMIT %s"
                params.append(limit)
                cur.execute(q, params)
                return list(cur.fetchall())

    try:
        return await asyncio.to_thread(_run)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "equity_history_query_failed", "detail": str(e)})


async def _perf_metrics_fetch(
    *,
    role: str,
    limit: int = 500,
    from_ts: str | None = None,
    to_ts: str | None = None,
):
    role = _validate_role(role)
    schema = _schema_for_role(role)
    limit = max(1, min(int(limit or 500), 5000))

    def _run():
        with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = 'perf_metrics'
                    """,
                    (schema,),
                )
                cols = {r["column_name"] for r in (cur.fetchall() or [])}
                if not cols:
                    raise RuntimeError("perf_metrics_table_missing")

                num_col = "created_at_ms" if "created_at_ms" in cols else None
                text_col = "created_at" if "created_at" in cols else None

                where: list[str] = []
                params: list[object] = []
                f_ms = _parse_ts_ms(from_ts)
                t_ms = _parse_ts_ms(to_ts)
                if num_col:
                    if f_ms is not None:
                        where.append(f"{num_col} >= %s")
                        params.append(int(f_ms))
                    if t_ms is not None:
                        where.append(f"{num_col} <= %s")
                        params.append(int(t_ms))
                elif text_col:
                    if from_ts:
                        params.append(_ms_to_iso(f_ms) if f_ms is not None else str(from_ts))
                        where.append(f"{text_col} >= %s")
                    if to_ts:
                        params.append(_ms_to_iso(t_ms) if t_ms is not None else str(to_ts))
                        where.append(f"{text_col} <= %s")

                order_col = num_col or text_col or "id"
                q = f"SELECT * FROM {schema}.perf_metrics"
                if where:
                    q += " WHERE " + " AND ".join(where)
                q += f" ORDER BY {order_col} DESC"
                q += " LIMIT %s"
                params.append(limit)
                cur.execute(q, params)
                return list(cur.fetchall())

    try:
        return await asyncio.to_thread(_run)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "perf_metrics_query_failed", "detail": str(e)})

@app.get("/api/events")
async def api_events(
    limit: int = 200,
    role: str | None = None,
    event_type: str | None = None,
    since_id: int | None = None,
    order: str | None = None,
):
    """Return unified shared events (append-only) from Postgres."""
    try:
        rows = await _events_fetch(limit=limit, bot_role=role, event_type=event_type, since_id=since_id, order=order)
        return {"ok": True, "items": rows, "count": len(rows)}
    except Exception as e:
        return {"ok": False, "error": str(e), "items": [], "count": 0}

@app.get("/api/events/stream")
async def api_events_stream(request: Request, since_id: int = 0, role: str | None = None, event_type: str | None = None, poll_s: float = 1.0, interval_ms: int | None = None, event_name: str | None = None):
    """Server-Sent Events stream for shared_events."""
    async def gen():
        last = int(since_id or 0)
        # Support UI-friendly interval_ms (preferred) and legacy poll_s
        sleep_s = float(poll_s or 1.0)
        if interval_ms is not None:
            try:
                sleep_s = float(interval_ms) / 1000.0
            except Exception:
                sleep_s = float(poll_s or 1.0)
        # Default SSE event type is "message" (works with EventSource.onmessage).
        # If event_name is provided and not "message", we emit "event: <event_name>" for compatibility.
        yield ": connected\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                rows = await _events_fetch(limit=200, bot_role=role, event_type=event_type, since_id=last)
                # rows are newest-first; stream oldest-first
                rows_sorted = sorted(rows, key=lambda r: int(r.get("id", 0)))
                for r in rows_sorted:
                    rid = int(r.get("id", 0))
                    if rid > last:
                        last = rid
                    payload = json.dumps(r, default=str)
                    yield f"id: {rid}\n"
                    if event_name and str(event_name).strip().lower() != "message":
                        yield f"event: {str(event_name).strip()}\n"
                    yield f"data: {payload}\n\n"
            except Exception as e:
                if event_name and str(event_name).strip().lower() != "message":
                    yield "event: error\n"
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            await asyncio.sleep(max(0.25, float(sleep_s)))
    return StreamingResponse(gen(), media_type="text/event-stream")


# Unified aliases (prefer these for the unified dashboard)
@app.get("/api/unified/events")
async def api_unified_events(
    limit: int = 200,
    role: str | None = None,
    event_type: str | None = None,
    since_id: int | None = None,
    order: str | None = None,
):
    return await api_events(limit=limit, role=role, event_type=event_type, since_id=since_id, order=order)

@app.get("/api/unified/events/stream")
async def api_unified_events_stream(
    request: Request,
    since_id: int = 0,
    role: str | None = None,
    event_type: str | None = None,
    poll_s: float = 1.0,
    interval_ms: int | None = None,
    event_name: str | None = None,
):
    return await api_events_stream(
        request,
        since_id=since_id,
        role=role,
        event_type=event_type,
        poll_s=poll_s,
        interval_ms=interval_ms,
        event_name=event_name,
    )

@app.get("/api/unified/events/last")
async def api_unified_events_last():
    try:
        last_id = await asyncio.to_thread(_events_last_id)
        return {"ok": True, "last_id": last_id}
    except Exception as e:
        return {"ok": False, "error": str(e), "last_id": 0}


@app.post("/api/audit/{audit_id}/replay")
async def api_audit_replay(audit_id: int, request: Request):
    """Replay a previously audited action (dev/test helper)."""
    if not AUDIT_ENABLED:
        raise HTTPException(status_code=503, detail="audit_disabled")

    row = await asyncio.to_thread(fetch_audit_event_by_id, AUDIT_DSN, int(audit_id))
    if not row:
        raise HTTPException(status_code=404, detail="audit_not_found")

    action = str(row.get("action") or "").strip()
    role = row.get("role")
    target_id = row.get("target_id")
    body = row.get("request_json") or {}

    if not isinstance(body, dict):
        body = {}

    # Only allow replay of known safe actions
    allowed = {"COMMAND_QUEUE", "SIGNAL_APPROVE", "SIGNAL_REJECT"}
    if action not in allowed:
        raise HTTPException(status_code=400, detail=f"replay_not_supported:{action}")

    if role not in ROLE_URLS:
        raise HTTPException(status_code=400, detail="replay_missing_role")

    base = ROLE_URLS.get(role)

    # Execute with a fresh trace_id (or reuse caller's trace)
    trace_id = _trace_id_from_request(request) or uuid.uuid4().hex
    headers = {"X-API-Key": DASHBOARD_API_KEY, "X-Trace-Id": trace_id}

    # Ensure downstream can persist/link the trace.
    try:
        if isinstance(body, dict) and "trace_id" not in body:
            body = {**body, "trace_id": trace_id}
    except Exception:
        pass

    if action == "COMMAND_QUEUE":
        url = f"{base}/api/commands/queue"
    elif action == "SIGNAL_APPROVE":
        url = f"{base}/api/signals/approve"
    else:
        url = f"{base}/api/signals/reject"

    # Extra safety: replaying a COMMAND_QUEUE must only allow safe commands.
    if action == "COMMAND_QUEUE":
        safe_cmds = {
            "CLOSE_ALL_POSITIONS",
            "CLOSE_TRADE",
            "CHECK_PROTECTION_NOW",
            "KILL_SWITCH_ON",
            "KILL_SWITCH_OFF",
        }
        try:
            cmd = str((body or {}).get("cmd") or "").strip().upper()
        except Exception:
            cmd = ""
        if cmd and cmd not in safe_cmds:
            raise HTTPException(status_code=400, detail=f"replay_unsafe_cmd:{cmd}")
    try:
        result = await _post_json(url, headers=headers, json_body=body)
        audit_id2 = await _audit_write(
            request=request,
            action=f"REPLAY_{action}",
            role=str(role) if role else None,
            target_id=str(target_id) if target_id else None,
            trace_id=trace_id,
            request_json={"source_audit_id": int(audit_id), "replayed_request": body, "original_action": action},
            response_json=result if isinstance(result, dict) else {"result": result},
            ok=True,
        )
        if isinstance(result, dict):
            result = {**result, "trace_id": trace_id, "audit_id": audit_id2, "source_audit_id": int(audit_id)}
        return result
    except HTTPException as e:
        await _audit_write(
            request=request,
            action=f"REPLAY_{action}",
            role=str(role) if role else None,
            target_id=str(target_id) if target_id else None,
            trace_id=trace_id,
            request_json={"source_audit_id": int(audit_id), "replayed_request": body, "original_action": action},
            response_json={"error": e.detail},
            ok=False,
        )
        raise

@app.get("/api/_debug/routes")
async def api_debug_routes():
    """Return registered route paths (debug)."""
    return {"ok": True, "routes": [getattr(r, "path", "") for r in app.routes]}



@app.get("/api/mina/{role}/system_health")
async def mina_system_health(role: Role):
    _validate_role(role)
    schema = _schema_for_role(role)
    return mina_pg.build_system_health(schema, role)


@app.get("/api/mina/{role}/health")
async def mina_health(role: Role):
    _validate_role(role)
    schema = _schema_for_role(role)
    return mina_pg.build_system_health(schema, role)

@app.get("/api/unified/roles")
async def api_unified_roles():
    return {
        "roles": ["paper", "live", "pump"],
        "proxy_example": "/api/mina/paper/signals?limit=10",
        "api_key_header": "X-API-Key",
    }

@app.get("/api/unified/overview")
async def api_unified_overview():
    """Unified overview: Gateway + Brain + DB-backed Mina role snapshots + latest audit/events."""
    out = {
        "schema_version": "v2",
        "ts_utc": None,
        "gateway": {"status": "ok", "service": "gateway"},
        "brain_api": None,
        "brain": None,
        "dashboards": {},
        "audit": None,
        "events": None,
    }
    import datetime as _dt
    out["ts_utc"] = _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    # Brain health + overview (best-effort; UI remains functional if brain_api is down).
    try:
        out["brain_api"] = await _fetch_json(f"{BRAIN_API_URL}/health")
    except HTTPException as e:
        out["brain_api"] = {"ok": False, **_http_exc_detail(e)}
    try:
        out["brain"] = await _fetch_json(f"{BRAIN_API_URL}/api/overview")
    except HTTPException as e:
        out["brain"] = {"ok": False, **_http_exc_detail(e)}

    for role in ("paper", "live", "pump"):
        schema = _schema_for_role(role)
        role_stats = mina_pg.get_stats(schema)
        role_stats.setdefault("trades", int(role_stats.get("total_trades") or role_stats.get("trades") or 0))
        signals_preview = mina_pg.list_signals(schema, limit=5)
        role_out = {
            "stats": role_stats,
            "signals_preview": signals_preview,
            "signals_preview_count": len(signals_preview),
            "system_health": mina_pg.build_system_health(schema, role),
            "schema": schema,
        }
        out["dashboards"][role] = role_out

    # Latest audit/events (best-effort)
    try:
        if AUDIT_ENABLED:
            rows = await asyncio.to_thread(fetch_audit_events, AUDIT_DSN, 5)
            out["audit"] = {"ok": True, "items": rows}
        else:
            out["audit"] = {"ok": False, "error": "audit_disabled"}
    except Exception as e:
        out["audit"] = {"ok": False, "error": str(e)}

    try:
        rows = await _events_fetch(limit=5, order="desc")
        out["events"] = {"ok": True, "items": rows}
    except Exception as e:
        out["events"] = {"ok": False, "error": str(e)}

    return out


@app.get("/api/unified/autopilot")
async def api_unified_autopilot_get():
    return _autopilot_state()

@app.get("/api/autopilot")
async def api_autopilot_get_alias():
    return _autopilot_state()


@app.post("/api/unified/autopilot")
async def api_unified_autopilot_set_global(request: Request):
    body = await request.json()
    mode = _normalize_mode(body.get("global_mode"))
    trace_id = _trace_id_from_request(request)
    actor = _actor_from_request(request)

    _set_gateway_setting(AUTOPILOT_KEYS["global"], mode, updated_by=actor)
    resp = _autopilot_state()
    audit_id = await _audit_write(
        request=request,
        action="AUTOPILOT_SET_GLOBAL",
        role=None,
        target_id="global",
        trace_id=trace_id,
        request_json={"global_mode": mode},
        response_json=resp,
        ok=True,
    )
    return {**resp, "ok": True, "trace_id": trace_id, "audit_id": audit_id}

@app.post("/api/autopilot")
async def api_autopilot_set_global_alias(request: Request):
    return await api_unified_autopilot_set_global(request)


@app.post("/api/unified/autopilot/{role}")
async def api_unified_autopilot_set_role(role: Role, request: Request):
    body = await request.json()
    mode = _normalize_mode(body.get("role_mode"))
    if role == "live":
        _enforce_live_write_confirmation(role="live", action="AUTOPILOT_SET_ROLE", body=body if isinstance(body, dict) else {}, request=request)
    trace_id = _trace_id_from_request(request)
    actor = _actor_from_request(request)

    _set_gateway_setting(AUTOPILOT_KEYS[role], mode, updated_by=actor)
    resp = _autopilot_state()
    audit_id = await _audit_write(
        request=request,
        action="AUTOPILOT_SET_ROLE",
        role=role,
        target_id=role,
        trace_id=trace_id,
        request_json={"role_mode": mode},
        response_json=resp,
        ok=True,
    )
    return {**resp, "ok": True, "trace_id": trace_id, "audit_id": audit_id}

@app.post("/api/autopilot/{role}")
async def api_autopilot_set_role_alias(role: Role, request: Request):
    return await api_unified_autopilot_set_role(role, request)

@app.post("/api/autopilot/shadow_decision")
async def api_autopilot_shadow_decision(request: Request):
    """Record a shadow decision from the autopilot worker (audit + shared_events)."""
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Body must be an object")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    role = body.get("role")
    signal_id = body.get("signal_id")
    trace_id = body.get("trace_id") or _trace_id_from_request(request)
    payload = {
        "role": role,
        "signal_id": signal_id,
        "would_action": body.get("would_action"),
        "reason": body.get("reason"),
        "meta": body.get("meta") or {},
    }

    audit_id = await _audit_write(
        request=request,
        action="AUTOPILOT_SHADOW_DECISION",
        role=str(role) if role else None,
        target_id=str(signal_id) if signal_id is not None else None,
        trace_id=trace_id,
        request_json=payload,
        response_json={"ok": True},
        ok=True,
    )
    return {"ok": True, "trace_id": trace_id, "audit_id": audit_id}


@app.post("/api/autopilot/worker/shadow_decision")
async def api_autopilot_shadow_decision_worker(request: Request):
    # Explicit worker path to avoid ambiguity with /api/autopilot/{role}.
    return await api_autopilot_shadow_decision(request)


@app.post("/api/autopilot/heartbeat")
async def api_autopilot_heartbeat(request: Request):
    """Record a worker heartbeat (audit + shared_events)."""
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}

    trace_id = body.get("trace_id") or _trace_id_from_request(request)
    payload = {
        "last_cycle_utc": body.get("last_cycle_utc"),
        "ok": bool(body.get("ok", True)),
        "last_error": body.get("last_error"),
    }
    audit_id = await _audit_write(
        request=request,
        action="AUTOPILOT_WORKER_HEARTBEAT",
        role=None,
        target_id="worker",
        trace_id=trace_id,
        request_json=payload,
        response_json={"ok": True},
        ok=bool(payload.get("ok", True)),
    )
    return {"ok": True, "trace_id": trace_id, "audit_id": audit_id}


@app.post("/api/autopilot/worker/heartbeat")
async def api_autopilot_heartbeat_worker(request: Request):
    # Explicit worker path to avoid ambiguity with /api/autopilot/{role}.
    return await api_autopilot_heartbeat(request)

@app.post("/api/unified/sync/run")
async def api_unified_sync_run(request: Request):
    """Proxy a Brain sync run then refresh Brain dataset cache (audited)."""
    params = dict(request.query_params)
    role = str(params.get("role") or "paper")
    sync_res = await _audited_post_params(
        request=request,
        action="SYNC_RUN",
        role=role,
        target_id=role,
        url=f"{BRAIN_API_URL}/api/sync/run",
        params=params,
    )
    # Refresh dataset cache (best-effort, not audited)
    trace_val = _trace_id_from_request(request)
    if isinstance(sync_res, dict) and sync_res.get("trace_id"):
        trace_val = str(sync_res.get("trace_id"))
    headers = {"X-Trace-Id": trace_val}
    refresh_res = await _post_json(f"{BRAIN_API_URL}/api/admin/dataset/refresh", headers=headers)
    return {"ok": True, "sync": sync_res, "refresh": refresh_res}

@app.post("/api/unified/sync/reset")
async def api_unified_sync_reset(request: Request, role: str = "paper"):
    """Proxy Brain sync reset (audited)."""
    params = dict(request.query_params)
    params.setdefault("role", role)
    res = await _audited_post_params(
        request=request,
        action="SYNC_RESET",
        role=str(params.get("role") or role),
        target_id=str(params.get("role") or role),
        url=f"{BRAIN_API_URL}/api/sync/reset",
        params=params,
    )
    return res

@app.post("/api/unified/sync/cleanup")
async def api_unified_sync_cleanup(request: Request, role: Optional[str] = None):
    """Proxy Brain sync cleanup (audited)."""
    params = dict(request.query_params)
    if role and "role" not in params:
        params["role"] = role
    role_val = str(params.get("role")) if params.get("role") is not None else None
    res = await _audited_post_params(
        request=request,
        action="SYNC_CLEANUP",
        role=role_val,
        target_id=role_val,
        url=f"{BRAIN_API_URL}/api/sync/cleanup",
        params=params,
    )
    return res

@app.get("/api/unified/sync/status")
async def api_unified_sync_status(role: str = "paper"):
    """Proxy Brain sync status for a role."""
    return await _fetch_json(f"{BRAIN_API_URL}/api/sync/status", params={"role": role})

@app.get("/api/unified/{role}/snapshot")
async def api_unified_role_snapshot(role: Role):
    """One-call snapshot for a single Mina role, sourced from Postgres."""
    _validate_role(role)
    return mina_pg.snapshot(role, signal_limit=10, position_limit=200)



@app.get("/api/unified/{role}/system_health")
async def api_unified_role_system_health(role: Role):
    schema = _schema_for_role(role)
    return mina_pg.build_system_health(schema, role)

@app.get("/api/unified/{role}/stats")
async def api_unified_role_stats(role: Role):
    schema = _schema_for_role(role)
    stats = mina_pg.get_stats(schema)
    trades = int(stats.get("trades") or stats.get("total_trades") or 0)
    return {
        "ok": True,
        "role": role,
        "schema": schema,
        "pnl": float(stats.get("pnl") or 0.0),
        "win_rate": float(stats.get("win_rate") or 0.0),
        "open_positions": int(stats.get("open_positions") or 0),
        "trades": trades,
        "total_trades": trades,
        "wins": int(stats.get("wins") or 0),
    }

@app.get("/api/unified/{role}/positions")
async def api_unified_role_positions(role: Role):
    schema = _schema_for_role(role)
    return mina_pg.list_open_positions(schema, limit=200)

@app.get("/api/unified/{role}/trades")
async def api_unified_role_trades(role: Role, limit: int = 50, status: str | None = None, symbol: str | None = None):
    rows = await _trades_fetch(role=role, limit=limit, status=status, symbol=symbol)
    return {"ok": True, "schema": _schema_for_role(role), "items": jsonable_encoder(rows), "count": len(rows)}

@app.get("/api/unified/{role}/trades/{trade_id}")
async def api_unified_role_trade_detail(role: Role, trade_id: int):
    row = await _trade_fetch_one(role, trade_id)
    if not row:
        raise HTTPException(status_code=404, detail="trade_not_found")
    return {"ok": True, "schema": _schema_for_role(role), "item": jsonable_encoder(row)}

@app.get("/api/unified/{role}/equity_history")
async def api_unified_equity_history(
    role: Role,
    limit: int = 200,
    from_ts: str | None = None,
    to_ts: str | None = None,
):
    schema = _schema_for_role(role)
    try:
        rows = await _equity_history_fetch(role=role, limit=limit, from_ts=from_ts, to_ts=to_ts)
    except HTTPException as e:
        return {
            "ok": False,
            "schema": schema,
            "items": [],
            "count": 0,
            "error": _http_exc_detail(e),
        }
    if not rows:
        return {
            "ok": False,
            "schema": schema,
            "items": [],
            "count": 0,
            "error": "equity_history_not_available",
        }
    return {"ok": True, "schema": schema, "items": jsonable_encoder(rows), "count": len(rows)}

@app.get("/api/unified/{role}/perf_metrics")
async def api_unified_perf_metrics(
    role: Role,
    limit: int = 500,
    from_ts: str | None = None,
    to_ts: str | None = None,
):
    rows = await _perf_metrics_fetch(role=role, limit=limit, from_ts=from_ts, to_ts=to_ts)
    return {"ok": True, "schema": _schema_for_role(role), "items": jsonable_encoder(rows), "count": len(rows)}

@app.get("/api/unified/{role}/commands/history")
async def api_unified_commands_history(role: Role, limit: int = 50):
    schema = _schema_for_role(role)
    if not _table_exists(schema, "commands"):
        return {"ok": True, "role": role, "schema": schema, "items": [], "count": 0}
    lim = max(1, min(int(limit or 50), 500))
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {schema}.commands ORDER BY id DESC LIMIT %s", (lim,))
            rows = [dict(r) for r in (cur.fetchall() or [])]
    return {"ok": True, "role": role, "schema": schema, "items": rows, "count": len(rows)}

@app.get("/api/unified/{role}/signals")
async def api_unified_role_signals(
    role: Role,
    limit: int = 30,
    status: str | None = None,
    source: str | None = None,
    symbol: str | None = None,
    timeframe: str | None = None,
    strategy: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
):
    schema = _schema_for_role(role)
    from_ms = _parse_ts_ms(from_ts or date_from)
    to_ms = _parse_ts_ms(to_ts or date_to)
    rows = mina_pg.list_signals(
        schema,
        status=status,
        source=source,
        symbol=symbol,
        timeframe=timeframe,
        strategy=strategy,
        from_ms=from_ms,
        to_ms=to_ms,
        limit=limit,
    )
    return {
        "ok": True,
        "role": role,
        "schema": schema,
        "items": rows,
        "count": len(rows),
        "filters": {
            "status": status,
            "source": source,
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy": strategy,
            "from_ts": from_ts or date_from,
            "to_ts": to_ts or date_to,
        },
    }

@app.get("/api/unified/{role}/signals/{signal_id}")
async def api_unified_signal_detail(role: Role, signal_id: int):
    schema = _schema_for_role(role)
    row = _fetch_signal_one(schema, int(signal_id))
    if not row:
        raise HTTPException(status_code=404, detail="signal_not_found")
    return {"ok": True, "role": role, "schema": schema, "item": row}
@app.get("/api/unified/{role}/signals/{signal_id}/decision")
async def unified_signal_decision(role: Role, signal_id: int, request: Request):
    """Best-effort decision precheck for a Mina signal, sourced from Postgres."""
    schema = _schema_for_role(role)
    sig = mina_pg.get_signal(schema, int(signal_id))
    if not sig:
        raise HTTPException(status_code=404, detail=f"Signal not found: {signal_id}")

    payload = sig.get("payload") if isinstance(sig.get("payload"), dict) else {}
    symbol = str(payload.get("symbol") or sig.get("symbol") or "").strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Signal has no symbol")

    decision = await _brain_get_json("/api/decision", params={"symbol": symbol})
    trace_id = _trace_id_from_request(request)
    audit_id = None
    if AUDIT_ENABLED:
        try:
            audit_id = await _audit_write(
                request=request,
                action="SIGNAL_DECISION_CHECK",
                role=role,
                target_id=str(signal_id),
                trace_id=trace_id,
                request_json={"signal_id": signal_id, "symbol": symbol},
                response_json={"decision": decision},
                ok=True,
            )
        except Exception:
            audit_id = None

    return {
        "ok": True,
        "role": role,
        "schema": schema,
        "signal": sig,
        "decision": decision,
        "trace_id": trace_id,
        "audit_id": audit_id,
    }



@app.post("/api/unified/{role}/signals/publish")
async def api_unified_signal_publish(role: Role, request: Request):
    """Publish (stage) a signal into {schema}.signal_inbox for the selected role."""
    schema = _schema_for_role(role)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {"raw": body}
    except Exception:
        body = {}

    signal_id = int(mina_pg.publish_signal(schema, body) or 0)
    result = {"status": "published", "id": signal_id, "_dashboard_inbox_id": signal_id}
    await _audit_write(
        request=request,
        action="SIGNAL_PUBLISH",
        role=role,
        target_id=str(signal_id or body.get("symbol") or body.get("pair") or ""),
        trace_id=_trace_id_from_request(request),
        request_json=body,
        response_json=result,
        ok=True,
    )
    return result


@app.post("/api/unified/{role}/publish")
async def api_unified_publish_alias(role: Role, request: Request):
    """Backward-compatible alias for /api/unified/{role}/signals/publish."""
    return await api_unified_signal_publish(role, request)


@app.get("/api/unified/{role}/logs")
async def api_unified_role_logs(role: Role, limit: int = 200):
    schema = _schema_for_role(role)
    rows = mina_pg.list_logs(schema, limit=int(limit))
    return {"ok": True, "role": role, "schema": schema, "items": rows, "count": len(rows)}


@app.get("/api/unified/{role}/settings")
async def api_unified_role_settings(role: Role, request: Request):
    schema = _schema_for_role(role)
    data = _fetch_all_settings(schema)
    trace_id = _trace_id_from_request(request)
    await _audit_write(
        request=request,
        action="SETTINGS_GET",
        role=role,
        target_id=None,
        trace_id=trace_id,
        request_json={},
        response_json={"count": len(data)},
        ok=True,
    )
    return data


@app.post("/api/unified/{role}/settings")
async def api_unified_role_settings_update(role: Role, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    _enforce_live_write_confirmation(role=role, action="SETTINGS_SET", body=body, request=request)
    schema = _schema_for_role(role)
    updated = _upsert_settings(schema, body, source="gateway.unified.settings")
    trace_id = _trace_id_from_request(request)
    await _audit_write(
        request=request,
        action="SETTINGS_SET",
        role=role,
        target_id=None,
        trace_id=trace_id,
        request_json=body,
        response_json={"updated": list(updated.keys())},
        ok=True,
    )
    return {"ok": True, "role": role, "schema": schema, "updated": updated, "count": len(updated)}


@app.get("/api/unified/{role}/env_secrets")
async def api_unified_role_env_secrets(role: Role, request: Request):
    schema = _schema_for_role(role)
    settings = _fetch_all_settings(schema)
    # Keep backward-compatible env secret surface: return only likely secret/env keys.
    out = {
        k: v
        for k, v in settings.items()
        if any(x in k.upper() for x in ("KEY", "SECRET", "TOKEN", "CHAT", "WEBHOOK", "URL", "PASS"))
    }
    trace_id = _trace_id_from_request(request)
    await _audit_write(
        request=request,
        action="ENV_SECRETS_GET",
        role=role,
        target_id=None,
        trace_id=trace_id,
        request_json={},
        response_json={"count": len(out)},
        ok=True,
    )
    return out


@app.post("/api/unified/{role}/env_secrets")
async def api_unified_role_env_secrets_update(role: Role, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    _enforce_live_write_confirmation(role=role, action="ENV_SECRETS_SET", body=body, request=request)
    schema = _schema_for_role(role)
    updated = _upsert_settings(schema, body, source="gateway.unified.env")
    trace_id = _trace_id_from_request(request)
    await _audit_write(
        request=request,
        action="ENV_SECRETS_SET",
        role=role,
        target_id=None,
        trace_id=trace_id,
        request_json={k: "***" for k in body.keys()},
        response_json={"updated": list(updated.keys())},
        ok=True,
    )
    return {"ok": True, "role": role, "schema": schema, "updated": list(updated.keys()), "count": len(updated)}


@app.post("/api/unified/{role}/control/restart_bot")
async def api_unified_control_restart_bot(role: Role, request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}
    _enforce_live_write_confirmation(role=role, action="CONTROL_RESTART_BOT", body=body, request=request)
    trace_id = _trace_id_from_request(request)
    queued = _queue_role_command(
        role=role,
        cmd="BOT_RESTART",
        params={"reason": "gateway_restart_bot"},
        trace_id=trace_id,
        request_payload={"target": "bot", "action": "restart"},
    )
    await _audit_write(
        request=request,
        action="CONTROL_RESTART_BOT",
        role=role,
        target_id="restart_bot",
        trace_id=trace_id,
        request_json={},
        response_json=queued,
        ok=True,
    )
    return {"ok": True, "role": role, "trace_id": trace_id, **queued}


@app.post("/api/unified/{role}/control/restart_monitor")
async def api_unified_control_restart_monitor(role: Role, request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}
    _enforce_live_write_confirmation(role=role, action="CONTROL_RESTART_MONITOR", body=body, request=request)
    trace_id = _trace_id_from_request(request)
    queued = _queue_role_command(
        role=role,
        cmd="MONITOR_RESTART",
        params={"reason": "gateway_restart_monitor"},
        trace_id=trace_id,
        request_payload={"target": "monitor", "action": "restart"},
    )
    await _audit_write(
        request=request,
        action="CONTROL_RESTART_MONITOR",
        role=role,
        target_id="restart_monitor",
        trace_id=trace_id,
        request_json={},
        response_json=queued,
        ok=True,
    )
    return {"ok": True, "role": role, "trace_id": trace_id, **queued}


@app.post("/api/unified/{role}/control/clear_kill_switch")
async def api_unified_control_clear_kill_switch(role: Role, request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}
    _enforce_live_write_confirmation(role=role, action="CONTROL_CLEAR_KILL_SWITCH", body=body, request=request)
    trace_id = _trace_id_from_request(request)
    queued = _queue_role_command(
        role=role,
        cmd="KILL_SWITCH_OFF",
        params={"reason": "clear_kill_switch"},
        trace_id=trace_id,
        request_payload={"target": "bot", "action": "clear_kill_switch"},
    )
    try:
        schema = _schema_for_role(role)
        _set_setting(schema, "kill_switch", "0", source="gateway.clear_kill_switch")
        _set_setting(schema, "kill_switch_reason", "", source="gateway.clear_kill_switch")
    except Exception:
        pass
    await _audit_write(
        request=request,
        action="CONTROL_CLEAR_KILL_SWITCH",
        role=role,
        target_id="clear_kill_switch",
        trace_id=trace_id,
        request_json={},
        response_json=queued,
        ok=True,
    )
    return {"ok": True, "role": role, "trace_id": trace_id, **queued}

@app.post("/api/unified/{role}/signals/{signal_id}/approve")
async def api_unified_signal_approve(role: Role, signal_id: int, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    _enforce_live_write_confirmation(role=role, action="SIGNAL_APPROVE", body=body, request=request)
    note = str(body.get("note") or "")
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    result = _approve_signal_from_db(role, int(signal_id), note=note, payload=payload)
    await _audit_write(
        request=request,
        action="SIGNAL_APPROVE",
        role=role,
        target_id=str(signal_id),
        trace_id=str(result.get("trace_id") or _trace_id_from_request(request)),
        request_json={"id": int(signal_id), "note": note},
        response_json={"ok": True, "command_id": result.get("command_id")},
        ok=True,
    )
    return result

@app.post("/api/unified/{role}/signals/{signal_id}/reject")
async def api_unified_signal_reject(role: Role, signal_id: int, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    _enforce_live_write_confirmation(role=role, action="SIGNAL_REJECT", body=body, request=request)
    reason = str(body.get("reason") or "Rejected from Unified UI")
    note = str(body.get("note") or "")
    result = _reject_signal_from_db(role, int(signal_id), reason=reason, note=note)
    await _audit_write(
        request=request,
        action="SIGNAL_REJECT",
        role=role,
        target_id=str(signal_id),
        trace_id=_trace_id_from_request(request),
        request_json={"id": int(signal_id), "reason": reason, "note": note},
        response_json={"ok": True},
        ok=True,
    )
    return result



@app.post("/api/unified/{role}/signals/suggest_from_decision")
async def unified_suggest_signal_from_decision(role: Role, request: Request):
    """
    Shadow bridge: call Brain /api/decision and, if viable, publish a suggestion into the selected Mina role's inbox.
    This does NOT approve/execute — it only creates a new inbox signal with the Brain decision attached in payload.
    """
    _validate_role(role)

    # Symbol can be passed as query (?symbol=BTCUSDT) or in JSON body
    body: Dict[str, Any] = {}
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}

    symbol = (request.query_params.get("symbol") or body.get("symbol") or "").strip().upper()
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol is required (query param or JSON body)")

    side = (body.get("side") or "").strip().upper()
    if side not in ("BUY", "SELL"):
        raise HTTPException(status_code=422, detail="side is required and must be BUY or SELL")

    timeframe = (body.get("timeframe") or "1m").strip()
    note = (body.get("note") or "").strip()
    strategy = (body.get("strategy") or "").strip()

    # 1) Ask Brain for a decision (gateway already exposes /api/decision proxy, but we call Brain directly here)
    decision = await _fetch_json(f"{BRAIN_API_URL}/api/decision", params={"symbol": symbol})

    decision_label = ""
    try:
        decision_label = str(decision.get("decision") or "")
    except Exception:
        decision_label = ""

    if decision_label in ("DO_NOT_TRADE", "NO_TRADE", "ABSTAIN"):
        # Nothing to stage
        await _audit_write(
            request=request,
            action="BRAIN_SUGGEST_SIGNAL",
            role=str(role),
            target_id=symbol,
            trace_id=_trace_id_from_request(request),
            request_json={"symbol": symbol, "side": side, "timeframe": timeframe, "note": note, "strategy": strategy, "decision": decision},
            response_json={"ok": False, "reason": "Brain decision is not tradable", "decision": decision},
            ok=False,
        )
        return JSONResponse({"ok": False, "reason": "Brain decision is not tradable", "decision": decision}, status_code=409)

    confidence = 0.0
    try:
        confidence = float(decision.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0

    inferred_strategy = strategy or (decision.get("recommended_strategy") or "")
    if not inferred_strategy:
        inferred_strategy = "brain_decision"

    publish_payload = {
        "symbol": symbol,
        "timeframe": timeframe,
        "strategy": inferred_strategy,
        "side": side,
        "confidence": confidence if confidence > 0 else 0.5,
        "score": confidence if confidence > 0 else 0.5,
        "note": note or f"brain:{decision_label}",
        "payload": {
            "source": "gateway",
            "brain_decision": decision,
        },
    }

    schema = _schema_for_role(role)
    signal_id = int(mina_pg.publish_signal(schema, publish_payload) or 0)
    upstream = {
        "status": "published",
        "id": signal_id,
        "_dashboard_inbox_id": signal_id,
    }
    await _audit_write(
        request=request,
        action="BRAIN_SUGGEST_SIGNAL",
        role=str(role),
        target_id=str(signal_id or symbol),
        trace_id=_trace_id_from_request(request),
        request_json=publish_payload,
        response_json={**upstream, "decision": decision},
        ok=True,
    )

    # include the decision for the UI
    try:
        upstream["decision"] = decision
    except Exception:
        pass

    return JSONResponse(upstream)

@app.post("/api/unified/{role}/commands/close_all")
async def api_unified_command_close_all(role: Role, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    _enforce_live_write_confirmation(role=role, action="COMMAND_CLOSE_ALL", body=body, request=request)
    reason = str((body or {}).get("reason") or "close_all").strip()
    trace_id = _trace_id_from_request(request)
    queued = _queue_role_command(
        role=role,
        cmd="CLOSE_ALL_POSITIONS",
        params={"reason": reason},
        trace_id=trace_id,
        request_payload={"cmd": "CLOSE_ALL_POSITIONS", "params": {"reason": reason}},
    )
    await _audit_write(
        request=request,
        action="COMMAND_QUEUE",
        role=role,
        target_id="CLOSE_ALL_POSITIONS",
        trace_id=trace_id,
        request_json={"reason": reason},
        response_json=queued,
        ok=True,
    )
    return {"ok": True, "role": role, "trace_id": trace_id, **queued}

@app.post("/api/unified/{role}/commands/kill_switch")
async def api_unified_command_kill_switch(role: Role, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    _enforce_live_write_confirmation(role=role, action="COMMAND_KILL_SWITCH", body=body, request=request)
    enabled_raw = (body or {}).get("enabled", True)
    enabled = bool(enabled_raw)
    if isinstance(enabled_raw, str):
        enabled = enabled_raw.strip().lower() in ("1", "true", "yes", "on")
    cmd = "KILL_SWITCH_ON" if enabled else "KILL_SWITCH_OFF"
    reason_default = "kill_switch_on" if enabled else "kill_switch_off"
    reason = str((body or {}).get("reason") or reason_default).strip()
    trace_id = _trace_id_from_request(request)
    queued = _queue_role_command(
        role=role,
        cmd=cmd,
        params={"reason": reason, "enabled": enabled},
        trace_id=trace_id,
        request_payload={"cmd": cmd, "params": {"reason": reason, "enabled": enabled}},
    )
    # Keep role setting in sync for status views.
    try:
        _set_setting(_schema_for_role(role), "kill_switch", "1" if enabled else "0", source="gateway.kill_switch")
        if reason:
            _set_setting(_schema_for_role(role), "kill_switch_reason", reason, source="gateway.kill_switch")
    except Exception:
        pass
    await _audit_write(
        request=request,
        action="COMMAND_QUEUE",
        role=role,
        target_id=cmd,
        trace_id=trace_id,
        request_json={"enabled": enabled, "reason": reason},
        response_json=queued,
        ok=True,
    )
    return {"ok": True, "role": role, "trace_id": trace_id, **queued}

@app.post("/api/unified/{role}/commands")
async def api_unified_queue_command(role: Role, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    _enforce_live_write_confirmation(role=role, action="COMMAND_QUEUE", body=body, request=request)
    cmd = str(body.get("cmd") or "").strip().upper()
    params = body.get("params") if isinstance(body.get("params"), dict) else {}
    if not cmd:
        raise HTTPException(status_code=400, detail="cmd is required")
    trace_id = _trace_id_from_request(request)
    queued = _queue_role_command(
        role=role,
        cmd=cmd,
        params=params,
        trace_id=trace_id,
        request_payload={"cmd": cmd, "params": params},
    )
    await _audit_write(
        request=request,
        action="COMMAND_QUEUE",
        role=role,
        target_id=cmd,
        trace_id=trace_id,
        request_json={"cmd": cmd, "params": params},
        response_json=queued,
        ok=True,
    )
    return {"ok": True, "role": role, "trace_id": trace_id, **queued}


# ---------------------------
# Phase 4: Ops Live endpoints
# ---------------------------

@app.get("/api/ops/status")
async def api_ops_status(role: str | None = None):
    roles = _resolve_roles(role)
    out: dict[str, Any] = {"ok": True, "roles": {}}
    for r in roles:
        schema = _schema_for_role(r)
        settings = _fetch_settings(schema, [
            "execution_monitor_heartbeat",
            "last_heartbeat",
            "bot_heartbeat",
            "kill_switch",
            "last_decision",
            "version",
            "bot_version",
        ])
        last_heartbeat = settings.get("execution_monitor_heartbeat") or settings.get("last_heartbeat") or settings.get("bot_heartbeat")

        last_error = None
        try:
            rows = _fetch_logs(schema, level="ERROR", limit=1)
            if rows:
                row = rows[0]
                cols = set(row.keys())
                last_error = {
                    "level": row.get("level") or row.get("lvl"),
                    "msg": row.get("message") or row.get("msg"),
                    "source": row.get("source"),
                    "ts": _safe_ts_value(row, cols, ["timestamp", "time", "created_at", "timestamp_ms", "created_at_ms"]),
                }
        except Exception:
            last_error = None

        out["roles"][r] = {
            "schema": schema,
            "kill_switch": settings.get("kill_switch"),
            "last_heartbeat": last_heartbeat,
            "last_decision": settings.get("last_decision"),
            "version": settings.get("version") or settings.get("bot_version"),
            "last_error": last_error,
        }
    return out


@app.get("/api/unified/status")
async def api_unified_status(role: str | None = None):
    return await api_ops_status(role)


@app.get("/api/ops/positions")
async def api_ops_positions(role: str = "live", limit: int = 100):
    roles = _resolve_roles(role)
    items: list[dict] = []
    for r in roles:
        schema = _schema_for_role(r)
        if _table_exists(schema, "positions"):
            with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT * FROM {schema}.positions ORDER BY id DESC LIMIT %s", (int(limit),))
                    rows = list(cur.fetchall())
        else:
            rows = []
            try:
                rows = await _trades_fetch(role=r, limit=limit, status="OPEN")
            except Exception:
                rows = []
        for row in rows:
            row = dict(row)
            row["role"] = r
            items.append(row)
    return {"ok": True, "items": jsonable_encoder(items), "count": len(items)}


@app.get("/api/unified/positions")
async def api_unified_positions(role: str = "all", limit: int = 100):
    return await api_ops_positions(role=role, limit=limit)


@app.get("/api/ops/errors")
async def api_ops_errors(role: str = "all", since: str | None = None, limit: int = 200):
    roles = _resolve_roles(role)
    since_ms = _parse_ts_ms(since)
    items: list[dict] = []
    for r in roles:
        schema = _schema_for_role(r)
        rows = _fetch_logs(schema, level="ERROR", since_ms=since_ms, limit=limit)
        for row in rows:
            item = dict(row)
            item["role"] = r
            items.append(item)
    return {"ok": True, "items": jsonable_encoder(items), "count": len(items)}


@app.get("/api/unified/errors")
async def api_unified_errors(role: str = "all", limit: int = 200):
    return await api_ops_errors(role=role, limit=limit)


@app.get("/api/unified/logs")
async def api_unified_logs(role: str = "all", level: str | None = None, contains: str | None = None, limit: int = 200):
    return await api_ops_logs(role=role, level=level, contains=contains, limit=limit)


@app.get("/api/ops/logs")
async def api_ops_logs(role: str = "all", level: str | None = None, contains: str | None = None, limit: int = 200):
    roles = _resolve_roles(role)
    items: list[dict] = []
    for r in roles:
        schema = _schema_for_role(r)
        rows = _fetch_logs(schema, level=level or None, contains=contains or None, limit=limit)
        for row in rows:
            item = dict(row)
            item["role"] = r
            items.append(item)
    return {"ok": True, "items": jsonable_encoder(items), "count": len(items)}


@app.get("/api/ops/logs/stream")
async def api_ops_logs_stream(
    request: Request,
    role: str = "all",
    service: str | None = None,
    level: str | None = None,
    contains: str | None = None,
    poll_s: float = 1.0,
):
    roles = _resolve_roles(role)

    async def event_gen():
        last_ids: dict[str, int] = {r: 0 for r in roles}
        while True:
            if await request.is_disconnected():
                break
            for r in roles:
                schema = _schema_for_role(r)
                if not _table_exists(schema, "logs"):
                    continue
                cols = _table_columns(schema, "logs")
                id_col = "id" if "id" in cols else None
                if not id_col:
                    continue
                where = [f"{id_col} > %s"]
                params: list[object] = [last_ids.get(r, 0)]
                if level and "level" in cols:
                    where.append("level ILIKE %s")
                    params.append(f"%{level}%")
                if service and "source" in cols:
                    where.append("source ILIKE %s")
                    params.append(f"%{service}%")
                if contains:
                    msg_col = "message" if "message" in cols else ("msg" if "msg" in cols else None)
                    if msg_col:
                        where.append(f"{msg_col} ILIKE %s")
                        params.append(f"%{contains}%")
                q = f"SELECT * FROM {schema}.logs WHERE " + " AND ".join(where) + f" ORDER BY {id_col} ASC LIMIT 200"
                with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
                    with conn.cursor() as cur:
                        cur.execute(q, params)
                        rows = list(cur.fetchall())
                        for row in rows:
                            last_ids[r] = max(last_ids.get(r, 0), int(row.get(id_col) or 0))
                            payload = {"role": r, "row": row}
                            yield f"data: {json.dumps(payload, default=str)}\n\n"
            await asyncio.sleep(max(0.5, float(poll_s or 1.0)))

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.get("/api/pipeline/status")
async def api_pipeline_status(role: str = "all"):
    roles = _resolve_roles(role)
    out: dict[str, Any] = {"ok": True, "roles": {}, "brain_sync": {}}
    headers = {"X-API-Key": DASHBOARD_API_KEY} if DASHBOARD_API_KEY else {}
    for r in roles:
        base = ROLE_URLS.get(r)
        if not base:
            out["roles"][r] = {"ok": False, "error": "unknown_role"}
            continue
        try:
            out["roles"][r] = await _fetch_json(f"{base}/api/pipeline/status", headers=headers)
        except HTTPException as e:
            out["roles"][r] = _http_exc_detail(e)
        try:
            out["brain_sync"][r] = await _brain_get_json("/api/sync/status", params={"role": r})
        except Exception:
            out["brain_sync"][r] = {"ok": False}
    return out


@app.post("/api/ops/command")
async def api_ops_command(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    role = str(body.get("role") or "").strip().lower()
    target = str(body.get("target") or "").strip().lower()
    action = str(body.get("action") or "").strip().lower()
    reason = str(body.get("reason") or "").strip()
    force = bool(body.get("force", False))
    if not role:
        raise HTTPException(status_code=400, detail="role is required")
    if role != "all":
        role = _validate_role(role)
    if target not in ("bot", "monitor", "pump"):
        raise HTTPException(status_code=400, detail="invalid target")
    if action not in ("start", "stop", "restart", "reload_config"):
        raise HTTPException(status_code=400, detail="invalid action")
    if role in ("live", "all"):
        _enforce_live_write_confirmation(role="live", action="OPS_COMMAND", body=body, request=request)

    trace_id = _trace_id_from_request(request)
    actor = _actor_from_request(request)
    dedupe_key = body.get("command_id") or body.get("dedupe_key")

    cmd = f"{target.upper()}_{action.upper()}"
    payload = {"role": role, "target": target, "action": action, "reason": reason}

    rows = []
    roles = _resolve_roles(role)
    for r in roles:
        row = _insert_command_queue(
            role=r,
            target=target,
            action=action,
            payload=payload,
            trace_id=trace_id,
            dedupe_key=f"{dedupe_key}:{r}" if dedupe_key else None,
            force=force,
        )
        rows.append(row)
        try:
            _mirror_command_to_mina(_schema_for_role(r), cmd, {"reason": reason}, trace_id)
        except Exception:
            pass
        # Restart actions are now consumed via commands queue (preferred).

    audit_id = await _audit_write(
        request=request,
        action="OPS_COMMAND",
        role=None if role == "all" else role,
        target_id=cmd,
        trace_id=trace_id,
        request_json=payload,
        response_json={"queued": True, "command_id": (rows[0].get("id") if rows else None)},
        ok=True,
    )

    return {"ok": True, "commands": rows, "trace_id": trace_id, "audit_id": audit_id}


# ---------------------------
# Phase 4: Portfolio endpoints
# ---------------------------

@app.post("/api/integrations/binance/connect")
async def api_binance_connect(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    api_key = str(body.get("api_key") or "").strip()
    api_secret = str(body.get("api_secret") or "").strip()
    testnet = bool(body.get("testnet", False))
    if not api_key or not api_secret:
        raise HTTPException(status_code=400, detail="api_key and api_secret required")
    _save_integration_secret("binance", {"api_key": api_key, "api_secret": api_secret, "testnet": testnet})
    return {"ok": True}


@app.post("/api/integrations/binance/disconnect")
async def api_binance_disconnect():
    _ensure_gateway_phase4_tables(AUDIT_DSN)
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM gateway.integration_secrets WHERE name = %s", ("binance",))
    return {"ok": True}


@app.get("/api/integrations/binance/status")
async def api_binance_status(check: bool = False):
    try:
        secret = _load_integration_secret("binance")
    except Exception as e:
        return {"ok": False, "has_credentials": False, "error": "secret_load_failed", "detail": str(e)}

    if not secret:
        return {
            "ok": True,
            "has_credentials": False,
            "connected": False,
            "testnet": True,
            "api_key_hint": "",
            "error": "not_connected",
        }

    api_key = str(secret.get("api_key") or "").strip()
    api_secret = str(secret.get("api_secret") or "").strip()
    testnet = bool(secret.get("testnet", False))
    has_credentials = bool(api_key and api_secret)
    key_hint = f"{api_key[:3]}***{api_key[-3:]}" if len(api_key) >= 6 else ("***" if api_key else "")
    result: Dict[str, Any] = {
        "ok": True,
        "has_credentials": has_credentials,
        "connected": False,
        "testnet": testnet,
        "api_key_hint": key_hint,
        "error": None if has_credentials else "invalid_saved_credentials",
    }
    if check and has_credentials:
        probe = await api_binance_test()
        result.update(
            {
                "connected": bool(probe.get("connected")),
                "error": probe.get("error"),
                "suggested_testnet": probe.get("suggested_testnet"),
                "spot": probe.get("spot"),
                "futures": probe.get("futures"),
            }
        )
    return result


def _bool_from_setting(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v or "").strip().lower()
    return s in {"1", "true", "yes", "on", "y", "t"}


def _normalize_project_mode(v: Any) -> str:
    m = str(v or "").strip().upper()
    if m in {"TEST", "TESTNET", "DEMO"}:
        return "TESTNET"
    if m in {"LIVE", "MAINNET", "PROD", "PRODUCTION"}:
        return "LIVE"
    raise HTTPException(status_code=400, detail="mode must be TESTNET or LIVE")


def _project_mode_payload(role: str, mode: str) -> Dict[str, str]:
    # paper is always safe simulation, even when project mode is LIVE.
    if role == "paper":
        return {"mode": "PAPER", "RUN_MODE": "PAPER", "USE_TESTNET": "TRUE"}
    if mode == "TESTNET":
        return {"mode": "TEST", "RUN_MODE": "TEST", "USE_TESTNET": "TRUE"}
    return {"mode": "LIVE", "RUN_MODE": "LIVE", "USE_TESTNET": "FALSE"}


def _project_mode_state() -> Dict[str, Any]:
    roles_out: Dict[str, Dict[str, Any]] = {}
    live_like_roles = ("live", "pump")
    live_like_live = 0
    for role in ("paper", "live", "pump"):
        schema = _schema_for_role(role)
        s = _fetch_settings(schema, ["mode", "RUN_MODE", "USE_TESTNET", "use_testnet", "kill_switch"])
        mode = str(s.get("mode") or s.get("RUN_MODE") or "").strip().upper()
        use_testnet_raw = s.get("USE_TESTNET")
        if use_testnet_raw is None:
            use_testnet_raw = s.get("use_testnet")
        if use_testnet_raw is None:
            use_testnet = mode in {"TEST", "PAPER"}
        else:
            use_testnet = _bool_from_setting(use_testnet_raw)
        effective = "LIVE" if (mode == "LIVE" and not use_testnet) else "TESTNET"
        if role in live_like_roles and effective == "LIVE":
            live_like_live += 1
        roles_out[role] = {
            "mode": mode or "UNKNOWN",
            "use_testnet": use_testnet,
            "kill_switch": str(s.get("kill_switch") or ""),
            "effective_mode": effective,
        }
    project_mode = "LIVE" if live_like_live == len(live_like_roles) else "TESTNET"
    return {"ok": True, "project_mode": project_mode, "roles": roles_out}


@app.get("/api/project/mode")
async def api_project_mode_get():
    return _project_mode_state()


@app.post("/api/project/mode")
async def api_project_mode_set(request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Body must be an object")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    target_mode = _normalize_project_mode(body.get("mode") or body.get("target"))
    if target_mode == "LIVE":
        _enforce_live_write_confirmation(role="live", action="PROJECT_MODE_SET_LIVE", body=body, request=request)
    trace_id = _trace_id_from_request(request)
    actor = _actor_from_request(request)
    applied: Dict[str, Dict[str, Any]] = {}
    for role in ("paper", "live", "pump"):
        schema = _schema_for_role(role)
        before = _fetch_settings(schema, ["mode", "RUN_MODE", "USE_TESTNET"])
        payload = _project_mode_payload(role, target_mode)
        for key, value in payload.items():
            _set_setting(schema, key, value, source=f"gateway.project_mode.{target_mode.lower()}")
        after = _fetch_settings(schema, ["mode", "RUN_MODE", "USE_TESTNET"])
        applied[role] = {"before": before, "after": after}

    state = _project_mode_state()
    response = {
        **state,
        "target_mode": target_mode,
        "applied": applied,
        "trace_id": trace_id,
    }
    audit_id = await _audit_write(
        request=request,
        action="PROJECT_MODE_SET",
        role=None,
        target_id=target_mode,
        trace_id=trace_id,
        request_json={"mode": target_mode},
        response_json={"project_mode": state.get("project_mode"), "roles": state.get("roles")},
        ok=True,
    )
    return {**response, "audit_id": audit_id, "actor": actor}


def _live_rollout_profile(stage: str) -> Dict[str, str]:
    s = str(stage or "").strip().upper()
    if s == "LIVE-1":
        return {
            LIVE_POLICY_KEYS["rollout_stage"]: "LIVE-1",
            LIVE_POLICY_KEYS["execution_enabled"]: "1",
            LIVE_POLICY_KEYS["max_open_positions"]: "1",
            LIVE_POLICY_KEYS["max_notional"]: "500",
            LIVE_POLICY_KEYS["max_daily_loss"]: "100",
            LIVE_POLICY_KEYS["max_leverage"]: "3",
            LIVE_POLICY_KEYS["cooldown_sec"]: "120",
            AUTOPILOT_KEYS["live"]: "OFF",
        }
    if s == "LIVE-2":
        return {
            LIVE_POLICY_KEYS["rollout_stage"]: "LIVE-2",
            LIVE_POLICY_KEYS["execution_enabled"]: "1",
            LIVE_POLICY_KEYS["max_open_positions"]: "3",
            LIVE_POLICY_KEYS["max_notional"]: "2500",
            LIVE_POLICY_KEYS["max_daily_loss"]: "300",
            LIVE_POLICY_KEYS["max_leverage"]: "5",
            LIVE_POLICY_KEYS["cooldown_sec"]: "30",
            AUTOPILOT_KEYS["live"]: "OFF",
        }
    return {
        LIVE_POLICY_KEYS["rollout_stage"]: "LIVE-0",
        LIVE_POLICY_KEYS["execution_enabled"]: "0",
        LIVE_POLICY_KEYS["max_open_positions"]: "1",
        LIVE_POLICY_KEYS["max_notional"]: "500",
        LIVE_POLICY_KEYS["max_daily_loss"]: "100",
        LIVE_POLICY_KEYS["max_leverage"]: "3",
        LIVE_POLICY_KEYS["cooldown_sec"]: "120",
        AUTOPILOT_KEYS["live"]: "SHADOW",
    }


@app.get("/api/live/safety_policy")
async def api_live_safety_policy_get(include_runtime: bool = True):
    policy = _get_live_safety_policy(mask_pin=True)
    runtime = _live_runtime_snapshot() if include_runtime else {}
    return {
        "ok": True,
        "policy": policy,
        "runtime": runtime,
        "rollout": {
            "stage": policy.get("rollout_stage"),
            "stages": list(LIVE_ROLLOUT_STAGES),
        },
    }


@app.post("/api/live/safety_policy")
async def api_live_safety_policy_set(request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Body must be an object")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    _enforce_live_write_confirmation(role="live", action="LIVE_POLICY_SET", body=body, request=request)
    actor = _actor_from_request(request)
    trace_id = _trace_id_from_request(request)
    current = _get_live_safety_policy(mask_pin=False)
    updated_pairs: Dict[str, str] = {}

    if "execution_enabled" in body:
        updated_pairs[LIVE_POLICY_KEYS["execution_enabled"]] = "1" if _as_bool(body.get("execution_enabled"), False) else "0"
    if "double_confirm_required" in body:
        updated_pairs[LIVE_POLICY_KEYS["double_confirm_required"]] = "1" if _as_bool(body.get("double_confirm_required"), True) else "0"
    if "pin_enabled" in body:
        updated_pairs[LIVE_POLICY_KEYS["pin_enabled"]] = "1" if _as_bool(body.get("pin_enabled"), False) else "0"
    if "max_daily_loss" in body:
        updated_pairs[LIVE_POLICY_KEYS["max_daily_loss"]] = str(max(0.0, _as_float(body.get("max_daily_loss"), 0.0)))
    if "max_open_positions" in body:
        updated_pairs[LIVE_POLICY_KEYS["max_open_positions"]] = str(max(0, _as_int(body.get("max_open_positions"), 0)))
    if "max_leverage" in body:
        updated_pairs[LIVE_POLICY_KEYS["max_leverage"]] = str(max(0.0, _as_float(body.get("max_leverage"), 0.0)))
    if "max_notional" in body:
        updated_pairs[LIVE_POLICY_KEYS["max_notional"]] = str(max(0.0, _as_float(body.get("max_notional"), 0.0)))
    if "cooldown_sec" in body:
        updated_pairs[LIVE_POLICY_KEYS["cooldown_sec"]] = str(max(0, _as_int(body.get("cooldown_sec"), 0)))
    if "rollout_stage" in body:
        stage = str(body.get("rollout_stage") or "").strip().upper()
        if stage in LIVE_ROLLOUT_STAGES:
            updated_pairs[LIVE_POLICY_KEYS["rollout_stage"]] = stage

    pin_raw = body.get("live_pin")
    if pin_raw is not None:
        pin_txt = str(pin_raw or "").strip()
        if pin_txt:
            updated_pairs[LIVE_POLICY_KEYS["pin_hash"]] = hash_secret(pin_txt)
            updated_pairs[LIVE_POLICY_KEYS["pin_enabled"]] = "1"
        else:
            updated_pairs[LIVE_POLICY_KEYS["pin_hash"]] = ""
    if _as_bool(body.get("clear_pin"), False):
        updated_pairs[LIVE_POLICY_KEYS["pin_hash"]] = ""
        updated_pairs[LIVE_POLICY_KEYS["pin_enabled"]] = "0"

    for key, value in updated_pairs.items():
        old_val = _get_gateway_setting(key, "")
        _set_gateway_setting(key, str(value), updated_by=actor)
        _audit_settings_change(key, old_val, str(value), trace_id, actor)

    # Keep role-local compatibility setting updated.
    try:
        live_schema = _schema_for_role("live")
        if LIVE_POLICY_KEYS["execution_enabled"] in updated_pairs:
            _set_setting(
                live_schema,
                "live_execution_enabled",
                "1" if _as_bool(updated_pairs[LIVE_POLICY_KEYS["execution_enabled"]], False) else "0",
                source="gateway.live_policy",
            )
    except Exception:
        pass

    refreshed = _get_live_safety_policy(mask_pin=True)
    runtime = _live_runtime_snapshot()
    return {
        "ok": True,
        "trace_id": trace_id,
        "policy_before": {
            **current,
            "pin_hash": "",
        },
        "policy": refreshed,
        "runtime": runtime,
        "updated_keys": list(updated_pairs.keys()),
    }


@app.get("/api/live/rollout")
async def api_live_rollout_get():
    policy = _get_live_safety_policy(mask_pin=True)
    return {
        "ok": True,
        "stage": policy.get("rollout_stage"),
        "stages": list(LIVE_ROLLOUT_STAGES),
        "policy": policy,
        "runtime": _live_runtime_snapshot(),
    }


@app.post("/api/live/rollout")
async def api_live_rollout_set(request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Body must be an object")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    stage = str(body.get("stage") or body.get("rollout_stage") or "").strip().upper()
    if stage not in LIVE_ROLLOUT_STAGES:
        raise HTTPException(status_code=400, detail=f"stage must be one of {', '.join(LIVE_ROLLOUT_STAGES)}")
    _enforce_live_write_confirmation(role="live", action="LIVE_ROLLOUT_SET", body=body, request=request)
    actor = _actor_from_request(request)
    trace_id = _trace_id_from_request(request)
    profile = _live_rollout_profile(stage)
    for key, value in profile.items():
        old_val = _get_gateway_setting(key, "")
        _set_gateway_setting(key, value, updated_by=actor)
        _audit_settings_change(key, old_val, value, trace_id, actor)

    try:
        live_schema = _schema_for_role("live")
        _set_setting(
            live_schema,
            "live_execution_enabled",
            "1" if profile.get(LIVE_POLICY_KEYS["execution_enabled"]) == "1" else "0",
            source="gateway.live_rollout",
        )
    except Exception:
        pass

    return await api_live_rollout_get()


def _strategies_payload(role: str = "all") -> Dict[str, Any]:
    roles = _resolve_roles(role)
    registry = _strategy_registry_rows()
    configs = _strategy_config_rows(role if role not in {"all", "*"} else None)
    cfg_map: Dict[str, Dict[str, Any]] = {r: {} for r in roles}
    for row in configs:
        rr = str(row.get("role") or "").strip().lower()
        sid = str(row.get("strategy_id") or "").strip().upper()
        if rr in cfg_map and sid:
            cfg_map[rr][sid] = row
    runtime_rows = _role_runtime_rows(role if role not in {"all", "*"} else None)
    runtime_map = {str(x.get("role") or ""): x for x in runtime_rows}
    profile_map = {str(x.get("profile_id") or ""): x for x in _risk_profile_rows()}
    role_metrics = {r: _role_trade_runtime_metrics(r) for r in roles}
    return {
        "ok": True,
        "role": role,
        "roles": roles,
        "registry": registry,
        "configs": cfg_map,
        "runtime": runtime_map,
        "risk_profiles": profile_map,
        "metrics": role_metrics,
    }


@app.get("/api/strategies")
async def api_strategies_get(role: str = "all"):
    return _strategies_payload(role=role)


@app.post("/api/strategies")
async def api_strategies_update(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    _ensure_strategy_risk_tables()
    actor = _actor_from_request(request)
    trace_id = _trace_id_from_request(request)
    rows_in = body.get("items") if isinstance(body.get("items"), list) else [body]
    updated: list[dict[str, Any]] = []
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            for raw in rows_in:
                if not isinstance(raw, dict):
                    continue
                strategy_id = str(raw.get("strategy_id") or "").strip().upper()
                role = str(raw.get("role") or "").strip().lower()
                if not strategy_id:
                    raise HTTPException(status_code=400, detail="strategy_id is required")
                role = _validate_role(role)
                if role == "live":
                    _enforce_live_write_confirmation(role="live", action="STRATEGY_CONFIG_SET", body=raw, request=request)
                enabled = bool(raw.get("enabled", True))
                params_json = raw.get("params_json") if isinstance(raw.get("params_json"), dict) else {}
                min_conf = _as_optional_float(raw.get("min_confidence"))
                min_score = _as_optional_float(raw.get("min_score"))
                max_positions = raw.get("max_positions")
                cooldown_sec = raw.get("cooldown_sec")
                cur.execute(
                    """
                    INSERT INTO brain.strategy_config
                    (strategy_id, role, enabled, params_json, min_confidence, min_score, max_positions, cooldown_sec, updated_at)
                    VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, now())
                    ON CONFLICT (strategy_id, role) DO UPDATE
                    SET enabled = EXCLUDED.enabled,
                        params_json = EXCLUDED.params_json,
                        min_confidence = EXCLUDED.min_confidence,
                        min_score = EXCLUDED.min_score,
                        max_positions = EXCLUDED.max_positions,
                        cooldown_sec = EXCLUDED.cooldown_sec,
                        updated_at = now()
                    RETURNING *
                    """,
                    (
                        strategy_id,
                        role,
                        enabled,
                        json.dumps(params_json, ensure_ascii=True),
                        min_conf,
                        min_score,
                        (None if max_positions in (None, "") else int(max_positions)),
                        (None if cooldown_sec in (None, "") else int(cooldown_sec)),
                    ),
                )
                row = dict(cur.fetchone() or {})
                row["params_json"] = row.get("params_json") if isinstance(row.get("params_json"), dict) else {}
                row["enabled"] = bool(row.get("enabled"))
                updated.append(row)
    await _audit_write(
        request=request,
        action="STRATEGY_CONFIG_SET",
        role=None,
        target_id="brain.strategy_config",
        trace_id=trace_id,
        request_json={"items": rows_in, "actor": actor},
        response_json={"updated": len(updated)},
        ok=True,
    )
    return {"ok": True, "trace_id": trace_id, "updated": updated, "count": len(updated)}


@app.get("/api/risk/profiles")
async def api_risk_profiles_get():
    items = _risk_profile_rows()
    return {"ok": True, "items": items, "count": len(items)}


@app.post("/api/risk/profiles")
async def api_risk_profiles_post(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    _ensure_strategy_risk_tables()
    trace_id = _trace_id_from_request(request)
    actor = _actor_from_request(request)
    items = body.get("items") if isinstance(body.get("items"), list) else [body]
    updated: list[dict[str, Any]] = []
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            for raw in items:
                if not isinstance(raw, dict):
                    continue
                profile_id = str(raw.get("profile_id") or "").strip()
                name = str(raw.get("name") or profile_id).strip()
                params_json = raw.get("params_json") if isinstance(raw.get("params_json"), dict) else {}
                if not profile_id:
                    raise HTTPException(status_code=400, detail="profile_id is required")
                cur.execute(
                    """
                    INSERT INTO brain.risk_profile (profile_id, name, params_json, updated_at)
                    VALUES (%s, %s, %s::jsonb, now())
                    ON CONFLICT (profile_id) DO UPDATE
                    SET name = EXCLUDED.name,
                        params_json = EXCLUDED.params_json,
                        updated_at = now()
                    RETURNING *
                    """,
                    (
                        profile_id,
                        name,
                        json.dumps(params_json, ensure_ascii=True),
                    ),
                )
                row = dict(cur.fetchone() or {})
                row["params_json"] = row.get("params_json") if isinstance(row.get("params_json"), dict) else {}
                updated.append(row)
    await _audit_write(
        request=request,
        action="RISK_PROFILE_SET",
        role=None,
        target_id="brain.risk_profile",
        trace_id=trace_id,
        request_json={"items": items, "actor": actor},
        response_json={"updated": len(updated)},
        ok=True,
    )
    return {"ok": True, "trace_id": trace_id, "updated": updated, "count": len(updated)}


@app.get("/api/runtime/role")
async def api_runtime_role_get(role: str = "all"):
    roles = _resolve_roles(role)
    runtime_rows = {r: _role_runtime_get(r) for r in roles}
    profile_rows = {r: _risk_profile_by_id(runtime_rows[r].get("active_risk_profile")) for r in roles}
    metrics = {r: _role_trade_runtime_metrics(r) for r in roles}
    return {
        "ok": True,
        "role": role,
        "items": runtime_rows,
        "profiles": profile_rows,
        "metrics": metrics,
    }


@app.post("/api/runtime/role")
async def api_runtime_role_post(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    _ensure_strategy_risk_tables()
    role = _validate_role(str(body.get("role") or "").strip().lower())
    if role == "live":
        _enforce_live_write_confirmation(role="live", action="RUNTIME_ROLE_SET", body=body, request=request)
    active_profile = str(body.get("active_risk_profile") or "").strip()
    if active_profile:
        profile_exists = any(str(x.get("profile_id") or "") == active_profile for x in _risk_profile_rows())
        if not profile_exists:
            raise HTTPException(status_code=400, detail="active_risk_profile not found")
    mode = str(body.get("execution_mode") or "").strip().upper() or _role_runtime_get(role).get("execution_mode") or "PAPER"
    if mode not in RUNTIME_EXECUTION_MODES:
        raise HTTPException(status_code=400, detail=f"execution_mode must be one of {', '.join(RUNTIME_EXECUTION_MODES)}")
    allow_auto = bool(body.get("allow_auto_approve", _role_runtime_get(role).get("allow_auto_approve", False)))
    allow_manual = bool(body.get("allow_manual_execute", _role_runtime_get(role).get("allow_manual_execute", True)))
    trace_id = _trace_id_from_request(request)
    actor = _actor_from_request(request)
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO brain.role_runtime
                (role, active_risk_profile, execution_mode, allow_auto_approve, allow_manual_execute, updated_at)
                VALUES (%s, %s, %s, %s, %s, now())
                ON CONFLICT (role) DO UPDATE
                SET active_risk_profile = COALESCE(EXCLUDED.active_risk_profile, brain.role_runtime.active_risk_profile),
                    execution_mode = EXCLUDED.execution_mode,
                    allow_auto_approve = EXCLUDED.allow_auto_approve,
                    allow_manual_execute = EXCLUDED.allow_manual_execute,
                    updated_at = now()
                RETURNING *
                """,
                (
                    role,
                    active_profile or None,
                    mode,
                    allow_auto,
                    allow_manual,
                ),
            )
            row = dict(cur.fetchone() or {})
    await _audit_write(
        request=request,
        action="RUNTIME_ROLE_SET",
        role=role,
        target_id=role,
        trace_id=trace_id,
        request_json={"role": role, "active_risk_profile": active_profile, "execution_mode": mode, "allow_auto_approve": allow_auto, "allow_manual_execute": allow_manual, "actor": actor},
        response_json={"ok": True},
        ok=True,
    )
    return {
        "ok": True,
        "trace_id": trace_id,
        "item": row,
        "profile": _risk_profile_by_id(row.get("active_risk_profile")),
        "metrics": _role_trade_runtime_metrics(role),
    }


@app.post("/api/integrations/binance/test")
async def api_binance_test():
    try:
        secret = _load_integration_secret("binance")
    except Exception as e:
        return {"ok": False, "error": "secret_load_failed", "detail": str(e)}
    if not secret:
        return {"ok": False, "error": "not_connected"}
    api_key = str(secret.get("api_key") or "").strip()
    api_secret = str(secret.get("api_secret") or "").strip()
    testnet = bool(secret.get("testnet", False))
    if not api_key or not api_secret:
        return {"ok": False, "error": "invalid_saved_credentials"}

    async def _signed_probe(base: str, path: str) -> Dict[str, Any]:
        ts = int(time.time() * 1000)
        query = urlencode({"timestamp": ts, "recvWindow": 5000})
        sig = hmac.new(api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
        url = f"{base}{path}?{query}&signature={sig}"
        headers = {"X-MBX-APIKEY": api_key}
        try:
            async with httpx.AsyncClient(timeout=8.0) as c:
                r = await c.get(url, headers=headers)
            payload: Dict[str, Any] = {}
            try:
                body = r.json()
                if isinstance(body, dict):
                    payload = body
            except Exception:
                payload = {}
            if r.status_code >= 400:
                return {
                    "ok": False,
                    "status_code": r.status_code,
                    "error_code": payload.get("code"),
                    "error_msg": payload.get("msg") or _clip_text(getattr(r, "text", ""), 200),
                }
            return {
                "ok": True,
                "status_code": r.status_code,
                "canTrade": payload.get("canTrade"),
                "permissions": payload.get("permissions"),
                "accountType": payload.get("accountType") or payload.get("multiAssetsMargin"),
            }
        except Exception as e:
            return {"ok": False, "error_msg": repr(e)}

    def _classify_failure(spot_res: Dict[str, Any], fut_res: Dict[str, Any]) -> str:
        codes = []
        for item in (spot_res, fut_res):
            code = item.get("error_code")
            if isinstance(code, int):
                codes.append(code)
        if -2014 in codes:
            return "api_key_format_invalid"
        if -2015 in codes:
            return "invalid_api_key_or_permissions_or_ip"
        if -1022 in codes:
            return "invalid_signature_or_secret"
        if -1021 in codes:
            return "timestamp_out_of_sync"
        return "auth_or_permission_failed"

    def _bases(is_testnet: bool) -> tuple[str, str]:
        spot = "https://testnet.binance.vision" if is_testnet else "https://api.binance.com"
        futures = "https://testnet.binancefuture.com" if is_testnet else "https://fapi.binance.com"
        return spot, futures

    spot_base, futures_base = _bases(testnet)
    spot = await _signed_probe(spot_base, "/api/v3/account")
    futures = await _signed_probe(futures_base, "/fapi/v2/account")
    connected = bool(spot.get("ok") or futures.get("ok"))
    error = None
    suggested_testnet: Optional[bool] = None

    if not connected:
        error = _classify_failure(spot, futures)
        # Try opposite network once to detect wrong testnet/mainnet selection.
        alt_testnet = not testnet
        alt_spot_base, alt_fut_base = _bases(alt_testnet)
        alt_spot = await _signed_probe(alt_spot_base, "/api/v3/account")
        alt_futures = await _signed_probe(alt_fut_base, "/fapi/v2/account")
        if alt_spot.get("ok") or alt_futures.get("ok"):
            error = "testnet_mismatch"
            suggested_testnet = alt_testnet

    return {
        "ok": connected,
        "connected": connected,
        "testnet": testnet,
        "spot": spot,
        "futures": futures,
        "error": error,
        "suggested_testnet": suggested_testnet,
    }


def _binance_bases(is_testnet: bool) -> tuple[str, str]:
    spot = "https://testnet.binance.vision" if is_testnet else "https://api.binance.com"
    futures = "https://testnet.binancefuture.com" if is_testnet else "https://fapi.binance.com"
    return spot, futures


async def _binance_signed_get(
    *,
    api_key: str,
    api_secret: str,
    base: str,
    path: str,
    params: Dict[str, Any] | None = None,
    timeout_s: float = 10.0,
) -> Dict[str, Any]:
    q = dict(params or {})
    q["timestamp"] = int(time.time() * 1000)
    q.setdefault("recvWindow", 5000)
    query = urlencode(q, doseq=True)
    sig = hmac.new(api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
    url = f"{base}{path}?{query}&signature={sig}"
    headers = {"X-MBX-APIKEY": api_key}
    async with httpx.AsyncClient(timeout=timeout_s) as c:
        r = await c.get(url, headers=headers)
    body: Any = None
    try:
        body = r.json()
    except Exception:
        body = {"raw": _clip_text(getattr(r, "text", ""), 400)}
    if r.status_code >= 400:
        return {
            "ok": False,
            "status_code": r.status_code,
            "error_code": body.get("code") if isinstance(body, dict) else None,
            "error_msg": (body.get("msg") if isinstance(body, dict) else None) or str(body),
            "body": body,
        }
    return {"ok": True, "status_code": r.status_code, "body": body}


async def _binance_fetch_income(
    *,
    api_key: str,
    api_secret: str,
    base: str,
    income_type: str,
    start_ms: int | None,
    end_ms: int | None,
    limit: int = 1000,
) -> list[dict]:
    params: Dict[str, Any] = {"incomeType": income_type, "limit": max(1, min(int(limit), 1000))}
    if start_ms is not None:
        params["startTime"] = int(start_ms)
    if end_ms is not None:
        params["endTime"] = int(end_ms)
    resp = await _binance_signed_get(
        api_key=api_key,
        api_secret=api_secret,
        base=base,
        path="/fapi/v1/income",
        params=params,
        timeout_s=12.0,
    )
    if not resp.get("ok"):
        return []
    body = resp.get("body")
    return [dict(x) for x in body] if isinstance(body, list) else []


@app.get("/api/portfolio/binance/account")
async def api_portfolio_binance_account(
    from_ts: str | None = None,
    to_ts: str | None = None,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None, alias="to"),
):
    if from_ts is None:
        from_ts = from_
    if to_ts is None:
        to_ts = to
    start_ms = _parse_ts_ms(from_ts)
    end_ms = _parse_ts_ms(to_ts)
    secret = _load_integration_secret("binance")
    if not secret:
        return {
            "ok": True,
            "connected": False,
            "disabled": True,
            "message": "Not connected / disabled",
            "summary": {
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "total_fees": 0.0,
                "balance_usdt": 0.0,
                "equity_usdt": 0.0,
            },
            "balances": [],
            "positions": [],
            "income": {"realized_pnl": [], "commission": []},
        }

    api_key = str(secret.get("api_key") or "").strip()
    api_secret = str(secret.get("api_secret") or "").strip()
    is_testnet = _as_bool(secret.get("testnet"), False)
    if not api_key or not api_secret:
        return {"ok": False, "connected": False, "error": "invalid_saved_credentials"}

    spot_base, fut_base = _binance_bases(is_testnet)
    spot_task = _binance_signed_get(
        api_key=api_key,
        api_secret=api_secret,
        base=spot_base,
        path="/api/v3/account",
    )
    fut_task = _binance_signed_get(
        api_key=api_key,
        api_secret=api_secret,
        base=fut_base,
        path="/fapi/v2/account",
    )
    pnl_task = _binance_fetch_income(
        api_key=api_key,
        api_secret=api_secret,
        base=fut_base,
        income_type="REALIZED_PNL",
        start_ms=start_ms,
        end_ms=end_ms,
    )
    fee_task = _binance_fetch_income(
        api_key=api_key,
        api_secret=api_secret,
        base=fut_base,
        income_type="COMMISSION",
        start_ms=start_ms,
        end_ms=end_ms,
    )
    spot_res, fut_res, pnl_rows, fee_rows = await asyncio.gather(spot_task, fut_task, pnl_task, fee_task)

    if not spot_res.get("ok") and not fut_res.get("ok"):
        return {
            "ok": False,
            "connected": False,
            "error": "binance_unreachable_or_auth_failed",
            "spot_error": spot_res,
            "futures_error": fut_res,
        }

    spot_body = spot_res.get("body") if isinstance(spot_res.get("body"), dict) else {}
    fut_body = fut_res.get("body") if isinstance(fut_res.get("body"), dict) else {}
    balances = []
    for b in (spot_body.get("balances") or []):
        free = _as_float((b or {}).get("free"), 0.0)
        locked = _as_float((b or {}).get("locked"), 0.0)
        if free == 0 and locked == 0:
            continue
        balances.append(
            {
                "asset": str((b or {}).get("asset") or ""),
                "free": free,
                "locked": locked,
                "total": free + locked,
            }
        )

    positions = []
    for p in (fut_body.get("positions") or []):
        amt = _as_float((p or {}).get("positionAmt"), 0.0)
        if amt == 0:
            continue
        positions.append(
            {
                "symbol": str((p or {}).get("symbol") or ""),
                "position_amt": amt,
                "entry_price": _as_float((p or {}).get("entryPrice"), 0.0),
                "mark_price": _as_float((p or {}).get("markPrice"), 0.0),
                "leverage": _as_float((p or {}).get("leverage"), 0.0),
                "unrealized_pnl": _as_float((p or {}).get("unrealizedProfit"), 0.0),
            }
        )

    realized_pnl = sum(_as_float((x or {}).get("income"), 0.0) for x in (pnl_rows or []))
    total_fees = abs(sum(_as_float((x or {}).get("income"), 0.0) for x in (fee_rows or [])))
    unrealized_pnl = _as_float(fut_body.get("totalUnrealizedProfit"), 0.0)
    wallet_balance = _as_float(fut_body.get("totalWalletBalance"), 0.0)
    total_balance_usdt = wallet_balance
    for b in balances:
        if str(b.get("asset") or "").upper() == "USDT":
            total_balance_usdt += _as_float(b.get("total"), 0.0)

    return {
        "ok": True,
        "connected": True,
        "testnet": is_testnet,
        "from": from_ts,
        "to": to_ts,
        "summary": {
            "realized_pnl": float(realized_pnl),
            "unrealized_pnl": float(unrealized_pnl),
            "total_fees": float(total_fees),
            "balance_usdt": float(total_balance_usdt),
            "equity_usdt": float(total_balance_usdt + unrealized_pnl),
        },
        "balances": balances,
        "positions": positions,
        "income": {
            "realized_pnl": pnl_rows,
            "commission": fee_rows,
        },
    }


@app.get("/api/portfolio/binance/export.csv")
async def api_portfolio_binance_export_csv(
    from_ts: str | None = None,
    to_ts: str | None = None,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None, alias="to"),
):
    data = await api_portfolio_binance_account(from_ts=from_ts, to_ts=to_ts, from_=from_, to=to)
    if not data.get("ok"):
        raise HTTPException(status_code=409, detail=data)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["section", "symbol_or_asset", "metric", "value", "timestamp"])
    for bal in data.get("balances") or []:
        writer.writerow(["balance", bal.get("asset"), "total", bal.get("total"), ""])
    for pos in data.get("positions") or []:
        writer.writerow(["position", pos.get("symbol"), "position_amt", pos.get("position_amt"), ""])
        writer.writerow(["position", pos.get("symbol"), "unrealized_pnl", pos.get("unrealized_pnl"), ""])
    for row in (data.get("income") or {}).get("realized_pnl") or []:
        writer.writerow(["income_realized_pnl", row.get("symbol"), row.get("incomeType"), row.get("income"), row.get("time")])
    for row in (data.get("income") or {}).get("commission") or []:
        writer.writerow(["income_commission", row.get("symbol"), row.get("incomeType"), row.get("income"), row.get("time")])
    filename = f"binance_portfolio_{dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/portfolio/export.csv")
async def api_portfolio_export_csv(
    role: str = "all",
    from_ts: str | None = None,
    to_ts: str | None = None,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None, alias="to"),
    limit: int = 5000,
):
    if from_ts is None:
        from_ts = from_
    if to_ts is None:
        to_ts = to
    roles = _resolve_roles(role)
    items: list[dict] = []
    for r in roles:
        try:
            rows = await _trades_fetch(role=r, limit=max(1, min(int(limit), 10000)), from_ts=from_ts, to_ts=to_ts)
        except Exception:
            rows = []
        for row in rows:
            rr = dict(row)
            rr["role"] = r
            items.append(rr)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["role", "id", "symbol", "side", "status", "qty", "entry_price", "exit_price", "pnl", "fee", "opened_at", "closed_at"])
    for row in items:
        writer.writerow(
            [
                row.get("role"),
                row.get("id") or row.get("trade_id"),
                row.get("symbol") or row.get("pair"),
                row.get("side") or row.get("signal"),
                row.get("status"),
                row.get("qty") or row.get("quantity") or row.get("size"),
                row.get("entry_price") or row.get("entry"),
                row.get("exit_price") or row.get("close_price"),
                row.get("pnl") or row.get("realized_pnl"),
                row.get("fee") or row.get("fees") or row.get("commission"),
                row.get("opened_at") or row.get("created_at"),
                row.get("closed_at") or row.get("closed_at_ms"),
            ]
        )
    filename = f"portfolio_{dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _portfolio_summary_for_schema(schema: str, from_ts: str | None, to_ts: str | None) -> Dict[str, Any]:
    if not _table_exists(schema, "trades"):
        return {
            "trades": 0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "wins": 0,
            "losses": 0,
            "fees": 0.0,
            "symbols": {},
        }
    cols = _table_columns(schema, "trades")
    pnl_col = "pnl" if "pnl" in cols else ("realized_pnl" if "realized_pnl" in cols else None)
    unrealized_col = "unrealized_pnl" if "unrealized_pnl" in cols else pnl_col
    status_col = "status" if "status" in cols else None
    sym_col = "symbol" if "symbol" in cols else ("pair" if "pair" in cols else None)
    time_num_col = "closed_at_ms" if "closed_at_ms" in cols else ("created_at_ms" if "created_at_ms" in cols else ("timestamp_ms" if "timestamp_ms" in cols else None))
    time_txt_col = "closed_at" if "closed_at" in cols else ("created_at" if "created_at" in cols else ("timestamp" if "timestamp" in cols else None))
    fee_cols = [c for c in ("fee", "fees", "commission", "total_fee", "total_fees") if c in cols]

    where_closed: list[str] = []
    params_closed: list[object] = []
    if status_col:
        where_closed.append("UPPER(status) = 'CLOSED'")
    f_ms = _parse_ts_ms(from_ts)
    t_ms = _parse_ts_ms(to_ts)
    if time_num_col and f_ms is not None:
        where_closed.append(f"{time_num_col} >= %s")
        params_closed.append(int(f_ms))
    if time_num_col and t_ms is not None:
        where_closed.append(f"{time_num_col} <= %s")
        params_closed.append(int(t_ms))
    if (not time_num_col) and time_txt_col and f_ms is not None:
        where_closed.append(f"{time_txt_col} >= %s")
        params_closed.append(_ms_to_iso(int(f_ms)))
    if (not time_num_col) and time_txt_col and t_ms is not None:
        where_closed.append(f"{time_txt_col} <= %s")
        params_closed.append(_ms_to_iso(int(t_ms)))

    where_closed_sql = ("WHERE " + " AND ".join(where_closed)) if where_closed else ""
    where_open_sql = "WHERE UPPER(status) = 'OPEN'" if status_col else ""
    realized = 0.0
    unrealized = 0.0
    wins = 0
    losses = 0
    fees = 0.0
    trades = 0
    symbols: dict[str, float] = {}
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            if pnl_col:
                cur.execute(f"SELECT COALESCE(SUM({pnl_col}),0) AS pnl, COUNT(*) AS n FROM {schema}.trades {where_closed_sql}", params_closed)
                row = cur.fetchone() or {}
                realized = float(row.get("pnl") or 0.0)
                trades = int(row.get("n") or 0)
                win_where = where_closed_sql
                if win_where:
                    win_where = win_where + f" AND {pnl_col} > 0"
                else:
                    win_where = f"WHERE {pnl_col} > 0"
                cur.execute(
                    f"SELECT COUNT(*) AS wins FROM {schema}.trades {win_where}",
                    params_closed,
                )
                wins = int((cur.fetchone() or {}).get("wins") or 0)
                losses = max(0, trades - wins)
            if sym_col and pnl_col:
                cur.execute(
                    f"SELECT {sym_col} AS sym, COALESCE(SUM({pnl_col}),0) AS pnl FROM {schema}.trades {where_closed_sql} GROUP BY {sym_col}",
                    params_closed,
                )
                for r in cur.fetchall() or []:
                    if r.get("sym"):
                        symbols[str(r.get("sym"))] = float(r.get("pnl") or 0.0)
            if unrealized_col:
                cur.execute(f"SELECT COALESCE(SUM(COALESCE({unrealized_col},0)),0) AS v FROM {schema}.trades {where_open_sql}")
                unrealized = float((cur.fetchone() or {}).get("v") or 0.0)
            if fee_cols:
                fee_expr = " + ".join([f"COALESCE({c},0)" for c in fee_cols])
                cur.execute(
                    f"SELECT COALESCE(SUM({fee_expr}),0) AS f FROM {schema}.trades {where_closed_sql}",
                    params_closed,
                )
                fees = float((cur.fetchone() or {}).get("f") or 0.0)
    return {
        "trades": trades,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "wins": wins,
        "losses": losses,
        "fees": fees,
        "symbols": symbols,
    }


@app.get("/api/portfolio/summary")
async def api_portfolio_summary(
    role: str = "all",
    from_ts: str | None = None,
    to_ts: str | None = None,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None, alias="to"),
):
    if from_ts is None:
        from_ts = from_
    if to_ts is None:
        to_ts = to
    roles = _resolve_roles(role)
    summary = {"realized_pnl": 0.0, "unrealized_pnl": 0.0, "win_rate": 0.0, "total_trades": 0, "wins": 0, "losses": 0, "total_fees": 0.0, "symbols": {}}
    by_role: Dict[str, Dict[str, Any]] = {}
    for r in roles:
        schema = _schema_for_role(r)
        s = _portfolio_summary_for_schema(schema, from_ts, to_ts)
        by_role[r] = {
            "realized_pnl": float(s.get("realized_pnl") or 0.0),
            "unrealized_pnl": float(s.get("unrealized_pnl") or 0.0),
            "floating_pnl": float(s.get("unrealized_pnl") or 0.0),
            "total_trades": int(s.get("trades") or 0),
            "wins": int(s.get("wins") or 0),
            "losses": int(s.get("losses") or 0),
            "total_fees": float(s.get("fees") or 0.0),
            "win_rate": round((float(s.get("wins") or 0) / max(1, int(s.get("trades") or 0))) * 100.0, 2)
            if int(s.get("trades") or 0) > 0
            else 0.0,
        }
        summary["realized_pnl"] += float(s.get("realized_pnl") or 0.0)
        summary["unrealized_pnl"] += float(s.get("unrealized_pnl") or 0.0)
        summary["total_trades"] += int(s.get("trades") or 0)
        summary["wins"] += int(s.get("wins") or 0)
        summary["losses"] += int(s.get("losses") or 0)
        for sym, pnl in (s.get("symbols") or {}).items():
            summary["symbols"][sym] = float(summary["symbols"].get(sym, 0.0)) + float(pnl or 0.0)
        summary["total_fees"] += float(s.get("fees") or 0.0)
    if summary["total_trades"] > 0:
        summary["win_rate"] = round((summary["wins"] / summary["total_trades"]) * 100.0, 2)
    summary["floating_pnl"] = float(summary.get("unrealized_pnl") or 0.0)
    # Connection status is optional metadata for UI disabled state.
    has_binance_secret = bool(_load_integration_secret("binance"))
    return {
        "ok": True,
        "role": role,
        "from": from_ts,
        "to": to_ts,
        "summary": summary,
        "by_role": by_role,
        "connection": {"enabled": has_binance_secret, "connected": False if not has_binance_secret else None},
    }


@app.get("/api/portfolio/equity")
async def api_portfolio_equity(
    role: str = "all",
    from_ts: str | None = None,
    to_ts: str | None = None,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None, alias="to"),
    limit: int = 1000,
):
    if from_ts is None:
        from_ts = from_
    if to_ts is None:
        to_ts = to
    roles = _resolve_roles(role)
    by_role: Dict[str, list[dict]] = {}
    points: list[dict] = []
    for r in roles:
        try:
            rows = await _equity_history_fetch(role=r, limit=limit, from_ts=from_ts, to_ts=to_ts)
        except Exception:
            rows = []
        out_rows: list[dict] = []
        for row in rows:
            rr = dict(row)
            rr["role"] = r
            out_rows.append(rr)
            points.append(rr)
        by_role[r] = out_rows
    # Global merged curve: sort by timestamp and cumulatively sum latest known values per role.
    def _ts_key(x: dict) -> int:
        val = x.get("timestamp_ms")
        try:
            return int(val)
        except Exception:
            pass
        txt = x.get("timestamp") or x.get("created_at") or x.get("date_utc")
        try:
            return int(dt.datetime.fromisoformat(str(txt).replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            return 0

    last_by_role: Dict[str, float] = {r: 0.0 for r in roles}
    merged: list[dict] = []
    for row in sorted(points, key=_ts_key):
        r = str(row.get("role") or "")
        val = float(row.get("total_balance") or row.get("equity") or 0.0)
        if r:
            last_by_role[r] = val
        merged.append(
            {
                "timestamp_ms": _ts_key(row),
                "timestamp": row.get("timestamp") or row.get("created_at") or row.get("date_utc"),
                "equity": float(sum(last_by_role.values())),
            }
        )
    return {"ok": True, "role": role, "from": from_ts, "to": to_ts, "items": merged, "by_role": by_role, "count": len(merged)}


@app.get("/api/portfolio/trades")
async def api_portfolio_trades(
    role: str = "all",
    from_ts: str | None = None,
    to_ts: str | None = None,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None, alias="to"),
    symbol: str | None = None,
    status: str | None = None,
    limit: int = 200,
):
    if from_ts is None:
        from_ts = from_
    if to_ts is None:
        to_ts = to
    roles = _resolve_roles(role)
    items: list[dict] = []
    for r in roles:
        try:
            rows = await _trades_fetch(role=r, limit=limit, status=status, symbol=symbol, from_ts=from_ts, to_ts=to_ts)
        except Exception:
            rows = []
        for row in rows:
            row = dict(row)
            row["role"] = r
            items.append(row)
    return {"ok": True, "items": jsonable_encoder(items), "count": len(items)}


@app.get("/api/portfolio/fees")
async def api_portfolio_fees(
    role: str = "all",
    from_ts: str | None = None,
    to_ts: str | None = None,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None, alias="to"),
):
    if from_ts is None:
        from_ts = from_
    if to_ts is None:
        to_ts = to
    roles = _resolve_roles(role)
    items: list[dict] = []
    total = 0.0
    for r in roles:
        schema = _schema_for_role(r)
        s = _portfolio_summary_for_schema(schema, from_ts, to_ts)
        fee_val = float(s.get("fees") or 0.0)
        total += fee_val
        items.append({"role": r, "total_fees": fee_val})
    return {"ok": True, "role": role, "from": from_ts, "to": to_ts, "items": items, "total_fees": total}


# ---------------------------
# Phase 4: Reports endpoints
# ---------------------------

_ANALYTICS_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}


@app.get("/api/reports/paper-arena")
async def api_report_paper_arena(from_ts: str | None = None, to_ts: str | None = None):
    schema = _schema_for_role("paper")
    summary = _portfolio_summary_for_schema(schema, from_ts, to_ts)
    return {"ok": True, "summary": summary}


@app.get("/api/reports/paper_arena")
async def api_report_paper_arena_alias(
    from_ts: str | None = None,
    to_ts: str | None = None,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None, alias="to"),
):
    return await api_report_paper_arena(from_ts=from_ts or from_, to_ts=to_ts or to)


@app.get("/api/reports/analytics")
async def api_report_analytics(from_ts: str | None = None, to_ts: str | None = None):
    now = time.time()
    if _ANALYTICS_CACHE["data"] and now - float(_ANALYTICS_CACHE["ts"] or 0) < 30:
        return _ANALYTICS_CACHE["data"]
    try:
        data = await _brain_get_json("/api/overview")
    except Exception as e:
        data = {"ok": False, "error": str(e)}
    _ANALYTICS_CACHE["ts"] = now
    _ANALYTICS_CACHE["data"] = data
    return data


@app.get("/api/reports/deep_audit")
async def api_report_deep_audit(trace_id: str | None = None, role: str = "all", limit: int = 200):
    if trace_id:
        return await api_report_audit_trace(trace_id=trace_id)
    audit_rows = []
    try:
        audit_rows = await asyncio.to_thread(fetch_audit_events, AUDIT_DSN, max(1, min(int(limit), 1000)))
    except Exception:
        audit_rows = []
    if role and role not in ("all", "*"):
        audit_rows = [r for r in audit_rows if str(r.get("role") or "").lower() == str(role).lower()]
    return {"ok": True, "role": role, "trace_id": trace_id, "audit": audit_rows, "count": len(audit_rows)}


@app.get("/api/reports/deep_audit_lab")
async def api_report_deep_audit_lab(trace_id: str | None = None, role: str = "all", limit: int = 200):
    return await api_report_deep_audit(trace_id=trace_id, role=role, limit=limit)


@app.get("/api/reports/daily_summary")
async def api_report_daily_summary(request: Request):
    params = dict(request.query_params)
    params.pop("from", None)
    params.pop("to", None)
    try:
        data = await _brain_get_json("/api/daily-summary", params=params)
        return {"ok": True, "data": data}
    except HTTPException as e:
        return {"ok": False, "error": _http_exc_detail(e), "data": None}
    except Exception as e:
        return {"ok": False, "error": str(e), "data": None}


@app.get("/api/reports/strategy_compare")
async def api_report_strategy_compare(request: Request):
    params = dict(request.query_params)
    params.pop("from", None)
    params.pop("to", None)
    try:
        data = await _brain_get_json("/api/strategy-compare", params=params)
        return {"ok": True, "data": data}
    except HTTPException as e:
        return {"ok": False, "error": _http_exc_detail(e), "data": None}
    except Exception as e:
        return {"ok": False, "error": str(e), "data": None}


@app.get("/api/reports/audit/trace")
async def api_report_audit_trace(trace_id: str):
    if not trace_id:
        raise HTTPException(status_code=400, detail="trace_id required")
    audit_rows = []
    try:
        audit_rows = await asyncio.to_thread(fetch_audit_events, AUDIT_DSN, 200)
        audit_rows = [r for r in audit_rows if str(r.get("trace_id")) == trace_id]
    except Exception:
        audit_rows = []
    event_rows = await _events_fetch(limit=200, order="desc")
    event_rows = [r for r in event_rows if str((r.get("data") or {}).get("trace_id")) == trace_id]
    return {"ok": True, "trace_id": trace_id, "audit": audit_rows, "events": event_rows}


@app.get("/api/reports/data-quality")
async def api_report_data_quality(role: str = "paper", from_ts: str | None = None, to_ts: str | None = None):
    roles = _resolve_roles(role)
    out = {"ok": True, "roles": {}}
    for r in roles:
        schema = _schema_for_role(r)
        if not _table_exists(schema, "trades"):
            out["roles"][r] = {"error": "trades_table_missing"}
            continue
        cols = _table_columns(schema, "trades")
        report = {"missing_cols": [], "counts": {}}
        required = ["symbol", "status", "pnl"]
        for c in required:
            if c not in cols:
                report["missing_cols"].append(c)
        with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) AS n FROM {schema}.trades")
                report["counts"]["total"] = int((cur.fetchone() or {}).get("n") or 0)
                if "status" in cols:
                    cur.execute(f"SELECT status, COUNT(*) AS n FROM {schema}.trades GROUP BY status")
                    report["counts"]["by_status"] = {r["status"]: int(r["n"]) for r in (cur.fetchall() or [])}
        out["roles"][r] = report
    return out


@app.get("/api/reports/pnl-breakdown")
async def api_report_pnl_breakdown(role: str = "paper", period: str = "daily", from_ts: str | None = None, to_ts: str | None = None):
    role = _validate_role(role)
    schema = _schema_for_role(role)
    if not _table_exists(schema, "trades"):
        return {"ok": False, "error": "trades_table_missing"}

    cols = _table_columns(schema, "trades")
    pnl_col = next((c for c in ("pnl", "realized_pnl", "profit", "pnl_usd") if c in cols), None)
    if not pnl_col:
        return {"ok": False, "error": "pnl_column_missing"}

    time_col = None
    time_is_ms = False
    if "closed_at_ms" in cols:
        time_col = "closed_at_ms"
        time_is_ms = True
    elif "closed_at" in cols:
        time_col = "closed_at"
    elif "timestamp_ms" in cols:
        time_col = "timestamp_ms"
        time_is_ms = True
    elif "timestamp" in cols:
        time_col = "timestamp"

    if not time_col:
        return {"ok": False, "error": "time_column_missing"}

    period = (period or "daily").lower()
    if period not in ("daily", "weekly"):
        period = "daily"

    from_ms = _parse_ts_ms(from_ts)
    to_ms = _parse_ts_ms(to_ts)

    if time_is_ms:
        ts_expr = f"to_timestamp({time_col} / 1000.0)"
    else:
        ts_expr = f"NULLIF({time_col}, '')::timestamptz"

    bucket = "date_trunc('week', %s)" % ts_expr if period == "weekly" else "date_trunc('day', %s)" % ts_expr

    where = ["status='CLOSED'"]
    params: list[Any] = []
    if from_ms is not None and time_is_ms:
        where.append(f"{time_col} >= %s")
        params.append(int(from_ms))
    if to_ms is not None and time_is_ms:
        where.append(f"{time_col} <= %s")
        params.append(int(to_ms))
    wsql = " AND ".join(where)

    sql = f"""
      SELECT {bucket} AS bucket, COUNT(*) AS trades, SUM({pnl_col}) AS pnl
      FROM {schema}.trades
      WHERE {wsql}
      GROUP BY bucket
      ORDER BY bucket ASC
    """
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = list(cur.fetchall())
    return {"ok": True, "role": role, "period": period, "items": rows}


@app.get("/api/reports/strategy-performance")
async def api_report_strategy_performance(role: str = "paper", from_ts: str | None = None, to_ts: str | None = None):
    role = _validate_role(role)
    schema = _schema_for_role(role)
    if not _table_exists(schema, "trades"):
        return {"ok": False, "error": "trades_table_missing"}

    cols = _table_columns(schema, "trades")
    strat_col = next((c for c in ("strategy", "strategy_name", "strat") if c in cols), None)
    pnl_col = next((c for c in ("pnl", "realized_pnl", "profit", "pnl_usd") if c in cols), None)
    if not strat_col or not pnl_col:
        return {"ok": False, "error": "strategy_or_pnl_missing"}

    time_col = "closed_at_ms" if "closed_at_ms" in cols else ("timestamp_ms" if "timestamp_ms" in cols else None)
    from_ms = _parse_ts_ms(from_ts)
    to_ms = _parse_ts_ms(to_ts)

    where = ["status='CLOSED'"]
    params: list[Any] = []
    if time_col and from_ms is not None:
        where.append(f"{time_col} >= %s")
        params.append(int(from_ms))
    if time_col and to_ms is not None:
        where.append(f"{time_col} <= %s")
        params.append(int(to_ms))

    sql = f"""
      SELECT {strat_col} AS strategy, COUNT(*) AS trades,
             SUM({pnl_col}) AS pnl,
             AVG({pnl_col}) AS avg_pnl
      FROM {schema}.trades
      WHERE {' AND '.join(where)}
      GROUP BY {strat_col}
      ORDER BY pnl DESC NULLS LAST
    """
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = list(cur.fetchall())
    return {"ok": True, "role": role, "items": rows}


@app.get("/api/reports/fees-slippage")
async def api_report_fees_slippage(role: str = "paper", from_ts: str | None = None, to_ts: str | None = None):
    role = _validate_role(role)
    schema = _schema_for_role(role)
    if not _table_exists(schema, "trades"):
        return {"ok": False, "error": "trades_table_missing"}
    cols = _table_columns(schema, "trades")
    fee_col = next((c for c in ("fee", "fees", "total_fees", "commission") if c in cols), None)
    slip_col = next((c for c in ("slippage", "slippage_bps", "slip_bps") if c in cols), None)

    if not fee_col and not slip_col:
        return {"ok": False, "error": "fees_or_slippage_missing"}

    time_col = "closed_at_ms" if "closed_at_ms" in cols else ("timestamp_ms" if "timestamp_ms" in cols else None)
    from_ms = _parse_ts_ms(from_ts)
    to_ms = _parse_ts_ms(to_ts)

    where = ["status='CLOSED'"]
    params: list[Any] = []
    if time_col and from_ms is not None:
        where.append(f"{time_col} >= %s")
        params.append(int(from_ms))
    if time_col and to_ms is not None:
        where.append(f"{time_col} <= %s")
        params.append(int(to_ms))

    fields = []
    if fee_col:
        fields.append(f"SUM({fee_col}) AS total_fees")
    if slip_col:
        fields.append(f"AVG({slip_col}) AS avg_slippage")
    sql = f"""
      SELECT {', '.join(fields)}
      FROM {schema}.trades
      WHERE {' AND '.join(where)}
    """
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
    return {"ok": True, "role": role, "data": dict(row) if row else {}}


@app.get("/api/reports/risk-timeline")
async def api_report_risk_timeline(role: str = "paper", limit: int = 200):
    role = _validate_role(role)
    schema = _schema_for_role(role)
    items: list[dict] = []

    if _table_exists(schema, "logs"):
        cols = _table_columns(schema, "logs")
        level_col = "level" if "level" in cols else ("lvl" if "lvl" in cols else None)
        msg_col = "message" if "message" in cols else ("msg" if "msg" in cols else None)
        time_col = "timestamp" if "timestamp" in cols else ("created_at" if "created_at" in cols else ("time" if "time" in cols else None))
        if level_col and msg_col:
            where = f"{level_col} ILIKE %s OR {level_col} ILIKE %s OR {level_col} ILIKE %s"
            sql = f"SELECT {level_col} AS level, {msg_col} AS message, {time_col} AS ts FROM {schema}.logs WHERE {where} ORDER BY id DESC LIMIT %s"
            with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, ("%ERROR%", "%WARN%", "%CRIT%", int(limit)))
                    items = list(cur.fetchall())

    if not items:
        rows = await _events_fetch(limit=limit, bot_role=role, order="desc")
        for r in rows or []:
            et = str(r.get("event_type") or "")
            if any(k in et.upper() for k in ("ERROR", "WARN", "CRIT", "RISK")):
                items.append({
                    "level": et,
                    "message": (r.get("data") or {}).get("message") if isinstance(r.get("data"), dict) else None,
                    "ts": r.get("created_at"),
                })

    return {"ok": True, "role": role, "items": items[:limit]}


@app.get("/api/reports/export")
async def api_report_export(type: str, format: str = "json", role: str | None = None, from_ts: str | None = None, to_ts: str | None = None):
    if type == "paper-arena":
        data = await api_report_paper_arena(from_ts=from_ts, to_ts=to_ts)
    elif type == "data-quality":
        data = await api_report_data_quality(role=role or "paper", from_ts=from_ts, to_ts=to_ts)
    else:
        raise HTTPException(status_code=400, detail="unknown_report_type")
    if format == "json":
        return data
    if format == "csv":
        return Response(content="type,ok\n", media_type="text/csv")
    raise HTTPException(status_code=400, detail="invalid_format")


# ---------------------------
# Phase 4: Project Doctor
# ---------------------------

@app.get("/api/doctor/checks")
async def api_doctor_checks(run_tests: bool = True):
    checks: list[dict] = []

    def _push(name: str, severity: str, details: str, data: Any | None = None):
        row: dict[str, Any] = {"name": name, "severity": severity, "details": details}
        if data is not None:
            row["data"] = data
        checks.append(row)

    # DB + schema wiring
    try:
        wiring = _db_wiring_snapshot()
        _push("db_connectivity", "OK" if wiring.get("same_db") else "CRIT", f"db={wiring.get('database_name')} host={wiring.get('host')}", wiring)
        missing = wiring.get("missing_services") or []
        if missing:
            _push("service_registry", "WARN", f"missing services: {len(missing)}", missing)
        else:
            _push("service_registry", "OK", "all required services registered")
    except Exception as e:
        _push("db_connectivity", "CRIT", str(e))

    # Required schema tables
    required_tables = ("trades", "events", "logs", "commands", "settings")
    for role in ("paper", "live", "pump"):
        schema = _schema_for_role(role)
        missing = [t for t in required_tables if not _table_exists(schema, t)]
        if missing:
            _push(f"schema_tables_{role}", "CRIT", f"missing: {', '.join(missing)}")
        else:
            _push(f"schema_tables_{role}", "OK", "tables present")

    # Heartbeat freshness
    for role in ("paper", "live", "pump"):
        schema = _schema_for_role(role)
        hb = _fetch_settings(schema, ["execution_monitor_heartbeat", "last_heartbeat", "bot_heartbeat"])
        last_hb = hb.get("execution_monitor_heartbeat") or hb.get("last_heartbeat") or hb.get("bot_heartbeat")
        if not last_hb:
            _push(f"heartbeat_{role}", "WARN", "missing heartbeat")
            continue
        try:
            ts = dt.datetime.fromisoformat(str(last_hb).replace("Z", "+00:00"))
            age = int((dt.datetime.now(dt.timezone.utc) - ts.astimezone(dt.timezone.utc)).total_seconds())
            sev = "OK" if age <= 60 else ("WARN" if age <= 180 else "CRIT")
            _push(f"heartbeat_{role}", sev, f"age_sec={age}")
        except Exception:
            _push(f"heartbeat_{role}", "WARN", f"unparseable heartbeat: {last_hb}")

    # Queue health
    try:
        _ensure_gateway_phase4_tables(AUDIT_DSN)
        with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT status, COUNT(*) AS n
                    FROM gateway.command_queue
                    GROUP BY status
                    """
                )
                rows = list(cur.fetchall() or [])
        counts = {str(r.get("status") or ""): int(r.get("n") or 0) for r in rows}
        pending = int(counts.get("queued", 0) + counts.get("pending", 0) + counts.get("in_progress", 0))
        sev = "OK" if pending < 500 else "WARN"
        _push("queue_health", sev, f"pending={pending}", counts)
    except Exception as e:
        _push("queue_health", "WARN", str(e))

    # Brain sync lag: sync_state.last_trade_id vs role max(trades.id)
    try:
        lag_rows: list[dict] = []
        with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                if _table_exists("brain", "sync_state"):
                    cur.execute("SELECT role, last_trade_id FROM brain.sync_state")
                    sync_rows = list(cur.fetchall() or [])
                else:
                    sync_rows = []
                for role in ("paper", "live", "pump"):
                    schema = _schema_for_role(role)
                    max_id = 0
                    if _table_exists(schema, "trades"):
                        cur.execute(f"SELECT COALESCE(MAX(id),0) AS max_id FROM {schema}.trades")
                        max_id = int((cur.fetchone() or {}).get("max_id") or 0)
                    last_trade_id = 0
                    for sr in sync_rows:
                        if str(sr.get("role") or "").lower() == role:
                            last_trade_id = int(sr.get("last_trade_id") or 0)
                            break
                    lag_rows.append({"role": role, "last_trade_id": last_trade_id, "max_trade_id": max_id, "lag": max(0, max_id - last_trade_id)})
        max_lag = max([int(r["lag"]) for r in lag_rows], default=0)
        sev = "OK" if max_lag <= 200 else ("WARN" if max_lag <= 1000 else "CRIT")
        _push("brain_sync_lag", sev, f"max_lag={max_lag}", lag_rows)
    except Exception as e:
        _push("brain_sync_lag", "WARN", str(e))

    # Pre-live checks: strategy/risk/runtime safety.
    try:
        _ensure_strategy_risk_tables()
        runtimes = {str(r.get("role") or ""): r for r in _role_runtime_rows()}
        strategy_cfg_paper = _strategy_config_map("paper")
        enabled_paper = [sid for sid, row in strategy_cfg_paper.items() if bool(row.get("enabled"))]
        for role in ("paper", "live", "pump"):
            rr = runtimes.get(role) or _role_runtime_get(role)
            profile_id = str((rr or {}).get("active_risk_profile") or "")
            if profile_id:
                _push(f"risk_profile_attached_{role}", "OK", f"profile={profile_id}")
            else:
                _push(f"risk_profile_attached_{role}", "CRIT", "no active_risk_profile attached")
            exec_mode = str((rr or {}).get("execution_mode") or "").upper()
            sev = "OK" if exec_mode in RUNTIME_EXECUTION_MODES else "CRIT"
            _push(
                f"execution_mode_{role}",
                sev,
                f"execution_mode={exec_mode} (expected one of {', '.join(RUNTIME_EXECUTION_MODES)})",
            )
        if enabled_paper:
            _push("strategy_enabled_paper", "OK", f"enabled={len(enabled_paper)}", enabled_paper)
        else:
            _push("strategy_enabled_paper", "CRIT", "no enabled strategies for paper role")

        traces_recent = 0
        schema = _schema_for_role("paper")
        if _table_exists(schema, "decision_traces"):
            with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT COUNT(*) AS n FROM {schema}.decision_traces WHERE created_at_ms >= %s", (_ms_now() - 30 * 60 * 1000,))
                    traces_recent = int((cur.fetchone() or {}).get("n") or 0)
        _push(
            "decision_traces_flowing",
            "OK" if traces_recent > 0 else "WARN",
            f"recent_30m={traces_recent}",
        )
    except Exception as e:
        _push("strategy_risk_runtime", "WARN", str(e))

    # Test/PAPER safe posture check.
    try:
        secret = _load_integration_secret("binance")
        if not secret:
            _push("keys_absent_test_mode", "OK", "Binance keys absent (expected for TEST/PAPER phase).")
        else:
            _push("keys_absent_test_mode", "WARN", "Binance keys are configured; verify live execution remains disabled.")
    except Exception as e:
        _push("keys_absent_test_mode", "WARN", str(e))

    if run_tests:
        # Write path test: insert diagnostic command and verify persistence.
        try:
            trace_id = uuid.uuid4().hex
            row = _insert_command_queue(
                role="paper",
                target="doctor",
                action="write_path_test",
                payload={"source": "doctor", "ts_utc": _utc_iso_now()},
                trace_id=trace_id,
                dedupe_key=f"doctor-write-{trace_id}",
                force=True,
            )
            ok = bool(row.get("id"))
            _push("write_path_test", "OK" if ok else "CRIT", f"command_id={row.get('id')}", row)
        except Exception as e:
            _push("write_path_test", "CRIT", str(e))

        # Event ingestion test: insert and re-read one event.
        try:
            test_trace = uuid.uuid4().hex
            payload = {"trace_id": test_trace, "kind": "doctor_event_ingestion_test", "ts_utc": _utc_iso_now()}
            with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {EVENTS_TABLE} (bot_role, event_type, data)
                        VALUES (%s, %s, %s::jsonb)
                        RETURNING id
                        """,
                        ("gateway", "DOCTOR_EVENT_TEST", json.dumps(payload)),
                    )
                    ins = cur.fetchone() or {}
                    event_id = int(ins.get("id") or 0)
                    cur.execute(f"SELECT id FROM {EVENTS_TABLE} WHERE id = %s", (event_id,))
                    chk = cur.fetchone() or {}
            ok = bool(chk.get("id"))
            _push("event_ingestion_test", "OK" if ok else "CRIT", f"event_id={event_id}")
        except Exception as e:
            _push("event_ingestion_test", "CRIT", str(e))

    # Emit incident events for alerting pipelines (best-effort).
    try:
        for chk in checks:
            sev = str(chk.get("severity") or "").upper()
            if sev not in {"CRIT", "ERROR", "WARN"}:
                continue
            name = str(chk.get("name") or "")
            details = str(chk.get("details") or "")
            if not name:
                continue
            event_type = "INCIDENT_WARN"
            if "lag" in name.lower():
                event_type = "INCIDENT_SYNC_LAG"
            elif "heartbeat" in name.lower() or "service" in name.lower():
                event_type = "INCIDENT_SERVICE_DOWN" if sev in {"CRIT", "ERROR"} else "INCIDENT_SERVICE_WARN"
            elif "kill_switch" in details.lower() or "kill switch" in details.lower():
                event_type = "INCIDENT_KILL_SWITCH"
            elif "daily loss" in details.lower() or "drawdown" in details.lower() or "dd" in details.lower():
                event_type = "INCIDENT_DD_BREACH"
            payload = {
                "trace_id": uuid.uuid4().hex,
                "severity": sev,
                "name": name,
                "details": details,
                "suggested_fix": _doctor_suggested_fix(name, details),
                "ts_utc": _utc_iso_now(),
            }
            _insert_shared_event("gateway", event_type, payload)
    except Exception:
        pass

    crit = len([c for c in checks if str(c.get("severity")).upper() in ("CRIT", "ERROR")])
    warn = len([c for c in checks if str(c.get("severity")).upper() == "WARN"])
    return {"ok": crit == 0, "checks": checks, "summary": {"total": len(checks), "crit": crit, "warn": warn, "ok": len(checks) - crit - warn}}

@app.post("/api/doctor/run")
async def api_doctor_run():
    checks: list[dict] = []
    # DB connectivity
    try:
        with psycopg.connect(AUDIT_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        checks.append({"name": "db_connectivity", "severity": "OK", "details": "Connected", "suggested_fix": ""})
    except Exception as e:
        checks.append({"name": "db_connectivity", "severity": "CRIT", "details": str(e), "suggested_fix": "Verify Postgres DSN"})

    # Master key
    if not TRADING_MASTER_KEY:
        checks.append({"name": "master_key", "severity": "WARN", "details": "TRADING_MASTER_KEY missing", "suggested_fix": "Set TRADING_MASTER_KEY for encryption"})

    # Schema meta / required tables
    try:
        _ensure_gateway_phase4_tables(AUDIT_DSN)
        with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version FROM gateway.schema_meta ORDER BY applied_at DESC LIMIT 1")
                row = cur.fetchone()
                if not row:
                    checks.append({"name": "schema_meta", "severity": "WARN", "details": "schema_meta empty", "suggested_fix": "Recreate gateway schema"})
    except Exception as e:
        checks.append({"name": "schema_meta", "severity": "WARN", "details": str(e), "suggested_fix": ""})

    # Event lag
    try:
        rows = await _events_fetch(limit=1, order="desc")
        if rows:
            last = rows[0].get("created_at")
            checks.append({"name": "event_lag", "severity": "OK", "details": f"last_event={last}", "suggested_fix": ""})
        else:
            checks.append({"name": "event_lag", "severity": "WARN", "details": "No events found", "suggested_fix": "Ensure events pipeline is active"})
    except Exception as e:
        checks.append({"name": "event_lag", "severity": "WARN", "details": str(e), "suggested_fix": ""})

    # Restart loop detection
    try:
        rows = await asyncio.to_thread(fetch_audit_events, AUDIT_DSN, 50)
        recent = [r for r in rows if str(r.get("action")) in ("CONTROL_RESTART_MONITOR", "CONTROL_RESTART_BOT", "OPS_COMMAND")]
        if len(recent) >= 3:
            checks.append({"name": "restart_loop", "severity": "WARN", "details": f"restart actions in last 50 audit rows: {len(recent)}", "suggested_fix": "Clear restart req flags; check monitors"})
    except Exception:
        pass

    # Brain sync freshness
    try:
        sync = await _brain_get_json("/api/sync/status")
        checks.append({"name": "brain_sync", "severity": "OK", "details": "sync_status ok", "suggested_fix": "", "data": sync})
    except Exception as e:
        checks.append({"name": "brain_sync", "severity": "WARN", "details": str(e), "suggested_fix": "Check brain_api connectivity"})

    # Binance connectivity (best-effort)
    try:
        btest = await api_binance_test()
        if not btest.get("ok"):
            checks.append({"name": "binance_connectivity", "severity": "WARN", "details": btest.get("error"), "suggested_fix": "Check Binance keys"})
        else:
            checks.append({"name": "binance_connectivity", "severity": "OK", "details": "connected", "suggested_fix": ""})
    except Exception as e:
        checks.append({"name": "binance_connectivity", "severity": "WARN", "details": str(e), "suggested_fix": ""})

    # Telegram config
    settings = _load_alert_settings()
    if not settings.get("TELEGRAM_BOT_TOKEN") or not settings.get("TELEGRAM_CHAT_ID"):
        checks.append({"name": "telegram_alerts", "severity": "WARN", "details": "Telegram not configured", "suggested_fix": "Set bot token/chat_id"})

    return {"ok": True, "checks": checks}


@app.post("/api/doctor/fix/clear_restart")
async def api_doctor_fix_clear_restart(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    role = str(body.get("role") or "all")
    roles = _resolve_roles(role)
    for r in roles:
        schema = _schema_for_role(r)
        for key in ("restart_monitor_req", "restart_monitor_ack", "restart_bot_req", "restart_bot_ack"):
            try:
                _set_setting(schema, key, "")
            except Exception:
                continue
    return {"ok": True, "roles": roles}


@app.post("/api/doctor/fix/clear_commands")
async def api_doctor_fix_clear_commands(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    age_min = int(body.get("age_min") or 30)
    role = str(body.get("role") or "all")
    roles = _resolve_roles(role)
    _ensure_gateway_phase4_tables(AUDIT_DSN)
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE gateway.command_queue
                SET status = 'cancelled', executed_at = now()
                WHERE role = ANY(%s)
                  AND status IN ('queued', 'pending', 'in_progress')
                  AND created_at < (now() - (%s || ' minutes')::interval)
                """,
                (roles, int(age_min)),
            )
            cleared = cur.rowcount or 0
    return {"ok": True, "roles": roles, "cleared": int(cleared)}


def _doctor_suggested_fix(name: str, details: str) -> str:
    n = str(name or "").lower()
    d = str(details or "").lower()
    if "heartbeat" in n or "service" in n:
        return "Restart the affected bot/monitor service and verify heartbeat freshness."
    if "sync" in n or "lag" in n:
        return "Run sync job and inspect brain sync worker logs."
    if "kill_switch" in d or "kill switch" in d:
        return "Keep kill switch ON until risk conditions recover, then clear from Unified Dashboard."
    if "daily loss" in d or "dd" in d or "drawdown" in d:
        return "Reduce risk caps and pause live execution until drawdown normalizes."
    if "error" in n or "error" in d:
        return "Inspect recent logs and fix the root cause before resuming automation."
    return "Inspect diagnostics and resolve the failing dependency."


@app.get("/api/doctor/incidents")
async def api_doctor_incidents(limit: int = 50):
    lim = max(1, min(int(limit or 50), 200))
    items: list[dict] = []

    # 1) Recent incident/error events from shared event bus.
    try:
        _ensure_events_table(AUDIT_DSN)
        with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, bot_role, event_type, data, created_at
                    FROM {EVENTS_TABLE}
                    WHERE UPPER(event_type) LIKE '%%ERROR%%'
                       OR UPPER(event_type) LIKE '%%INCIDENT%%'
                       OR UPPER(event_type) LIKE '%%KILL_SWITCH%%'
                       OR UPPER(event_type) LIKE '%%SYNC_LAG%%'
                       OR UPPER(event_type) LIKE '%%DD_BREACH%%'
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (lim,),
                )
                for row in (cur.fetchall() or []):
                    data = row.get("data")
                    payload = data if isinstance(data, dict) else _safe_json_loads(data, {})
                    message = str(
                        (payload or {}).get("message")
                        or (payload or {}).get("details")
                        or row.get("event_type")
                        or "incident"
                    )
                    trace_id = str((payload or {}).get("trace_id") or "")
                    items.append(
                        {
                            "source": "shared_events",
                            "id": int(row.get("id") or 0),
                            "role": str(row.get("bot_role") or "all"),
                            "severity": "CRIT" if "CRIT" in str(row.get("event_type") or "").upper() else "WARN",
                            "name": str(row.get("event_type") or "INCIDENT"),
                            "message": message,
                            "suggested_fix": _doctor_suggested_fix(str(row.get("event_type") or ""), message),
                            "trace_id": trace_id,
                            "ts_utc": str(row.get("created_at") or ""),
                        }
                    )
    except Exception:
        pass

    # 2) Role logs fallback to include last errors if event bus is quiet.
    if len(items) < lim:
        per_role_lim = max(5, min(30, lim // 3 or 10))
        for role in ("paper", "live", "pump"):
            schema = _schema_for_role(role)
            try:
                rows = _fetch_logs(schema, level="ERROR", limit=per_role_lim)
            except Exception:
                rows = []
            for row in rows:
                ts_val = row.get("timestamp") or row.get("time") or row.get("created_at") or row.get("timestamp_ms") or row.get("created_at_ms")
                trace_id = str(row.get("trace_id") or "")
                message = str(row.get("message") or row.get("msg") or "error")
                items.append(
                    {
                        "source": f"{schema}.logs",
                        "id": int(row.get("id") or 0) if str(row.get("id") or "").isdigit() else 0,
                        "role": role,
                        "severity": "CRIT" if "CRIT" in str(row.get("level") or "").upper() else "WARN",
                        "name": str(row.get("level") or row.get("lvl") or "ERROR"),
                        "message": message,
                        "suggested_fix": _doctor_suggested_fix("log_error", message),
                        "trace_id": trace_id,
                        "ts_utc": str(ts_val or ""),
                    }
                )

    # 3) Keep only most recent rows.
    def _incident_ts(x: dict) -> int:
        return _parse_ts_ms(str(x.get("ts_utc") or "")) or 0

    out = sorted(items, key=_incident_ts, reverse=True)[:lim]
    return {"ok": True, "items": out, "count": len(out)}


# ---------------------------
# Phase 4: API Index + Webhooks
# ---------------------------

@app.get("/api/api-index")
async def api_index():
    groups = {
        "ops": [
            "/api/ops/status",
            "/api/ops/positions",
            "/api/ops/errors",
            "/api/ops/logs",
            "/api/ops/logs/stream",
            "/api/ops/command",
            "/api/ops/db_fingerprint",
            "/api/ops/runtime",
            "/api/ops/ui_actions",
            "/api/system/db_wiring",
        ],
        "unified": ["/api/unified/overview", "/api/unified/{role}/signals", "/api/unified/{role}/trades", "/api/unified/{role}/commands"],
        "portfolio": [
            "/api/portfolio/summary",
            "/api/portfolio/trades",
            "/api/portfolio/fees",
            "/api/portfolio/export.csv",
            "/api/portfolio/binance/account",
            "/api/portfolio/binance/export.csv",
            "/api/integrations/binance/*",
        ],
        "reports": ["/api/reports/paper-arena", "/api/reports/analytics", "/api/reports/audit/trace", "/api/reports/data-quality"],
        "doctor": ["/api/doctor/run", "/api/doctor/checks", "/api/doctor/incidents", "/api/doctor/fix/clear_restart", "/api/doctor/fix/clear_commands"],
        "learn": ["/api/learn/status", "/api/learn/sync", "/api/learn/train", "/api/learn/promote", "/api/learn/rollback", "/api/learn/kpis", "/api/learn/backtest", "/api/learn/config"],
        "live_safety": ["/api/live/safety_policy", "/api/live/rollout"],
        "strategy_risk": ["/api/strategies", "/api/risk/profiles", "/api/runtime/role"],
        "manual_ops": ["/api/manual/execute", "/api/snapshot"],
        "pump": ["/api/pump/candidates/promote"],
        "alerts": ["/api/alerts/telegram/settings", "/api/alerts/telegram/test", "/api/alerts/rules", "/api/alerts/history"],
        "webhooks": ["/api/webhooks", "/api/webhooks/test/{id}"],
        "brain_proxy": ["/api/brain/{path}"],
        "mina_proxy": ["/api/mina/{role}/{path}"],
    }
    return {
        "ok": True,
        "gateway": ["/api/ops/status", "/api/ops/positions", "/api/ops/errors", "/api/ops/logs", "/api/ops/logs/stream", "/api/pipeline/status", "/api/system/db_wiring"],
        "brain": ["/api/brain/*"],
        "mina": ["/api/mina/{role}/*"],
        "groups": groups,
    }


def _default_api_docs_registry() -> Dict[str, Any]:
    return {
        "ok": True,
        "generated_at": _utc_iso_now(),
        "endpoints": [
            {
                "method": "GET",
                "route": "/api/ops/status",
                "description": "Aggregated monitor state per role.",
                "sample_curl": "curl -s http://localhost:8200/api/ops/status?role=paper",
            },
            {
                "method": "POST",
                "route": "/api/ops/command",
                "description": "Queue start/stop/restart style operations through command queue.",
                "sample_curl": "curl -s -X POST http://localhost:8200/api/ops/command -H 'Content-Type: application/json' -d '{\"role\":\"paper\",\"target\":\"bot\",\"action\":\"restart\"}'",
            },
            {
                "method": "GET",
                "route": "/api/ops/db_fingerprint",
                "description": "Single-DB runtime fingerprint (database, host, schemas, version).",
                "sample_curl": "curl -s http://localhost:8200/api/ops/db_fingerprint",
            },
            {
                "method": "GET",
                "route": "/api/ops/runtime?role=pump",
                "description": "Runtime state per role including pump entrypoint and heartbeat.",
                "sample_curl": "curl -s 'http://localhost:8200/api/ops/runtime?role=pump'",
            },
            {
                "method": "GET",
                "route": "/api/portfolio/summary",
                "description": "Portfolio KPIs by role for a UTC date range.",
                "sample_curl": "curl -s 'http://localhost:8200/api/portfolio/summary?role=live&from=2026-02-01T00:00:00Z&to=2026-02-06T00:00:00Z'",
            },
            {
                "method": "GET",
                "route": "/api/portfolio/binance/account",
                "description": "Binance balances/positions plus realized/unrealized pnl and fees (read-only).",
                "sample_curl": "curl -s 'http://localhost:8200/api/portfolio/binance/account?from=2026-02-01T00:00:00Z&to=2026-02-06T00:00:00Z'",
            },
            {
                "method": "GET",
                "route": "/api/portfolio/export.csv",
                "description": "Export role trades in CSV for UTC window.",
                "sample_curl": "curl -s 'http://localhost:8200/api/portfolio/export.csv?role=live' -o portfolio.csv",
            },
            {
                "method": "GET",
                "route": "/api/brain/inspector/overview",
                "description": "Brain inspector summary backed by Postgres.",
                "sample_curl": "curl -s 'http://localhost:8200/api/brain/inspector/overview?role=paper'",
            },
            {
                "method": "GET",
                "route": "/api/brain/inspector/traces?limit=20",
                "description": "Decision trace alias endpoint (backward compatible).",
                "sample_curl": "curl -s 'http://localhost:8200/api/brain/inspector/traces?limit=20'",
            },
            {
                "method": "POST",
                "route": "/api/manual/execute",
                "description": "Manual execute command with trace_id audit, queue row, and simulated paper execution.",
                "sample_curl": "curl -s -X POST http://localhost:8200/api/manual/execute -H 'Content-Type: application/json' -d '{\"role\":\"paper\",\"symbol\":\"BTCUSDT\",\"amount_usd\":100,\"market\":\"futures\",\"direction\":\"LONG\"}'",
            },
            {
                "method": "POST",
                "route": "/api/snapshot",
                "description": "Point-in-time snapshot for indicators/regime/pump-score at a UTC timestamp.",
                "sample_curl": "curl -s -X POST http://localhost:8200/api/snapshot -H 'Content-Type: application/json' -d '{\"role\":\"paper\",\"symbol\":\"SOLUSDT\",\"market\":\"futures\",\"interval\":\"5m\",\"at_utc\":\"2026-02-06T12:30:00Z\"}'",
            },
            {
                "method": "GET",
                "route": "/api/live/safety_policy",
                "description": "Live safety policy and runtime risk snapshot.",
                "sample_curl": "curl -s http://localhost:8200/api/live/safety_policy",
            },
            {
                "method": "POST",
                "route": "/api/live/rollout",
                "description": "Set rollout stage LIVE-0/LIVE-1/LIVE-2.",
                "sample_curl": "curl -s -X POST http://localhost:8200/api/live/rollout -H 'Content-Type: application/json' -d '{\"stage\":\"LIVE-1\"}'",
            },
            {
                "method": "GET",
                "route": "/api/strategies",
                "description": "Strategy registry + role configs + runtime/risk context.",
                "sample_curl": "curl -s 'http://localhost:8200/api/strategies?role=paper'",
            },
            {
                "method": "POST",
                "route": "/api/strategies",
                "description": "Update DB-backed strategy config for a role.",
                "sample_curl": "curl -s -X POST http://localhost:8200/api/strategies -H 'Content-Type: application/json' -d '{\"strategy_id\":\"BASELINE_SCALP\",\"role\":\"paper\",\"enabled\":true}'",
            },
            {
                "method": "GET",
                "route": "/api/risk/profiles",
                "description": "Risk profile list and parameters stored in Postgres.",
                "sample_curl": "curl -s http://localhost:8200/api/risk/profiles",
            },
            {
                "method": "GET",
                "route": "/api/runtime/role",
                "description": "Role runtime execution mode + active risk profile + live metrics.",
                "sample_curl": "curl -s 'http://localhost:8200/api/runtime/role?role=paper'",
            },
            {
                "method": "GET",
                "route": "/api/doctor/incidents",
                "description": "Incident feed with suggested fixes and trace ids.",
                "sample_curl": "curl -s 'http://localhost:8200/api/doctor/incidents?limit=50'",
            },
            {
                "method": "POST",
                "route": "/api/notifications/test",
                "description": "Send Telegram test message using stored notification settings.",
                "sample_curl": "curl -s -X POST http://localhost:8200/api/notifications/test",
            },
        ],
        "webhook_integration": {
            "inbound_endpoint": "/api/webhooks",
            "auth": {
                "header": "X-Webhook-Token",
                "description": "Set a shared token in gateway settings and send it in every inbound webhook request.",
            },
            "sample_curl": "curl -s -X POST http://localhost:8200/api/webhooks -H 'Content-Type: application/json' -H 'X-Webhook-Token: <token>' -d '{\"event_type\":\"SignalEvent\"}'",
        },
    }


@app.get("/api/api-docs/registry")
async def api_docs_registry():
    if API_DOCS_REGISTRY_PATH.exists():
        try:
            loaded = json.loads(API_DOCS_REGISTRY_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                loaded.setdefault("ok", True)
                loaded.setdefault("generated_at", _utc_iso_now())
                return loaded
        except Exception:
            pass
    return _default_api_docs_registry()


@app.post("/api/webhooks")
async def api_webhooks_create(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    url = str(body.get("url") or "").strip()
    secret = str(body.get("secret") or "").strip()
    event_types = body.get("event_types") or []
    enabled = bool(body.get("enabled", True))
    if not url:
        raise HTTPException(status_code=400, detail="url required")
    secret_hash = hash_secret(secret) if secret else None
    _ensure_gateway_phase4_tables(AUDIT_DSN)
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO gateway.webhooks(url, secret_hash, event_types, enabled) VALUES (%s, %s, %s::jsonb, %s) RETURNING id",
                (url, secret_hash, json.dumps(event_types), enabled),
            )
            row = cur.fetchone()
            webhook_id = int(row["id"]) if row else 0
    if secret:
        _save_integration_secret(f"webhook:{webhook_id}", {"secret": secret})
    return {"ok": True, "id": webhook_id}


@app.get("/api/webhooks")
async def api_webhooks_list():
    _ensure_gateway_phase4_tables(AUDIT_DSN)
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, url, event_types, enabled, created_at, updated_at FROM gateway.webhooks ORDER BY id DESC")
            rows = list(cur.fetchall())
    return {"ok": True, "items": rows}


@app.patch("/api/webhooks/{webhook_id}")
async def api_webhooks_update(webhook_id: int, request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    fields = []
    params: list[Any] = []
    if "url" in body:
        fields.append("url = %s")
        params.append(str(body["url"]))
    if "enabled" in body:
        fields.append("enabled = %s")
        params.append(bool(body["enabled"]))
    if "event_types" in body:
        fields.append("event_types = %s::jsonb")
        params.append(json.dumps(body["event_types"]))
    if "secret" in body:
        secret = str(body.get("secret") or "")
        fields.append("secret_hash = %s")
        params.append(hash_secret(secret))
        _save_integration_secret(f"webhook:{webhook_id}", {"secret": secret})
    if not fields:
        return {"ok": True}
    params.append(int(webhook_id))
    q = f"UPDATE gateway.webhooks SET {', '.join(fields)}, updated_at = now() WHERE id = %s"
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(q, params)
    return {"ok": True}


@app.delete("/api/webhooks/{webhook_id}")
async def api_webhooks_delete(webhook_id: int):
    _ensure_gateway_phase4_tables(AUDIT_DSN)
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM gateway.webhooks WHERE id = %s", (int(webhook_id),))
            cur.execute("DELETE FROM gateway.integration_secrets WHERE name = %s", (f"webhook:{int(webhook_id)}",))
    return {"ok": True}


@app.post("/api/webhooks/test/{webhook_id}")
async def api_webhooks_test(webhook_id: int):
    secret = _load_integration_secret(f"webhook:{int(webhook_id)}").get("secret", "")
    payload = {"event_type": "TEST", "ts_utc": dt.datetime.utcnow().isoformat() + "Z"}
    signature = hmac.new(secret.encode("utf-8"), json.dumps(payload).encode("utf-8"), hashlib.sha256).hexdigest()
    _ensure_gateway_phase4_tables(AUDIT_DSN)
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT url FROM gateway.webhooks WHERE id = %s", (int(webhook_id),))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="webhook_not_found")
            url = row["url"]
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            await c.post(url, json=payload, headers={"X-Webhook-Signature": signature})
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


# ---------------------------
# Phase 4: Learn endpoints
# ---------------------------

def _ensure_brain_learning_tables() -> None:
    ddl = """
    CREATE SCHEMA IF NOT EXISTS brain;
    CREATE TABLE IF NOT EXISTS brain.learning_state (
      id BIGINT PRIMARY KEY DEFAULT 1,
      training_enabled BOOLEAN NOT NULL DEFAULT TRUE,
      last_training_run TIMESTAMPTZ,
      last_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
      candidate_model_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
      deployed_model_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
      previous_deployed_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
      thresholds JSONB NOT NULL DEFAULT '{}'::jsonb,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    INSERT INTO brain.learning_state (id)
    VALUES (1)
    ON CONFLICT (id) DO NOTHING;
    """
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)


def _get_learning_state_row() -> Dict[str, Any]:
    _ensure_brain_learning_tables()
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM brain.learning_state WHERE id = 1 LIMIT 1")
            row = dict(cur.fetchone() or {})
    row.setdefault("training_enabled", True)
    row.setdefault("last_metrics", {})
    row.setdefault("candidate_model_versions", {})
    row.setdefault("deployed_model_versions", {})
    row.setdefault("previous_deployed_versions", {})
    row.setdefault("thresholds", {})
    return row


def _update_learning_state(
    *,
    training_enabled: Optional[bool] = None,
    last_metrics: Optional[Dict[str, Any]] = None,
    candidate_model_versions: Optional[Dict[str, Any]] = None,
    deployed_model_versions: Optional[Dict[str, Any]] = None,
    previous_deployed_versions: Optional[Dict[str, Any]] = None,
    thresholds: Optional[Dict[str, Any]] = None,
    set_last_training_run_now: bool = False,
) -> Dict[str, Any]:
    _ensure_brain_learning_tables()
    fields: list[str] = ["updated_at = now()"]
    values: list[Any] = []
    if training_enabled is not None:
        fields.append("training_enabled = %s")
        values.append(bool(training_enabled))
    if last_metrics is not None:
        fields.append("last_metrics = %s::jsonb")
        values.append(json.dumps(last_metrics))
    if candidate_model_versions is not None:
        fields.append("candidate_model_versions = %s::jsonb")
        values.append(json.dumps(candidate_model_versions))
    if deployed_model_versions is not None:
        fields.append("deployed_model_versions = %s::jsonb")
        values.append(json.dumps(deployed_model_versions))
    if previous_deployed_versions is not None:
        fields.append("previous_deployed_versions = %s::jsonb")
        values.append(json.dumps(previous_deployed_versions))
    if thresholds is not None:
        fields.append("thresholds = %s::jsonb")
        values.append(json.dumps(thresholds))
    if set_last_training_run_now:
        fields.append("last_training_run = now()")

    if len(fields) > 1:
        with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f"UPDATE brain.learning_state SET {', '.join(fields)} WHERE id = 1", values)
    return _get_learning_state_row()


def _default_learn_config() -> Dict[str, Any]:
    return {
        "window_days": 30,
        "high_conf_threshold": 0.75,
        "abstain_threshold": 0.55,
        "label_rule": "pnl_gt_0",
        "calibration": {"enabled": True, "method": "isotonic"},
        "veto_filters": {"max_spread_bps": 20, "min_liquidity_usd": 100000},
        "dynamic_thresholds": {
            "bull": {"min_confidence": 0.70},
            "bear": {"min_confidence": 0.80},
            "sideways": {"min_confidence": 0.85},
        },
    }


def _learn_config() -> Dict[str, Any]:
    raw = _get_gateway_setting("learn_config_json", "{}")
    try:
        cfg = json.loads(raw)
    except Exception:
        cfg = {}
    base = _default_learn_config()
    if isinstance(cfg, dict):
        base.update(cfg)
    return base


def _learning_kpis_for_role(role: str, window_days: int | None = None) -> Dict[str, Any]:
    r = _validate_role(role)
    schema = _schema_for_role(r)
    cfg = _learn_config()
    days = max(1, int(window_days or cfg.get("window_days") or 30))
    high_conf = _as_float(cfg.get("high_conf_threshold"), 0.75)
    from_ms = _ms_now() - int(days * 24 * 3600 * 1000)
    split_ms = _ms_now() - int(min(7, days) * 24 * 3600 * 1000)

    if not _table_exists(schema, "trades"):
        return {
            "ok": True,
            "role": r,
            "window_days": days,
            "precision_high_confidence": 0.0,
            "abstention_rate": 0.0,
            "drift_score": 0.0,
            "total_samples": 0,
            "notes": "trades_table_missing",
        }

    cols = _table_columns(schema, "trades")
    pnl_col = "pnl" if "pnl" in cols else ("realized_pnl" if "realized_pnl" in cols else None)
    conf_col = "confidence" if "confidence" in cols else ("score" if "score" in cols else None)
    time_col = "closed_at_ms" if "closed_at_ms" in cols else ("created_at_ms" if "created_at_ms" in cols else None)
    status_col = "status" if "status" in cols else None

    precision = 0.0
    abstention = 0.0
    drift_score = 0.0
    total_samples = 0
    recent_win = 0.0
    prev_win = 0.0

    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            where = []
            params: list[Any] = []
            if status_col:
                where.append("UPPER(status) = 'CLOSED'")
            if time_col:
                where.append(f"{time_col} >= %s")
                params.append(from_ms)
            where_sql = ("WHERE " + " AND ".join(where)) if where else ""
            if pnl_col:
                cur.execute(f"SELECT COUNT(*) AS n FROM {schema}.trades {where_sql}", params)
                total_samples = int((cur.fetchone() or {}).get("n") or 0)
            if pnl_col and conf_col:
                cur.execute(
                    f"""
                    SELECT
                        SUM(CASE WHEN {conf_col} >= %s AND {pnl_col} > 0 THEN 1 ELSE 0 END) AS wins_hc,
                        SUM(CASE WHEN {conf_col} >= %s THEN 1 ELSE 0 END) AS total_hc
                    FROM {schema}.trades
                    {where_sql}
                    """,
                    [high_conf, high_conf, *params],
                )
                row = cur.fetchone() or {}
                wins_hc = int(row.get("wins_hc") or 0)
                total_hc = int(row.get("total_hc") or 0)
                precision = round((wins_hc / total_hc) * 100.0, 2) if total_hc > 0 else 0.0

            if pnl_col and time_col:
                cur.execute(
                    f"""
                    SELECT
                        SUM(CASE WHEN {time_col} >= %s AND {pnl_col} > 0 THEN 1 ELSE 0 END) AS recent_wins,
                        SUM(CASE WHEN {time_col} >= %s THEN 1 ELSE 0 END) AS recent_n,
                        SUM(CASE WHEN {time_col} < %s AND {time_col} >= %s AND {pnl_col} > 0 THEN 1 ELSE 0 END) AS prev_wins,
                        SUM(CASE WHEN {time_col} < %s AND {time_col} >= %s THEN 1 ELSE 0 END) AS prev_n
                    FROM {schema}.trades
                    {where_sql}
                    """,
                    [split_ms, split_ms, split_ms, from_ms, split_ms, from_ms, *params],
                )
                row = cur.fetchone() or {}
                recent_wins = int(row.get("recent_wins") or 0)
                recent_n = int(row.get("recent_n") or 0)
                prev_wins = int(row.get("prev_wins") or 0)
                prev_n = int(row.get("prev_n") or 0)
                recent_win = round((recent_wins / recent_n) * 100.0, 2) if recent_n > 0 else 0.0
                prev_win = round((prev_wins / prev_n) * 100.0, 2) if prev_n > 0 else 0.0
                drift_score = round(recent_win - prev_win, 2)

    # Abstention rate from decision traces if available.
    if _table_exists(schema, "decision_traces"):
        cols_dt = _table_columns(schema, "decision_traces")
        dcol = "decision" if "decision" in cols_dt else None
        tcol = "created_at_ms" if "created_at_ms" in cols_dt else None
        if dcol:
            with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    where = []
                    params: list[Any] = []
                    if tcol:
                        where.append(f"{tcol} >= %s")
                        params.append(from_ms)
                    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
                    cur.execute(
                        f"""
                        SELECT
                          SUM(CASE WHEN UPPER(COALESCE({dcol},'')) IN ('WAIT','ABSTAIN','NO_TRADE','DO_NOT_TRADE') THEN 1 ELSE 0 END) AS abstain_n,
                          COUNT(*) AS n
                        FROM {schema}.decision_traces
                        {where_sql}
                        """,
                        params,
                    )
                    row = cur.fetchone() or {}
                    abstain_n = int(row.get("abstain_n") or 0)
                    n = int(row.get("n") or 0)
                    abstention = round((abstain_n / n) * 100.0, 2) if n > 0 else 0.0

    return {
        "ok": True,
        "role": r,
        "window_days": days,
        "high_conf_threshold": high_conf,
        "precision_high_confidence": precision,
        "abstention_rate": abstention,
        "drift_score": drift_score,
        "recent_win_rate": recent_win,
        "previous_win_rate": prev_win,
        "total_samples": total_samples,
    }


@app.get("/api/learn/state")
async def api_learn_state():
    row = _get_learning_state_row()
    cfg = _learn_config()
    window_days = _as_int(cfg.get("window_days"), 30)
    kpis = {r: _learning_kpis_for_role(r, window_days=window_days) for r in ("paper", "live", "pump")}
    return {"ok": True, "state": row, "config": cfg, "kpis": kpis}

@app.get("/api/learn/status")
async def api_learn_status():
    out: dict[str, Any] = {"ok": True, "brain": None, "sync": None, "state": None}
    try:
        out["state"] = _get_learning_state_row()
    except Exception as e:
        out["state"] = {"ok": False, "error": str(e)}
    try:
        out["config"] = _learn_config()
    except Exception as e:
        out["config"] = {"ok": False, "error": str(e)}
    try:
        out["brain"] = await _brain_get_json("/api/overview")
    except Exception as e:
        out["brain"] = {"ok": False, "error": str(e)}
    try:
        out["sync"] = await _brain_get_json("/api/sync/status")
    except Exception as e:
        out["sync"] = {"ok": False, "error": str(e)}
    return out


@app.get("/api/learn/kpis")
async def api_learn_kpis(role: str = "all", window_days: int | None = None):
    roles = _resolve_roles(role)
    out: Dict[str, Any] = {"ok": True, "role": role, "items": {}, "window_days": window_days}
    for r in roles:
        out["items"][r] = _learning_kpis_for_role(r, window_days=window_days)
    return out


@app.post("/api/learn/sync")
async def api_learn_sync(request: Request):
    trace_id = _trace_id_from_request(request)
    res = await _post_json(f"{BRAIN_API_URL}/api/sync/run", headers={"X-Trace-Id": trace_id})
    return {"ok": True, "job_id": trace_id, "result": res}


@app.post("/api/learn/train")
async def api_learn_train(request: Request):
    trace_id = _trace_id_from_request(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    role = str(body.get("role") or "paper").strip().lower()
    if role not in ("paper", "live", "pump"):
        role = "paper"
    if role == "live":
        _enforce_live_write_confirmation(role="live", action="LEARN_TRAIN", body=body, request=request)

    cfg = _learn_config()
    window_days = max(1, _as_int(body.get("window_days") or cfg.get("window_days"), 30))
    kpis = _learning_kpis_for_role(role, window_days=window_days)
    current = _get_learning_state_row()
    candidate = dict(_safe_json_loads(current.get("candidate_model_versions"), {}) or {})
    deployed_versions = dict(_safe_json_loads(current.get("deployed_model_versions"), {}) or {})
    prev = str(candidate.get(role) or deployed_versions.get(role) or "v0")
    try:
        n = int("".join(ch for ch in str(prev) if ch.isdigit()) or "0")
    except Exception:
        n = 0
    next_version = f"v{n + 1}"
    candidate[role] = next_version

    metrics = {
        "role": role,
        "trace_id": trace_id,
        "trained_at": _utc_iso_now(),
        "window_days": window_days,
        "label_rule": str(body.get("label_rule") or cfg.get("label_rule") or "pnl_gt_0"),
        "calibration": body.get("calibration") if isinstance(body.get("calibration"), dict) else cfg.get("calibration"),
        "veto_filters": body.get("veto_filters") if isinstance(body.get("veto_filters"), dict) else cfg.get("veto_filters"),
        "dynamic_thresholds": body.get("dynamic_thresholds") if isinstance(body.get("dynamic_thresholds"), dict) else cfg.get("dynamic_thresholds"),
        "kpis": kpis,
        "samples": int(kpis.get("total_samples") or 0),
        "win_rate": float(kpis.get("recent_win_rate") or 0.0),
    }
    thresholds_patch = body.get("thresholds") if isinstance(body.get("thresholds"), dict) else None
    merged_thresholds = dict(_safe_json_loads(current.get("thresholds"), {}) or {})
    if thresholds_patch:
        merged_thresholds.update(thresholds_patch)

    state = _update_learning_state(
        last_metrics=metrics,
        candidate_model_versions=candidate,
        thresholds=merged_thresholds if thresholds_patch else None,
        set_last_training_run_now=True,
    )
    return {"ok": True, "job_id": trace_id, "candidate_version": next_version, "state": state, "kpis": kpis}


@app.post("/api/learn/promote")
async def api_learn_promote(request: Request):
    trace_id = _trace_id_from_request(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    role = str(body.get("role") or "paper").strip().lower()
    if role not in ("paper", "live", "pump"):
        raise HTTPException(status_code=400, detail="role must be paper|live|pump")
    if role == "live":
        _enforce_live_write_confirmation(role="live", action="LEARN_PROMOTE", body=body, request=request)
    actor = _actor_from_request(request)

    row = _get_learning_state_row()
    candidate = dict(_safe_json_loads(row.get("candidate_model_versions"), {}) or {})
    deployed = dict(_safe_json_loads(row.get("deployed_model_versions"), {}) or {})
    previous = dict(_safe_json_loads(row.get("previous_deployed_versions"), {}) or {})
    target = str(body.get("version") or candidate.get(role) or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="candidate version missing for role")
    previous[role] = str(deployed.get(role) or "")
    deployed[role] = target
    state = _update_learning_state(
        deployed_model_versions=deployed,
        previous_deployed_versions=previous,
    )
    deploy_key = f"learn_deployed_{role}"
    old_cfg_raw = _get_gateway_setting(deploy_key, "{}")
    deploy_snapshot = {
        "role": role,
        "deployed_version": target,
        "previous_version": previous.get(role) or "",
        "trace_id": trace_id,
        "ts_utc": _utc_iso_now(),
        "config": _learn_config(),
    }
    _set_gateway_setting(deploy_key, json.dumps(deploy_snapshot, ensure_ascii=True), updated_by=actor)
    _audit_settings_change(deploy_key, old_cfg_raw, json.dumps(deploy_snapshot, ensure_ascii=True), trace_id, actor)
    return {"ok": True, "trace_id": trace_id, "role": role, "deployed_version": target, "state": state, "deploy_snapshot": deploy_snapshot}


@app.post("/api/learn/rollback")
async def api_learn_rollback(request: Request):
    trace_id = _trace_id_from_request(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    role = str(body.get("role") or "paper").strip().lower()
    if role not in ("paper", "live", "pump"):
        raise HTTPException(status_code=400, detail="role must be paper|live|pump")
    if role == "live":
        _enforce_live_write_confirmation(role="live", action="LEARN_ROLLBACK", body=body, request=request)
    actor = _actor_from_request(request)
    row = _get_learning_state_row()
    deployed = dict(_safe_json_loads(row.get("deployed_model_versions"), {}) or {})
    previous = dict(_safe_json_loads(row.get("previous_deployed_versions"), {}) or {})
    rollback_to = str(previous.get(role) or "").strip()
    if not rollback_to:
        raise HTTPException(status_code=400, detail="no previous deployed version")
    current = str(deployed.get(role) or "")
    deployed[role] = rollback_to
    previous[role] = current
    state = _update_learning_state(
        deployed_model_versions=deployed,
        previous_deployed_versions=previous,
    )
    deploy_key = f"learn_deployed_{role}"
    old_cfg_raw = _get_gateway_setting(deploy_key, "{}")
    deploy_snapshot = {
        "role": role,
        "deployed_version": rollback_to,
        "previous_version": current,
        "trace_id": trace_id,
        "ts_utc": _utc_iso_now(),
        "config": _learn_config(),
        "rollback": True,
    }
    _set_gateway_setting(deploy_key, json.dumps(deploy_snapshot, ensure_ascii=True), updated_by=actor)
    _audit_settings_change(deploy_key, old_cfg_raw, json.dumps(deploy_snapshot, ensure_ascii=True), trace_id, actor)
    return {"ok": True, "trace_id": trace_id, "role": role, "deployed_version": rollback_to, "state": state, "deploy_snapshot": deploy_snapshot}


@app.post("/api/learn/backtest")
async def api_learn_backtest(request: Request):
    trace_id = _trace_id_from_request(request)
    return {"ok": True, "job_id": trace_id}


@app.get("/api/learn/config")
async def api_learn_config():
    return {"ok": True, "config": _learn_config()}


@app.patch("/api/learn/config")
async def api_learn_config_update(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    actor = _actor_from_request(request)
    trace_id = _trace_id_from_request(request)
    old_val = _get_gateway_setting("learn_config_json", "{}")
    try:
        old_cfg = json.loads(old_val)
    except Exception:
        old_cfg = {}
    new_cfg = {**old_cfg, **body}
    _set_gateway_setting("learn_config_json", json.dumps(new_cfg), updated_by=actor)
    _audit_settings_change("learn_config_json", old_val, json.dumps(new_cfg), trace_id, actor)
    return {"ok": True, "config": new_cfg}


# ---------------------------
# Phase 4: Alerts endpoints
# ---------------------------

@app.get("/api/alerts/telegram/settings")
async def api_alerts_telegram_get():
    settings = _load_alert_settings()
    return {"ok": True, "settings": settings}


@app.patch("/api/alerts/telegram/settings")
async def api_alerts_telegram_update(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    _save_alert_settings(body)
    return {"ok": True}


@app.post("/api/alerts/telegram/test")
async def api_alerts_telegram_test():
    if not TRADING_MASTER_KEY:
        return {"ok": False, "error": "master_key_missing"}
    settings = _load_alert_settings()
    token = str(settings.get("TELEGRAM_BOT_TOKEN") or settings.get("token") or "")
    chat_id = str(settings.get("TELEGRAM_CHAT_ID") or settings.get("chat_id") or "")
    if not token or not chat_id:
        return {"ok": False, "error": "missing_settings"}
    payload = {"chat_id": chat_id, "text": "✅ Trading alerts test", "parse_mode": "Markdown"}
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            await c.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


@app.get("/api/alerts/rules")
async def api_alerts_rules_get():
    _ensure_gateway_phase4_tables(AUDIT_DSN)
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM gateway.alert_rules ORDER BY id DESC")
            rows = list(cur.fetchall())
    return {"ok": True, "items": rows}


@app.patch("/api/alerts/rules")
async def api_alerts_rules_update(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    _ensure_gateway_phase4_tables(AUDIT_DSN)
    enabled = bool(body.get("enabled", True))
    filters = body.get("filters") or {}
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO gateway.alert_rules(enabled, filters) VALUES (%s, %s::jsonb)",
                (enabled, json.dumps(filters)),
            )
    return {"ok": True}


@app.get("/api/alerts/history")
async def api_alerts_history(limit: int = 200):
    _ensure_gateway_phase4_tables(AUDIT_DSN)
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM gateway.alert_delivery_log ORDER BY id DESC LIMIT %s", (int(limit),))
            rows = list(cur.fetchall())
    return {"ok": True, "items": rows}


# ---------------------------
# Unified Notifications API
# ---------------------------

def _notification_settings_unpack(raw: str) -> Dict[str, Any]:
    txt = str(raw or "").strip()
    if not txt:
        return {}
    # Try encrypted first (preferred when TRADING_MASTER_KEY is set).
    if TRADING_MASTER_KEY:
        try:
            obj = decrypt_json(TRADING_MASTER_KEY, txt)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    try:
        obj = json.loads(txt)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _notification_settings_pack(obj: Dict[str, Any]) -> str:
    if TRADING_MASTER_KEY:
        return encrypt_json(TRADING_MASTER_KEY, obj)
    return json.dumps(obj, ensure_ascii=True)


def _get_notification_settings() -> Dict[str, Any]:
    raw = _get_gateway_setting("notifications_settings", "")
    return _notification_settings_unpack(raw)


def _save_notification_settings(payload: Dict[str, Any], actor: str = "gateway") -> Dict[str, Any]:
    cur = _get_notification_settings()
    merged = {**cur}
    for k, v in (payload or {}).items():
        # Ignore blank token updates (prevents accidental wipe from UI).
        if str(k).lower() in {"bot_token", "telegram_bot_token"} and str(v or "").strip() == "":
            continue
        merged[str(k)] = v
    packed = _notification_settings_pack(merged)
    _set_gateway_setting("notifications_settings", packed, updated_by=actor)
    return merged


@app.get("/api/notifications/settings")
async def api_notifications_settings_get():
    data = _get_notification_settings()
    token = str(data.get("bot_token") or data.get("telegram_bot_token") or "").strip()
    out = {
        "enabled": bool(data.get("enabled", False)),
        "notify_signals_created": bool(data.get("notify_signals_created", True)),
        "notify_signals_approved": bool(data.get("notify_signals_approved", True)),
        "notify_signals_opened": bool(data.get("notify_signals_opened", True)),
        "notify_signals_closed": bool(data.get("notify_signals_closed", True)),
        "notify_errors": bool(data.get("notify_errors", True)),
        "notify_service_down": bool(data.get("notify_service_down", True)),
        "notify_sync_lag": bool(data.get("notify_sync_lag", True)),
        "notify_error_spike": bool(data.get("notify_error_spike", True)),
        "notify_dd_breach": bool(data.get("notify_dd_breach", True)),
        "notify_kill_switch": bool(data.get("notify_kill_switch", True)),
        "chat_id": str(data.get("chat_id") or ""),
        "has_token": bool(token),
        "token_masked": (token[:3] + "***" + token[-3:]) if len(token) >= 8 else ("***" if token else ""),
        "patcher_settings_key": str(data.get("patcher_settings_key") or ""),
    }
    return {"ok": True, "settings": out}


@app.post("/api/notifications/settings")
async def api_notifications_settings_post(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    actor = _actor_from_request(request)
    saved = _save_notification_settings(body, actor=actor)
    # Keep alerts worker compatibility.
    try:
        _save_alert_settings(saved)
    except Exception:
        pass
    return await api_notifications_settings_get()


@app.post("/api/notifications/test")
async def api_notifications_test():
    data = _get_notification_settings()
    token = str(data.get("bot_token") or data.get("telegram_bot_token") or "").strip()
    chat_id = str(data.get("chat_id") or data.get("telegram_chat_id") or "").strip()
    if not token or not chat_id:
        return {"ok": False, "error": "missing_token_or_chat_id"}
    text = str(data.get("test_text") or "✅ Unified Dashboard notifications test")
    payload = {"chat_id": chat_id, "text": text}
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload)
        if r.status_code >= 400:
            return {"ok": False, "error": "telegram_error", "status_code": r.status_code}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------
# Brain Inspector (DB-backed)
# ---------------------------

@app.get("/api/brain/inspector/overview")
async def api_brain_inspector_overview(role: str = "all", limit: int = 500):
    roles = _resolve_roles(role)
    out = {"ok": True, "role": role, "roles": {}, "brain": {}}
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            for r in roles:
                schema = _schema_for_role(r)
                stats = {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "expectancy": 0.0}
                if _table_exists(schema, "trades"):
                    cols = _table_columns(schema, "trades")
                    pnl_col = "pnl" if "pnl" in cols else None
                    if pnl_col:
                        cur.execute(
                            f"""
                            SELECT COUNT(*) AS n,
                                   SUM(CASE WHEN {pnl_col} > 0 THEN 1 ELSE 0 END) AS wins,
                                   SUM(CASE WHEN {pnl_col} <= 0 THEN 1 ELSE 0 END) AS losses,
                                   AVG({pnl_col}) AS expectancy
                            FROM {schema}.trades
                            WHERE UPPER(COALESCE(status,''))='CLOSED'
                            """
                        )
                        row = cur.fetchone() or {}
                        trades_n = int(row.get("n") or 0)
                        wins = int(row.get("wins") or 0)
                        losses = int(row.get("losses") or 0)
                        stats = {
                            "trades": trades_n,
                            "wins": wins,
                            "losses": losses,
                            "win_rate": round((wins / trades_n) * 100.0, 2) if trades_n > 0 else 0.0,
                            "expectancy": float(row.get("expectancy") or 0.0),
                        }
                out["roles"][r] = stats

            if _table_exists("brain", "trade_features"):
                cur.execute("SELECT COUNT(*) AS n FROM brain.trade_features")
                n = int((cur.fetchone() or {}).get("n") or 0)
                out["brain"]["trade_features_count"] = n
                cur.execute("SELECT * FROM brain.trade_features ORDER BY id DESC LIMIT %s", (max(1, min(int(limit), 500)),))
                rows = [dict(r) for r in (cur.fetchall() or [])]
                out["brain"]["recent_features"] = rows[:10]
            else:
                out["brain"]["trade_features_count"] = 0
                out["brain"]["recent_features"] = []
    return out


@app.get("/api/brain/inspector/features_sample")
async def api_brain_inspector_features_sample(limit: int = 50):
    lim = max(1, min(int(limit or 50), 200))
    if not _table_exists("brain", "trade_features"):
        return {"ok": True, "items": [], "count": 0}
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM brain.trade_features ORDER BY id DESC LIMIT %s", (lim,))
            rows = [dict(r) for r in (cur.fetchall() or [])]
    return {"ok": True, "items": rows, "count": len(rows)}


@app.get("/api/brain/inspector/features")
async def api_brain_inspector_features_alias(limit: int = 50):
    """Backward-compatible alias for features sample."""
    return await api_brain_inspector_features_sample(limit=limit)


@app.get("/api/brain/inspector/decision_traces")
async def api_brain_inspector_decision_traces(
    role: str = "all",
    trace_id: str | None = None,
    decision_id: int | None = None,
    limit: int = 200,
):
    roles = _resolve_roles(role)
    lim = max(1, min(int(limit or 200), 500))
    items: list[dict] = []
    for r in roles:
        schema = _schema_for_role(r)
        if not _table_exists(schema, "decision_traces"):
            continue
        cols = _table_columns(schema, "decision_traces")
        where: list[str] = []
        params: list[Any] = []
        if decision_id is not None and "id" in cols:
            where.append("id = %s")
            params.append(int(decision_id))
        if trace_id and "trace" in cols:
            where.append("trace::text ILIKE %s")
            params.append(f"%{trace_id}%")
        q = f"SELECT * FROM {schema}.decision_traces"
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY id DESC LIMIT %s"
        params.append(lim)
        with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(q, params)
                rows = [dict(rr) for rr in (cur.fetchall() or [])]
        for row in rows:
            row["role"] = r
            if isinstance(row.get("trace"), str):
                parsed = _safe_json_loads(row.get("trace"), {})
                row["trace"] = parsed if isinstance(parsed, dict) else {}
        items.extend(rows)
    items.sort(key=lambda x: int(x.get("id") or 0), reverse=True)
    return {"ok": True, "items": items[:lim], "count": len(items[:lim])}


@app.get("/api/brain/inspector/traces")
async def api_brain_inspector_traces_alias(
    role: str = "all",
    trace_id: str | None = None,
    decision_id: int | None = None,
    limit: int = 200,
):
    """Backward-compatible alias for decision traces."""
    return await api_brain_inspector_decision_traces(
        role=role,
        trace_id=trace_id,
        decision_id=decision_id,
        limit=limit,
    )


def _insert_role_event(schema: str, event_type: str, payload: Dict[str, Any]) -> int:
    if not _table_exists(schema, "events"):
        return 0
    cols = _table_columns(schema, "events")
    fields: list[str] = []
    values: list[Any] = []
    if "created_at" in cols:
        fields.append("created_at")
        values.append(_utc_iso_now())
    if "created_at_ms" in cols:
        fields.append("created_at_ms")
        values.append(_ms_now())
    if "event_type" in cols:
        fields.append("event_type")
        values.append(str(event_type))
    if "type" in cols:
        fields.append("type")
        values.append(str(event_type))
    if "source" in cols:
        fields.append("source")
        values.append("gateway")
    if "payload_json" in cols:
        fields.append("payload_json")
        values.append(json.dumps(payload or {}, ensure_ascii=True))
    if "data" in cols:
        fields.append("data")
        values.append(json.dumps(payload or {}, ensure_ascii=True))
    if not fields:
        return 0
    placeholders = ",".join(["%s"] * len(fields))
    returning = " RETURNING id" if "id" in cols else ""
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {schema}.events ({', '.join(fields)}) VALUES ({placeholders}){returning}",
                values,
            )
            if "id" in cols:
                row = cur.fetchone() or {}
                return int(row.get("id") or 0)
    return 0


def _insert_role_log(schema: str, level: str, message: str, source: str = "gateway", payload: Dict[str, Any] | None = None) -> int:
    if not _table_exists(schema, "logs"):
        return 0
    cols = _table_columns(schema, "logs")
    fields: list[str] = []
    values: list[Any] = []
    lvl = str(level or "INFO").strip().upper()
    msg = str(message or "").strip()
    if "level" in cols:
        fields.append("level")
        values.append(lvl)
    if "msg" in cols:
        fields.append("msg")
        values.append(msg)
    if "message" in cols:
        fields.append("message")
        values.append(msg)
    if "created_at" in cols:
        fields.append("created_at")
        values.append(_utc_iso_now())
    if "created_at_ms" in cols:
        fields.append("created_at_ms")
        values.append(_ms_now())
    if "source" in cols:
        fields.append("source")
        values.append(str(source or "gateway"))
    if "payload_json" in cols:
        fields.append("payload_json")
        values.append(json.dumps(payload or {}, ensure_ascii=True))
    if "meta" in cols:
        fields.append("meta")
        values.append(json.dumps(payload or {}, ensure_ascii=True))
    if not fields:
        return 0
    placeholders = ",".join(["%s"] * len(fields))
    returning = " RETURNING id" if "id" in cols else ""
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {schema}.logs ({', '.join(fields)}) VALUES ({placeholders}){returning}",
                values,
            )
            if "id" in cols:
                row = cur.fetchone() or {}
                return int(row.get("id") or 0)
    return 0


def _command_lifecycle_mark(schema: str, command_id: int, *, ack: bool, executed: bool, note: str = "") -> None:
    if command_id <= 0 or (not _table_exists(schema, "commands")):
        return
    cols = _table_columns(schema, "commands")
    if "id" not in cols:
        return
    updates: list[str] = []
    values: list[Any] = []
    if "status" in cols:
        updates.append("status = %s")
        values.append("EXECUTED" if executed else ("ACKED" if ack else "PENDING"))
    if ack and "claimed_at" in cols:
        updates.append("claimed_at = %s")
        values.append(_utc_iso_now())
    if ack and "claimed_at_ms" in cols:
        updates.append("claimed_at_ms = %s")
        values.append(_ms_now())
    if executed and "done_at" in cols:
        updates.append("done_at = %s")
        values.append(_utc_iso_now())
    if executed and "done_at_ms" in cols:
        updates.append("done_at_ms = %s")
        values.append(_ms_now())
    if "ack_meta" in cols:
        updates.append("ack_meta = %s")
        values.append(json.dumps({"source": "gateway", "note": note}, ensure_ascii=True))
    if "last_error" in cols and note:
        updates.append("last_error = %s")
        values.append(str(note))
    if not updates:
        return
    values.append(int(command_id))
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE {schema}.commands SET {', '.join(updates)} WHERE id = %s", values)


def _queue_lifecycle_mark(queue_id: int, *, executed: bool) -> None:
    if queue_id <= 0:
        return
    _ensure_gateway_phase4_tables(AUDIT_DSN)
    status = "executed" if executed else "acked"
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE gateway.command_queue
                SET status = %s,
                    acked_at = COALESCE(acked_at, now()),
                    executed_at = CASE WHEN %s THEN now() ELSE executed_at END
                WHERE id = %s
                """,
                (status, bool(executed), int(queue_id)),
            )


def _manual_trade_insert(schema: str, payload: Dict[str, Any], trace_id: str, *, simulated: bool) -> int:
    if not _table_exists(schema, "trades"):
        return 0
    cols = _table_columns(schema, "trades")
    now_iso = _utc_iso_now()
    now_ms = _ms_now()
    symbol = str(payload.get("symbol") or "").strip().upper()
    direction = str(payload.get("direction") or payload.get("side") or "LONG").strip().upper()
    side = "BUY" if direction in {"LONG", "BUY"} else "SELL"
    market = str(payload.get("market") or "futures").strip().lower()
    amount_usd = _as_float(payload.get("amount_usd"), 0.0)
    entry_price = _as_float(payload.get("entry_price"), 0.0)
    qty = _as_float(payload.get("quantity"), 0.0)
    if qty <= 0:
        qty = amount_usd
    fields: list[str] = []
    values: list[Any] = []

    def _add(col: str, val: Any) -> None:
        if col in cols:
            fields.append(col)
            values.append(val)

    _add("symbol", symbol)
    _add("signal", side)
    _add("side", direction)
    _add("direction", direction)
    _add("status", "OPEN")
    _add("market_type", market)
    _add("strategy_tag", "MANUAL_EXECUTE")
    _add("timeframe", "manual")
    _add("entry_price", entry_price)
    _add("price", entry_price)
    _add("quantity", qty)
    _add("qty", qty)
    _add("size", qty)
    _add("notional", amount_usd)
    _add("position_notional", amount_usd)
    _add("timestamp", now_iso)
    _add("timestamp_ms", now_ms)
    _add("created_at", now_iso)
    _add("created_at_ms", now_ms)
    _add("confidence", 1.0)
    _add("source", "gateway_manual_execute")
    _add("trace_id", trace_id)
    _add(
        "explain",
        "manual execute via unified dashboard (simulated)" if simulated else "manual execute via unified dashboard",
    )
    if "meta" in cols:
        _add("meta", json.dumps(payload, ensure_ascii=True))
    if "payload_json" in cols:
        _add("payload_json", json.dumps(payload, ensure_ascii=True))
    if not fields:
        return 0
    placeholders = ",".join(["%s"] * len(fields))
    returning = " RETURNING id" if "id" in cols else ""
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {schema}.trades ({', '.join(fields)}) VALUES ({placeholders}){returning}",
                values,
            )
            if "id" in cols:
                row = cur.fetchone() or {}
                return int(row.get("id") or 0)
    return 0


def _snapshot_cache_insert(schema: str, payload: Dict[str, Any]) -> int:
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.snapshots_cache (
                    id BIGSERIAL PRIMARY KEY,
                    ts_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
                    trace_id TEXT,
                    symbol TEXT,
                    market TEXT,
                    interval TEXT,
                    at_utc TIMESTAMPTZ,
                    request_json JSONB,
                    result_json JSONB
                )
                """
            )
            cur.execute(
                f"""
                INSERT INTO {schema}.snapshots_cache
                (trace_id, symbol, market, interval, at_utc, request_json, result_json)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                RETURNING id
                """,
                (
                    str(payload.get("trace_id") or ""),
                    str(payload.get("symbol") or ""),
                    str(payload.get("market") or ""),
                    str(payload.get("interval") or ""),
                    str(payload.get("at_utc") or None),
                    json.dumps(payload.get("request") or {}, ensure_ascii=True),
                    json.dumps(payload.get("result") or {}, ensure_ascii=True),
                ),
            )
            row = cur.fetchone() or {}
            return int(row.get("id") or 0)


def _rsi_value(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses += -diff
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = max(diff, 0.0)
        loss = max(-diff, 0.0)
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
    if avg_loss <= 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _atr_value(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    tr: list[float] = []
    for i in range(1, len(closes)):
        tr.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )
    if len(tr) < period:
        return None
    atr = sum(tr[:period]) / period
    for x in tr[period:]:
        atr = ((atr * (period - 1)) + x) / period
    return atr


def _adx_value(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    tr: list[float] = []
    pdm: list[float] = []
    mdm: list[float] = []
    for i in range(1, len(closes)):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        pdm.append(up if (up > down and up > 0.0) else 0.0)
        mdm.append(down if (down > up and down > 0.0) else 0.0)
        tr.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )
    if len(tr) < period:
        return None
    tr_s = sum(tr[:period])
    pdm_s = sum(pdm[:period])
    mdm_s = sum(mdm[:period])
    if tr_s <= 0:
        return None
    pdi = 100.0 * (pdm_s / tr_s)
    mdi = 100.0 * (mdm_s / tr_s)
    dx_values: list[float] = []
    denom = pdi + mdi
    dx_values.append((100.0 * abs(pdi - mdi) / denom) if denom > 0 else 0.0)
    for i in range(period, len(tr)):
        tr_s = tr_s - (tr_s / period) + tr[i]
        pdm_s = pdm_s - (pdm_s / period) + pdm[i]
        mdm_s = mdm_s - (mdm_s / period) + mdm[i]
        if tr_s <= 0:
            continue
        pdi = 100.0 * (pdm_s / tr_s)
        mdi = 100.0 * (mdm_s / tr_s)
        denom = pdi + mdi
        dx_values.append((100.0 * abs(pdi - mdi) / denom) if denom > 0 else 0.0)
    if not dx_values:
        return None
    adx = dx_values[0]
    for dx in dx_values[1:]:
        adx = ((adx * (period - 1)) + dx) / period
    return adx


async def _fetch_binance_klines(
    *,
    symbol: str,
    market: str,
    interval: str,
    at_ms: int | None,
    limit: int = 250,
) -> list[dict[str, Any]]:
    mkt = str(market or "futures").strip().lower()
    if mkt not in {"futures", "spot"}:
        raise HTTPException(status_code=400, detail="invalid_market")
    url = (
        "https://fapi.binance.com/fapi/v1/klines"
        if mkt == "futures"
        else "https://api.binance.com/api/v3/klines"
    )
    params: Dict[str, Any] = {
        "symbol": str(symbol or "").strip().upper(),
        "interval": str(interval or "5m").strip(),
        "limit": max(50, min(int(limit or 250), 1000)),
    }
    if at_ms and int(at_ms) > 0:
        params["endTime"] = int(at_ms)
    resp = await _request("GET", url, params=params)
    if resp.status_code >= 400:
        _raise_upstream_http_error(resp, url)
    try:
        arr = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail={"error": "snapshot_upstream_non_json", "detail": repr(e)})
    if not isinstance(arr, list):
        return []
    rows: list[dict[str, Any]] = []
    for row in arr:
        if not isinstance(row, list) or len(row) < 7:
            continue
        rows.append(
            {
                "open_time_ms": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "close_time_ms": int(row[6]),
            }
        )
    return rows


def _nearest_candle(candles: list[dict[str, Any]], at_ms: int | None) -> dict[str, Any] | None:
    if not candles:
        return None
    if at_ms is None:
        return candles[-1]
    eligible = [c for c in candles if int(c.get("open_time_ms") or 0) <= int(at_ms)]
    if eligible:
        return eligible[-1]
    return candles[-1]


def _regime_label_from_indicators(rsi: float | None, adx: float | None) -> str:
    rv = float(rsi) if rsi is not None else 50.0
    av = float(adx) if adx is not None else 0.0
    if av >= 25.0 and rv >= 55.0:
        return "TREND_UP"
    if av >= 25.0 and rv <= 45.0:
        return "TREND_DOWN"
    if av >= 20.0:
        return "TREND_MIXED"
    return "RANGE"


def _parse_local_or_utc_ms(at_utc: str | None, at_local: str | None) -> int | None:
    parsed = _parse_ts_ms(at_utc)
    if parsed is not None:
        return parsed
    txt = str(at_local or "").strip()
    if not txt:
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %I:%M %p", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            naive = dt.datetime.strptime(txt, fmt)
            aware = naive.replace(tzinfo=dt.timezone.utc)
            return int(aware.timestamp() * 1000)
        except Exception:
            continue
    return _parse_ts_ms(txt)


# ---------------------------
# Manual Execution
# ---------------------------

@app.post("/api/manual/execute")
async def api_manual_execute(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")

    role = _validate_role(str(body.get("role") or "paper").strip().lower())
    if role == "pump":
        raise HTTPException(status_code=400, detail="pump role is signal-only; manual execution is disabled")

    symbol = str(body.get("symbol") or "").strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")
    amount_usd = _as_float(body.get("amount_usd"), 0.0)
    if amount_usd <= 0:
        raise HTTPException(status_code=400, detail="amount_usd must be > 0")

    market = str(body.get("market") or "futures").strip().lower()
    if market not in {"futures", "spot"}:
        raise HTTPException(status_code=400, detail="market must be futures|spot")
    direction = str(body.get("direction") or "LONG").strip().upper()
    if direction not in {"LONG", "SHORT", "BUY", "SELL"}:
        raise HTTPException(status_code=400, detail="direction must be LONG|SHORT|BUY|SELL")
    tif = str(body.get("time_in_force") or "MARKET").strip().upper() or "MARKET"

    trace_id = (
        str(body.get("trace_id") or "").strip()
        or _trace_id_from_request(request)
    )

    if role == "live":
        _enforce_live_write_confirmation(role="live", action="MANUAL_EXECUTE", body=body, request=request)
        # Live opening path obeys kill-switch/caps/execution-enabled policy.
        _enforce_live_opening_policy(
            "OPEN_TRADE",
            {
                "symbol": symbol,
                "side": direction,
                "notional": amount_usd,
                "leverage": _as_float(body.get("leverage"), 0.0),
            },
        )
        secret = _load_integration_secret("binance")
        api_key = str(secret.get("api_key") or "").strip()
        api_secret = str(secret.get("api_secret") or "").strip()
        if not api_key or not api_secret:
            raise HTTPException(
                status_code=412,
                detail={
                    "error": "live_binance_keys_required",
                    "message": "Live manual execution requires configured Binance API keys.",
                },
            )

    params = {
        "symbol": symbol,
        "amount_usd": amount_usd,
        "market": market,
        "direction": direction,
        "time_in_force": tif,
        "trace_id": trace_id,
        "requested_at_utc": _utc_iso_now(),
        "source": "unified_dashboard",
    }
    if "leverage" in body:
        params["leverage"] = _as_float(body.get("leverage"), 0.0)

    eval_signal = {
        "symbol": symbol,
        "side": direction,
        "strategy": "MANUAL_EXECUTE",
        "confidence": 1.0,
        "score": 1.0,
        "amount_usd": amount_usd,
        "market": market,
        "leverage": _as_float(body.get("leverage"), 0.0),
    }
    eval_out = _strategy_risk_eval(role, eval_signal, action="MANUAL_EXECUTE")
    if not bool(eval_out.get("ok")):
        decision_trace_id = _insert_decision_trace(
            role,
            eval_signal,
            eval_out,
            trace_id=trace_id,
            gate="BLOCK",
            decision="NO_TRADE",
        )
        raise HTTPException(
            status_code=409,
            detail={
                "error": "strategy_risk_veto",
                "message": "Manual execute blocked by strategy/risk policy.",
                "trace_id": trace_id,
                "decision_trace_id": decision_trace_id,
                "evaluation": jsonable_encoder(eval_out),
            },
        )

    queued = _queue_role_command(
        role=role,
        cmd="MANUAL_EXECUTE",
        params=params,
        trace_id=trace_id,
        request_payload=body,
    )
    schema = _schema_for_role(role)
    command_id = int(queued.get("command_id") or 0)
    queue_id = int(((queued.get("queue") or {}).get("id")) or 0)

    _insert_role_event(
        schema,
        "MANUAL_EXECUTE_REQUEST",
        {"trace_id": trace_id, "params": params, "command_id": command_id},
    )
    _insert_shared_event(
        role,
        "MANUAL_EXECUTE_REQUEST",
        {"trace_id": trace_id, "symbol": symbol, "market": market, "direction": direction, "amount_usd": amount_usd},
    )
    _insert_role_log(
        schema,
        "INFO",
        f"manual execute requested {symbol} {direction} {amount_usd:.2f} ({market})",
        payload={"trace_id": trace_id, "command_id": command_id},
    )

    # Paper mode is always simulated-safe and still audited end-to-end.
    simulated = role == "paper"
    trade_id = 0
    lifecycle = "queued"
    decision_trace_id = _insert_decision_trace(
        role,
        eval_signal,
        eval_out,
        trace_id=trace_id,
        gate="PASS",
        decision="MANUAL_EXECUTE",
    )
    if simulated:
        trade_id = _manual_trade_insert(schema, params, trace_id, simulated=True)
        _command_lifecycle_mark(schema, command_id, ack=True, executed=True, note="simulated_by_gateway")
        _queue_lifecycle_mark(queue_id, executed=True)
        _insert_role_event(
            schema,
            "MANUAL_EXECUTE_RESULT",
            {
                "trace_id": trace_id,
                "command_id": command_id,
                "trade_id": trade_id,
                "simulated": True,
                "result": "executed",
            },
        )
        _insert_shared_event(
            role,
            "MANUAL_EXECUTE_RESULT",
            {"trace_id": trace_id, "command_id": command_id, "trade_id": trade_id, "simulated": True, "result": "executed"},
        )
        lifecycle = "executed"
    return {
        "ok": True,
        "role": role,
        "schema": schema,
        "trace_id": trace_id,
        "command_id": command_id,
        "trade_id": int(trade_id or 0),
        "simulated": simulated,
        "exchange_skipped": simulated,
        "lifecycle": lifecycle,
        "decision_trace_id": decision_trace_id,
        "evaluation": eval_out,
        "queue": queued.get("queue") or {},
    }


# ---------------------------
# Historical Snapshot (UTC)
# ---------------------------

@app.get("/api/snapshot")
async def api_snapshot(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None, alias="to"),
    role: str = "all",
    limit: int = 300,
):
    roles = _resolve_roles(role)
    lim = max(1, min(int(limit or 300), 1000))
    from_ms = _parse_ts_ms(from_)
    to_ms = _parse_ts_ms(to)

    def _in_window(ms: int | None) -> bool:
        if ms is None:
            return True
        if from_ms is not None and ms < from_ms:
            return False
        if to_ms is not None and ms > to_ms:
            return False
        return True

    trades: list[dict] = []
    decisions: list[dict] = []
    for r in roles:
        schema = _schema_for_role(r)
        if _table_exists(schema, "trades"):
            rows = await _trades_fetch(role=r, limit=lim, status=None, symbol=None)
            for row in rows:
                rr = dict(row)
                rr["role"] = r
                ts = _parse_ts_ms(str(rr.get("closed_at_ms") or rr.get("timestamp_ms") or ""))
                if _in_window(ts):
                    trades.append(rr)
        if _table_exists(schema, "decision_traces"):
            with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT * FROM {schema}.decision_traces ORDER BY id DESC LIMIT %s", (lim,))
                    rows = [dict(x) for x in (cur.fetchall() or [])]
            for row in rows:
                ms = _parse_ts_ms(str(row.get("created_at_ms") or ""))
                if _in_window(ms):
                    row["role"] = r
                    row["trace"] = _safe_json_loads(row.get("trace"), {})
                    decisions.append(row)

    events: list[dict] = []
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {EVENTS_TABLE} ORDER BY id DESC LIMIT %s", (lim,))
            rows = [dict(x) for x in (cur.fetchall() or [])]
    for row in rows:
        data = row.get("data")
        if isinstance(data, str):
            row["data"] = _safe_json_loads(data, {})
        if role != "all" and str(row.get("bot_role") or "").lower() != role.lower():
            continue
        ts_txt = str(row.get("created_at") or "")
        ms = None
        try:
            ms = int(dt.datetime.fromisoformat(ts_txt.replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            ms = None
        if _in_window(ms):
            events.append(row)

    # Replay trace view from gateway audit entries.
    replay: Dict[str, Dict[str, Any]] = {}
    try:
        audits = await asyncio.to_thread(fetch_audit_events, AUDIT_DSN, lim)
    except Exception:
        audits = []
    for a in audits:
        t = str(a.get("trace_id") or "").strip()
        if not t:
            continue
        rec = replay.setdefault(t, {"trace_id": t, "audit": []})
        rec["audit"].append(a)
    replay_items = list(replay.values())[:100]

    return {
        "ok": True,
        "role": role,
        "from": from_,
        "to": to,
        "trades": trades[:lim],
        "events": events[:lim],
        "decisions": decisions[:lim],
        "replay_traces": replay_items,
    }


@app.post("/api/snapshot")
async def api_snapshot_at_utc(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")

    role = _validate_role(str(body.get("role") or "paper").strip().lower())
    schema = _schema_for_role(role)
    symbol = str(body.get("symbol") or "").strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")
    market = str(body.get("market") or "futures").strip().lower()
    if market not in {"futures", "spot"}:
        raise HTTPException(status_code=400, detail="market must be futures|spot")
    interval = str(body.get("interval") or "5m").strip().lower()
    if interval not in {"1m", "5m", "15m", "1h", "4h", "1d"}:
        raise HTTPException(status_code=400, detail="interval must be one of 1m|5m|15m|1h|4h|1d")

    at_local = str(body.get("at_local") or "").strip()
    at_utc_raw = str(body.get("at_utc") or "").strip()
    at_ms = _parse_local_or_utc_ms(at_utc_raw, at_local)
    if at_ms is None:
        raise HTTPException(status_code=400, detail="at_utc (or at_local) is required")
    at_utc = _ms_to_iso(int(at_ms))
    trace_id = str(body.get("trace_id") or "").strip() or _trace_id_from_request(request)

    req_payload = {
        "trace_id": trace_id,
        "role": role,
        "symbol": symbol,
        "market": market,
        "interval": interval,
        "at_local": at_local,
        "at_utc": at_utc,
    }
    _insert_role_event(schema, "SNAPSHOT_REQUEST", req_payload)
    _insert_shared_event(role, "SNAPSHOT_REQUEST", req_payload)

    candles = await _fetch_binance_klines(symbol=symbol, market=market, interval=interval, at_ms=int(at_ms), limit=260)
    if not candles:
        raise HTTPException(status_code=502, detail={"error": "snapshot_market_data_unavailable"})
    candle = _nearest_candle(candles, int(at_ms))
    if not candle:
        raise HTTPException(status_code=502, detail={"error": "snapshot_candle_missing"})

    closes = [float(c.get("close") or 0.0) for c in candles]
    highs = [float(c.get("high") or 0.0) for c in candles]
    lows = [float(c.get("low") or 0.0) for c in candles]
    rsi = _rsi_value(closes, period=14)
    atr = _atr_value(highs, lows, closes, period=14)
    adx = _adx_value(highs, lows, closes, period=14)
    c_close = float(candle.get("close") or 0.0)
    atr_pct = ((float(atr) / c_close) * 100.0) if (atr is not None and c_close > 0) else None
    regime_label = _regime_label_from_indicators(rsi, adx)

    pump_score = None
    pump_features: Dict[str, Any] = {}
    pump_candidate: Dict[str, Any] = {}
    pump_schema = _schema_for_role("pump")
    if _table_exists(pump_schema, "pump_candidates"):
        with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cols = _table_columns(pump_schema, "pump_candidates")
                time_col = "created_at_ms" if "created_at_ms" in cols else ("timestamp_ms" if "timestamp_ms" in cols else None)
                where = ["UPPER(COALESCE(symbol,'')) = %s"]
                params: list[Any] = [symbol]
                if time_col:
                    where.append(f"{time_col} <= %s")
                    params.append(int(at_ms))
                q = f"SELECT * FROM {pump_schema}.pump_candidates WHERE " + " AND ".join(where) + " ORDER BY id DESC LIMIT 1"
                cur.execute(q, params)
                row = dict(cur.fetchone() or {})
                if row:
                    raw_payload = row.get("payload_json") if "payload_json" in row else row.get("payload")
                    parsed_payload = _safe_json_loads(raw_payload, {})
                    pump_features = parsed_payload if isinstance(parsed_payload, dict) else {}
                    pump_score = row.get("pump_score")
                    if pump_score is None:
                        pump_score = pump_features.get("pump_score")
                    pump_candidate = {
                        "id": row.get("id"),
                        "status": row.get("status"),
                        "note": row.get("note"),
                    }

    result = {
        "ok": True,
        "role": role,
        "schema": schema,
        "trace_id": trace_id,
        "symbol": symbol,
        "market": market,
        "interval": interval,
        "at_local": at_local,
        "at_utc": at_utc,
        "candle": {
            "open_time_utc": _ms_to_iso(int(candle.get("open_time_ms") or 0)),
            "close_time_utc": _ms_to_iso(int(candle.get("close_time_ms") or 0)),
            "open": float(candle.get("open") or 0.0),
            "high": float(candle.get("high") or 0.0),
            "low": float(candle.get("low") or 0.0),
            "close": float(candle.get("close") or 0.0),
            "volume": float(candle.get("volume") or 0.0),
        },
        "indicators": {
            "rsi": round(float(rsi), 6) if rsi is not None else None,
            "adx": round(float(adx), 6) if adx is not None else None,
            "atr": round(float(atr), 8) if atr is not None else None,
            "atr_pct": round(float(atr_pct), 6) if atr_pct is not None else None,
        },
        "regime_label": regime_label,
        "pump": {
            "score": _as_float(pump_score, 0.0) if pump_score is not None else None,
            "candidate": pump_candidate,
            "features": pump_features,
        },
        "raw_indicators": {
            "sample_size": len(candles),
            "closes_tail": closes[-5:],
            "highs_tail": highs[-5:],
            "lows_tail": lows[-5:],
        },
    }

    _insert_role_event(
        schema,
        "SNAPSHOT_RESULT",
        {
            "trace_id": trace_id,
            "symbol": symbol,
            "market": market,
            "interval": interval,
            "at_utc": at_utc,
            "regime_label": regime_label,
            "pump_score": result["pump"]["score"],
        },
    )
    _insert_shared_event(
        role,
        "SNAPSHOT_RESULT",
        {
            "trace_id": trace_id,
            "symbol": symbol,
            "market": market,
            "interval": interval,
            "at_utc": at_utc,
            "regime_label": regime_label,
            "pump_score": result["pump"]["score"],
        },
    )
    _insert_role_log(
        schema,
        "INFO",
        f"snapshot {symbol} {interval} @ {at_utc}",
        payload={"trace_id": trace_id, "regime_label": regime_label},
    )
    cache_id = 0
    try:
        cache_id = _snapshot_cache_insert(
            schema,
            {
                "trace_id": trace_id,
                "symbol": symbol,
                "market": market,
                "interval": interval,
                "at_utc": at_utc,
                "request": req_payload,
                "result": result,
            },
        )
    except Exception:
        cache_id = 0
    result["cache_id"] = int(cache_id or 0)
    return result


def _insert_shared_event(bot_role: str, event_type: str, data: Dict[str, Any]) -> int:
    _ensure_events_table(AUDIT_DSN)
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {EVENTS_TABLE} (bot_role, event_type, data)
                VALUES (%s, %s, %s::jsonb)
                RETURNING id
                """,
                (str(bot_role), str(event_type), json.dumps(data or {}, ensure_ascii=True)),
            )
            row = cur.fetchone() or {}
            return int(row.get("id") or 0)


def _insert_signal_inbox_row(schema: str, payload: Dict[str, Any]) -> int:
    if not _table_exists(schema, "signal_inbox"):
        raise HTTPException(status_code=503, detail=f"{schema}.signal_inbox_missing")
    cols = _table_columns(schema, "signal_inbox")
    fields: list[str] = []
    values: list[Any] = []

    def _add(name: str, value: Any) -> None:
        if name in cols:
            fields.append(name)
            values.append(value)

    now_iso = _utc_iso_now()
    now_ms = _ms_now()
    _add("received_at", now_iso)
    _add("received_at_ms", now_ms)
    _add("source", str(payload.get("source") or "pump_promote"))
    _add("status", str(payload.get("status") or "PENDING_APPROVAL"))
    _add("symbol", str(payload.get("symbol") or "").upper())
    _add("timeframe", str(payload.get("timeframe") or "5m"))
    _add("strategy", str(payload.get("strategy") or "PUMP_HUNTER_PROMOTE"))
    _add("side", _normalize_side(payload.get("side")))
    _add("confidence", _as_float(payload.get("confidence"), 0.5))
    _add("score", _as_float(payload.get("score"), _as_float(payload.get("confidence"), 0.5)))
    _add("note", str(payload.get("note") or "Promoted from pump candidate"))
    if "payload" in cols:
        fields.append("payload")
        values.append(json.dumps(payload.get("payload") or {}, ensure_ascii=True))

    if not fields:
        raise HTTPException(status_code=503, detail=f"{schema}.signal_inbox_columns_missing")

    placeholders = ",".join(["%s"] * len(fields))
    returning = " RETURNING id" if "id" in cols else ""
    q = f"INSERT INTO {schema}.signal_inbox ({', '.join(fields)}) VALUES ({placeholders}){returning}"
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(q, values)
            if "id" in cols:
                row = cur.fetchone() or {}
                return int(row.get("id") or 0)
    return 0


def _fetch_pump_candidate_row(candidate_id: int) -> Dict[str, Any] | None:
    schema = _schema_for_role("pump")
    if _table_exists(schema, "pump_candidates"):
        with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM {schema}.pump_candidates WHERE id = %s LIMIT 1", (int(candidate_id),))
                row = dict(cur.fetchone() or {})
                if row:
                    raw_payload = row.get("payload")
                    if raw_payload in (None, ""):
                        raw_payload = row.get("payload_json")
                    p = _safe_json_loads(raw_payload, {})
                    row["payload"] = p if isinstance(p, dict) else {}
                    return row
    # Fallback: signal inbox row can also be promoted.
    return _fetch_signal_one(schema, int(candidate_id))


def _set_pump_candidate_status(candidate_id: int, status: str, note: str | None = None) -> None:
    schema = _schema_for_role("pump")
    if not _table_exists(schema, "pump_candidates"):
        return
    cols = _table_columns(schema, "pump_candidates")
    if "status" not in cols:
        return
    fields = ["status = %s"]
    vals: list[Any] = [str(status or "").upper()]
    if note is not None and "note" in cols:
        fields.append("note = %s")
        vals.append(str(note))
    if "updated_at" in cols:
        fields.append("updated_at = %s")
        vals.append(_utc_iso_now())
    vals.append(int(candidate_id))
    with psycopg.connect(AUDIT_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE {schema}.pump_candidates SET {', '.join(fields)} WHERE id = %s", vals)


def _list_pump_candidates(limit: int = 50, status: str | None = "PENDING") -> list[dict]:
    schema = _schema_for_role("pump")
    if not _table_exists(schema, "pump_candidates"):
        return []
    cols = _table_columns(schema, "pump_candidates")
    where: list[str] = []
    params: list[Any] = []
    st = str(status or "").strip().upper()
    if st and st != "ALL" and "status" in cols:
        where.append("UPPER(COALESCE(status,'')) = %s")
        params.append(st)
    order_col = "created_at_ms" if "created_at_ms" in cols else ("id" if "id" in cols else None)
    q = f"SELECT * FROM {schema}.pump_candidates"
    if where:
        q += " WHERE " + " AND ".join(where)
    if order_col:
        q += f" ORDER BY {order_col} DESC"
    q += " LIMIT %s"
    params.append(max(1, min(int(limit or 50), 1000)))
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(q, params)
            rows = [dict(r) for r in (cur.fetchall() or [])]
    for row in rows:
        payload = _safe_json_loads(row.get("payload_json"), {})
        row["payload"] = payload if isinstance(payload, dict) else {}
    return rows


def _pump_status_snapshot() -> Dict[str, Any]:
    schema = _schema_for_role("pump")
    state = {}
    if _table_exists(schema, "pump_hunter_state"):
        with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM {schema}.pump_hunter_state ORDER BY id DESC LIMIT 1")
                state = dict(cur.fetchone() or {})

    counts = {"WATCH": 0, "PENDING": 0, "APPROVED": 0, "REJECTED": 0, "EXECUTED": 0, "PROMOTED": 0}
    if _table_exists(schema, "pump_candidates"):
        with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT status, COUNT(*) AS c FROM {schema}.pump_candidates GROUP BY status")
                for r in cur.fetchall() or []:
                    key = str(r.get("status") or "").upper()
                    counts[key] = int(r.get("c") or 0)

    return {"status": "ok", "state": state, "counts": counts}


def _insert_pump_label_row(symbol: str, timestamp_ms: int, label: str, note: str = "") -> int:
    schema = _schema_for_role("pump")
    if not _table_exists(schema, "pump_labels"):
        raise HTTPException(status_code=503, detail=f"{schema}.pump_labels_missing")
    cols = _table_columns(schema, "pump_labels")
    fields: list[str] = []
    vals: list[Any] = []
    if "created_at_ms" in cols:
        fields.append("created_at_ms")
        vals.append(_ms_now())
    if "symbol" in cols:
        fields.append("symbol")
        vals.append(str(symbol).upper().strip())
    if "timestamp_ms" in cols:
        fields.append("timestamp_ms")
        vals.append(int(timestamp_ms))
    if "label" in cols:
        fields.append("label")
        vals.append(str(label or "PUMP").strip() or "PUMP")
    if "note" in cols:
        fields.append("note")
        vals.append(str(note or ""))
    if not fields:
        raise HTTPException(status_code=503, detail=f"{schema}.pump_labels_columns_missing")
    placeholders = ",".join(["%s"] * len(fields))
    returning = " RETURNING id" if "id" in cols else ""
    with psycopg.connect(AUDIT_DSN, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {schema}.pump_labels ({', '.join(fields)}) VALUES ({placeholders}){returning}",
                vals,
            )
            if "id" in cols:
                row = cur.fetchone() or {}
                return int(row.get("id") or 0)
    return 0


def _promote_pump_candidate_to_role(
    *,
    candidate_id: int,
    target_role: str,
    side: str,
    note: str,
    actor: str,
    trace_id: str,
) -> Dict[str, Any]:
    role = _validate_role(target_role)
    if role not in {"paper", "live"}:
        raise HTTPException(status_code=400, detail="target_role must be paper|live")
    candidate = _fetch_pump_candidate_row(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="pump_candidate_not_found")

    payload = candidate.get("payload") if isinstance(candidate.get("payload"), dict) else {}
    symbol = str(candidate.get("symbol") or payload.get("symbol") or "").strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="candidate_missing_symbol")
    picked_side = _normalize_side(side or candidate.get("ai_vote") or candidate.get("side") or payload.get("side"))
    if picked_side not in {"LONG", "SHORT"}:
        raise HTTPException(status_code=400, detail="candidate_missing_side")

    signal_payload = {
        "source": "pump_promote",
        "status": "PENDING_APPROVAL",
        "symbol": symbol,
        "timeframe": str(candidate.get("interval") or payload.get("interval") or payload.get("timeframe") or "5m"),
        "strategy": "PUMP_HUNTER_PROMOTE",
        "side": picked_side,
        "confidence": _as_float(candidate.get("ai_confidence") or payload.get("ai_confidence"), 0.5),
        "score": _as_float(candidate.get("pump_score") or payload.get("pump_score"), 0.5),
        "note": note or f"Promoted from pump candidate #{int(candidate_id)}",
        "payload": {
            "trace_id": trace_id,
            "promoted_by": actor,
            "promoted_at": _utc_iso_now(),
            "promoted_from": "mina_pump.pump_candidates",
            "candidate_id": int(candidate_id),
            "target_role": role,
            "candidate": {
                "symbol": symbol,
                "ai_vote": candidate.get("ai_vote") or payload.get("ai_vote"),
                "ai_confidence": candidate.get("ai_confidence") or payload.get("ai_confidence"),
                "pump_score": candidate.get("pump_score") or payload.get("pump_score"),
                "watch": candidate.get("watch") if "watch" in candidate else payload.get("watch"),
            },
        },
    }
    signal_id = _insert_signal_inbox_row(_schema_for_role(role), signal_payload)
    _set_pump_candidate_status(candidate_id, "PROMOTED", note=note or "Promoted by Unified Dashboard")
    event_id = _insert_shared_event(
        "pump",
        "PUMP_SIGNAL_PROMOTED",
        {
            "trace_id": trace_id,
            "candidate_id": int(candidate_id),
            "target_role": role,
            "signal_id": signal_id,
            "symbol": symbol,
            "side": picked_side,
            "actor": actor,
        },
    )
    return {
        "ok": True,
        "trace_id": trace_id,
        "event_id": event_id,
        "candidate_id": int(candidate_id),
        "target_role": role,
        "signal_id": int(signal_id or 0),
        "symbol": symbol,
        "side": picked_side,
    }


@app.post("/api/pump/candidates/promote")
async def api_pump_candidate_promote(request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Body must be an object")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    candidate_id = _as_int(body.get("id") or body.get("candidate_id"), 0)
    if candidate_id <= 0:
        raise HTTPException(status_code=400, detail="candidate id is required")
    target_role = str(body.get("target_role") or "paper").strip().lower()
    side = str(body.get("side") or "").strip().upper()
    note = str(body.get("note") or "").strip()
    trace_id = _trace_id_from_request(request)
    actor = _actor_from_request(request)

    if target_role == "live":
        _enforce_live_write_confirmation(role="live", action="PUMP_PROMOTE_TO_LIVE", body=body, request=request)

    out = _promote_pump_candidate_to_role(
        candidate_id=int(candidate_id),
        target_role=target_role,
        side=side,
        note=note,
        actor=actor,
        trace_id=trace_id,
    )
    await _audit_write(
        request=request,
        action="PUMP_PROMOTE_SIGNAL",
        role="pump",
        target_id=str(candidate_id),
        trace_id=trace_id,
        request_json={"candidate_id": candidate_id, "target_role": target_role, "side": side, "note": note},
        response_json={"ok": True, "signal_id": out.get("signal_id"), "target_role": out.get("target_role")},
        ok=True,
    )
    return out


@app.get("/api/pump/candidates/promote")
async def api_pump_candidate_promote_docs():
    return {
        "ok": True,
        "method": "POST",
        "route": "/api/pump/candidates/promote",
        "detail": "Use POST with {id, target_role, side, note} to promote a pump candidate.",
    }


@app.get("/api/pump/status")
async def api_pump_status():
    snap = _pump_status_snapshot()
    return {"ok": True, **snap}


@app.get("/api/pump/candidates")
async def api_pump_candidates(limit: int = 50, status: str = "ALL"):
    rows = _list_pump_candidates(limit=limit, status=status)
    return {"ok": True, "status": "ok", "items": rows, "count": len(rows)}


@app.post("/api/pump/candidates/approve")
async def api_pump_candidate_approve(request: Request):
    return await mina_proxy_post("pump", "pump/candidates/approve", request)


@app.post("/api/pump/candidates/reject")
async def api_pump_candidate_reject(request: Request):
    return await mina_proxy_post("pump", "pump/candidates/reject", request)


@app.post("/api/pump/label")
async def api_pump_label(request: Request):
    return await mina_proxy_post("pump", "pump/label", request)


@app.get("/api/pump/stats")
async def api_pump_stats():
    schema = _schema_for_role("pump")
    summary = _portfolio_summary_for_schema(schema, None, None)
    return {
        "ok": True,
        "status": "ok",
        "schema": schema,
        "trades": int(summary.get("trades") or 0),
        "wins": int(summary.get("wins") or 0),
        "losses": int(summary.get("losses") or 0),
        "realized_pnl": float(summary.get("realized_pnl") or 0.0),
        "pump": _pump_status_snapshot().get("counts") or {},
    }


@app.get("/api/pump/trades")
async def api_pump_trades(limit: int = 50, status: str | None = None):
    rows = await _trades_fetch(role="pump", limit=limit, status=status)
    return {"ok": True, "status": "ok", "items": rows, "count": len(rows)}


@app.get("/api/mina/{role}/{path:path}")
async def mina_proxy(role: Role, path: str, request: Request):
    """
    Legacy Mina route bridge.

    Dashboards were removed from runtime; key routes are mapped to DB-backed
    unified endpoints. Unknown routes return HTTP 410 with migration guidance.
    Example:
      /api/mina/paper/api/signals?limit=10  ->  /api/unified/paper/signals
    """
    _validate_role(role)
    schema = _schema_for_role(role)
    raw_path = str(path or "").strip().strip("/")
    path_l = raw_path.lower()
    if path_l.startswith("api/"):
        path_l = path_l[4:]
    params = dict(request.query_params)

    # Explicit mappings from legacy Mina routes to DB-backed unified read models.
    if path_l in ("system_health", "health"):
        return mina_pg.build_system_health(schema, role)
    if path_l == "snapshot":
        return mina_pg.snapshot(role, signal_limit=int(params.get("limit") or 10), position_limit=int(params.get("limit_positions") or 200))
    if path_l == "stats":
        return mina_pg.get_stats(schema)
    if path_l == "db_ready":
        return {"status": "ok", "backend": "postgres", "pg_schema": schema}
    if path_l == "roles":
        return {"roles": ["paper", "live", "pump"]}

    if path_l == "signals":
        limit = int(params.get("limit") or 50)
        status = params.get("status")
        rows = mina_pg.list_signals(
            schema,
            status=str(status) if status else None,
            source=str(params.get("source") or "").strip() or None,
            symbol=str(params.get("symbol") or "").strip() or None,
            timeframe=str(params.get("timeframe") or "").strip() or None,
            strategy=str(params.get("strategy") or "").strip() or None,
            from_ms=_parse_ts_ms(str(params.get("from_ts") or params.get("date_from") or "")),
            to_ms=_parse_ts_ms(str(params.get("to_ts") or params.get("date_to") or "")),
            limit=limit,
        )
        # Keep legacy dashboard response shape (plain array).
        return rows
    if role == "pump" and path_l == "pump/status":
        return _pump_status_snapshot()
    if role == "pump" and path_l == "pump/candidates":
        limit = int(params.get("limit") or 50)
        status = str(params.get("status") or "PENDING")
        rows = _list_pump_candidates(limit=limit, status=status)
        return {"status": "ok", "items": rows}
    if role == "pump" and path_l == "pump/stats":
        summary = _portfolio_summary_for_schema(schema, None, None)
        return {
            "status": "ok",
            "schema": schema,
            "trades": int(summary.get("trades") or 0),
            "wins": int(summary.get("wins") or 0),
            "losses": int(summary.get("losses") or 0),
            "realized_pnl": float(summary.get("realized_pnl") or 0.0),
            "pump": _pump_status_snapshot().get("counts") or {},
        }
    if role == "pump" and path_l == "trades":
        rows = await _trades_fetch(role="pump", limit=int(params.get("limit") or 50), status=params.get("status"))
        return {"status": "ok", "items": rows}
    if path_l.startswith("signals/") and path_l.endswith("/decision"):
        try:
            sid = int(path_l.split("/", 2)[1])
        except Exception:
            raise HTTPException(status_code=400, detail="invalid_signal_id")
        return await unified_signal_decision(role=role, signal_id=sid, request=request)
    if path_l.startswith("signals/"):
        try:
            sid = int(path_l.split("/", 1)[1])
        except Exception:
            raise HTTPException(status_code=400, detail="invalid_signal_id")
        row = _fetch_signal_one(schema, sid)
        if not row:
            raise HTTPException(status_code=404, detail="signal_not_found")
        return row
    if path_l == "positions":
        return mina_pg.list_open_positions(schema, limit=int(params.get("limit") or 200))
    if path_l == "logs":
        return mina_pg.list_logs(schema, limit=int(params.get("limit") or 200))
    if path_l == "settings":
        return mina_pg.fetch_settings(schema)
    if path_l in ("commands", "commands/history"):
        out = await api_unified_commands_history(role=role, limit=int(params.get("limit") or 50))
        if path_l == "commands":
            return out.get("items") or []
        return out
    if path_l == "meta/datasource":
        db_name, host = _dsn_info(AUDIT_DSN)
        return {
            "status": "ok",
            "service": f"mina_{role}_proxy",
            "backend": "postgres",
            "dsn_host": host,
            "db_name": db_name,
            "schema": schema,
            "version": "gateway-proxy",
        }

    use_endpoint = f"/api/unified/{role}/snapshot"
    if "signal" in path_l:
        use_endpoint = f"/api/unified/{role}/signals"
    elif "position" in path_l:
        use_endpoint = f"/api/unified/{role}/positions"
    elif "log" in path_l:
        use_endpoint = f"/api/unified/{role}/logs"
    elif "command" in path_l:
        use_endpoint = f"/api/unified/{role}/commands"
    elif "health" in path_l:
        use_endpoint = f"/api/unified/{role}/system_health"
    return JSONResponse(
        status_code=410,
        content={
            "status": "gone",
            "error": "legacy_dashboards_removed",
            "message": "Legacy Mina dashboard services were removed from the runtime stack.",
            "legacy_route": f"/api/mina/{role}/{raw_path}",
            "use_endpoint": use_endpoint,
        },
    )


@app.post("/api/mina/{role}/{path:path}")
async def mina_proxy_post(role: Role, path: str, request: Request):
    """
    Legacy Mina write-route bridge.

    Dashboards were removed from runtime; key writes are mapped to DB-backed
    unified routes. Unknown routes return HTTP 410 with migration guidance.
    Example:
      /api/mina/paper/api/commands/queue -> /api/unified/paper/commands
    """
    _validate_role(role)

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    schema = _schema_for_role(role)
    raw_path = str(path or "").strip().strip("/")
    path_l = raw_path.lower()
    if path_l.startswith("api/"):
        path_l = path_l[4:]
    trace_id = _trace_id_from_request(request)
    if role == "live":
        _enforce_live_write_confirmation(role="live", action=f"MINA_PROXY_POST:{path_l}", body=body, request=request)

    if role == "pump" and path_l == "pump/candidates/promote":
        cid = _as_int(body.get("id") or body.get("candidate_id"), 0)
        if cid <= 0:
            raise HTTPException(status_code=400, detail="candidate id is required")
        target_role = str(body.get("target_role") or "paper").strip().lower()
        side = str(body.get("side") or "").strip().upper()
        note = str(body.get("note") or "").strip()
        actor = _actor_from_request(request)
        if target_role == "live":
            _enforce_live_write_confirmation(role="live", action="PUMP_PROMOTE_TO_LIVE", body=body, request=request)
        return _promote_pump_candidate_to_role(
            candidate_id=cid,
            target_role=target_role,
            side=side,
            note=note,
            actor=actor,
            trace_id=trace_id,
        )

    if role == "pump" and path_l == "pump/candidates/approve":
        cid = _as_int(body.get("id") or body.get("candidate_id"), 0)
        if cid <= 0:
            raise HTTPException(status_code=400, detail="candidate id is required")
        note = str(body.get("note") or "").strip()
        rec = _fetch_pump_candidate_row(cid)
        if not rec:
            raise HTTPException(status_code=404, detail="pump_candidate_not_found")
        _set_pump_candidate_status(cid, "APPROVED", note=note)
        evt_payload = {
            "trace_id": trace_id,
            "candidate_id": cid,
            "symbol": str(rec.get("symbol") or ""),
            "status": "APPROVED",
            "actor": _actor_from_request(request),
            "note": note,
        }
        _insert_role_event(schema, "PUMP_CANDIDATE_APPROVED", evt_payload)
        _insert_shared_event("pump", "PUMP_CANDIDATE_APPROVED", evt_payload)
        await _audit_write(
            request=request,
            action="PUMP_CANDIDATE_APPROVE",
            role="pump",
            target_id=str(cid),
            trace_id=trace_id,
            request_json={"id": cid, "note": note},
            response_json={"ok": True},
            ok=True,
        )
        return {"ok": True, "status": "ok", "trace_id": trace_id, "id": cid}

    if role == "pump" and path_l == "pump/candidates/reject":
        cid = _as_int(body.get("id") or body.get("candidate_id"), 0)
        if cid <= 0:
            raise HTTPException(status_code=400, detail="candidate id is required")
        note = str(body.get("note") or "").strip()
        rec = _fetch_pump_candidate_row(cid)
        if not rec:
            raise HTTPException(status_code=404, detail="pump_candidate_not_found")
        _set_pump_candidate_status(cid, "REJECTED", note=note)
        evt_payload = {
            "trace_id": trace_id,
            "candidate_id": cid,
            "symbol": str(rec.get("symbol") or ""),
            "status": "REJECTED",
            "actor": _actor_from_request(request),
            "note": note,
        }
        _insert_role_event(schema, "PUMP_CANDIDATE_REJECTED", evt_payload)
        _insert_shared_event("pump", "PUMP_CANDIDATE_REJECTED", evt_payload)
        await _audit_write(
            request=request,
            action="PUMP_CANDIDATE_REJECT",
            role="pump",
            target_id=str(cid),
            trace_id=trace_id,
            request_json={"id": cid, "note": note},
            response_json={"ok": True},
            ok=True,
        )
        return {"ok": True, "status": "ok", "trace_id": trace_id, "id": cid}

    if role == "pump" and path_l == "pump/label":
        symbol = str(body.get("symbol") or "").strip().upper()
        ts_ms = _as_int(body.get("timestamp_ms"), 0)
        label = str(body.get("label") or "PUMP").strip() or "PUMP"
        note = str(body.get("note") or "").strip()
        if not symbol or ts_ms <= 0:
            raise HTTPException(status_code=400, detail="symbol and timestamp_ms are required")
        label_id = _insert_pump_label_row(symbol, ts_ms, label, note)
        evt_payload = {
            "trace_id": trace_id,
            "symbol": symbol,
            "timestamp_ms": ts_ms,
            "label": label,
            "note": note,
            "label_id": label_id,
        }
        _insert_role_event(schema, "PUMP_LABEL_SET", evt_payload)
        _insert_shared_event("pump", "PUMP_LABEL_SET", evt_payload)
        await _audit_write(
            request=request,
            action="PUMP_LABEL_SET",
            role="pump",
            target_id=symbol,
            trace_id=trace_id,
            request_json={"symbol": symbol, "timestamp_ms": ts_ms, "label": label, "note": note},
            response_json={"ok": True, "id": label_id},
            ok=True,
        )
        return {"ok": True, "status": "ok", "trace_id": trace_id, "id": int(label_id or 0)}

    if path_l in ("publish", "signals/publish"):
        signal_id = int(mina_pg.publish_signal(schema, body) or 0)
        return {"status": "published", "id": signal_id, "_dashboard_inbox_id": signal_id}

    # DB-native write paths (dashboard-independent).
    if path_l in ("commands/queue", "command"):
        cmd = str(body.get("cmd") or "").strip().upper()
        params = body.get("params") if isinstance(body.get("params"), dict) else {}
        if not cmd:
            raise HTTPException(status_code=400, detail="cmd is required")
        queued = _queue_role_command(
            role=role,
            cmd=cmd,
            params=params,
            trace_id=trace_id,
            request_payload={"cmd": cmd, "params": params},
        )
        return {"ok": True, "status": "ok", "role": role, "trace_id": trace_id, **queued}

    if path_l == "signals/approve":
        sid = int(body.get("id") or 0)
        if sid <= 0:
            raise HTTPException(status_code=400, detail="id is required")
        note = str(body.get("note") or "")
        payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
        return _approve_signal_from_db(role, sid, note=note, payload=payload)

    if path_l == "signals/reject":
        sid = int(body.get("id") or 0)
        if sid <= 0:
            raise HTTPException(status_code=400, detail="id is required")
        reason = str(body.get("reason") or "Rejected from Gateway")
        note = str(body.get("note") or "")
        return _reject_signal_from_db(role, sid, reason=reason, note=note)

    if path_l in ("settings", "env_secrets"):
        updated = _upsert_settings(schema, body, source=f"gateway.proxy.{path_l}")
        return {"ok": True, "status": "ok", "updated": list(updated.keys()), "count": len(updated)}

    if path_l == "control/restart_bot":
        queued = _queue_role_command(
            role=role,
            cmd="BOT_RESTART",
            params={"reason": "gateway_proxy_restart_bot"},
            trace_id=trace_id,
            request_payload={"target": "bot", "action": "restart"},
        )
        return {"ok": True, "status": "ok", "trace_id": trace_id, **queued}

    if path_l == "control/restart_monitor":
        queued = _queue_role_command(
            role=role,
            cmd="MONITOR_RESTART",
            params={"reason": "gateway_proxy_restart_monitor"},
            trace_id=trace_id,
            request_payload={"target": "monitor", "action": "restart"},
        )
        return {"ok": True, "status": "ok", "trace_id": trace_id, **queued}

    if path_l == "control/clear_kill_switch":
        queued = _queue_role_command(
            role=role,
            cmd="KILL_SWITCH_OFF",
            params={"reason": "gateway_proxy_clear_kill_switch"},
            trace_id=trace_id,
            request_payload={"target": "bot", "action": "clear_kill_switch"},
        )
        _set_setting(schema, "kill_switch", "0", source="gateway.proxy.clear_kill_switch")
        return {"ok": True, "status": "ok", "trace_id": trace_id, **queued}

    use_endpoint = f"/api/unified/{role}/commands"
    if "signal" in path_l:
        use_endpoint = f"/api/unified/{role}/signals"
    elif "publish" in path_l:
        use_endpoint = f"/api/unified/{role}/publish"
    elif "setting" in path_l:
        use_endpoint = f"/api/unified/{role}/settings"
    return JSONResponse(
        status_code=410,
        content={
            "status": "gone",
            "error": "legacy_dashboards_removed",
            "message": "Legacy Mina dashboard services were removed from the runtime stack.",
            "legacy_route": f"/api/mina/{role}/{raw_path}",
            "use_endpoint": use_endpoint,
        },
    )


# ---------------------------
# Brain passthrough proxy
# ---------------------------

_RESERVED_API_PREFIXES = (
    "unified",
    "mina",
    "pump",
    "audit",
    "audit_log",
    "ops",
    "live",
    "portfolio",
    "reports",
    "doctor",
    "api-index",
    "webhooks",
    "learn",
    "strategies",
    "risk",
    "runtime",
    "alerts",
    "integrations",
    "_debug",
    "stack",
    "overview",
    "contracts",
)

async def _proxy_to_brain(path: str, request: Request) -> Response:
    c = _client_or_raise()
    upstream = f"{BRAIN_API_URL.rstrip('/')}/api/{path.lstrip('/')}"
    method = request.method.upper()

    # Forward selected headers only (avoid hop-by-hop headers).
    fwd_headers = {}
    for h in ("accept", "content-type", "x-trace-id"):
        if h in request.headers:
            fwd_headers[h] = request.headers[h]

    body = await request.body()

    try:
        r = await c.request(
            method,
            upstream,
            params=dict(request.query_params),
            content=body if body else None,
            headers=fwd_headers,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upstream request error: {e}")

    ct = r.headers.get("content-type") or "application/octet-stream"
    return Response(content=r.content, status_code=r.status_code, headers={"content-type": ct})


@app.api_route("/api/brain/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def api_brain_proxy(path: str, request: Request):
    """Explicit brain proxy namespace."""
    return await _proxy_to_brain(path, request)


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def api_fallback_to_brain(path: str, request: Request):
    """Fallback: if an /api/* route isn't handled by the gateway, proxy it to brain_api.

    This keeps existing Brain UI pages working behind the gateway's /api baseURL.
    """
    if not path:
        raise HTTPException(status_code=404, detail="Not Found")

    for p in _RESERVED_API_PREFIXES:
        if path == p or path.startswith(p + "/"):
            raise HTTPException(status_code=404, detail="Not Found")

    return await _proxy_to_brain(path, request)


# ---------------------------
# Mina-style Ops Dashboard (server-rendered)
# ---------------------------
def _ui_template(request: Request, name: str, title: str):
    return templates.TemplateResponse(f"ui/{name}", {"request": request, "title": title})


@app.get("/ui")
async def ui_root():
    return RedirectResponse(url="/ui/ops")


@app.get("/ui/ops")
async def ui_ops(request: Request):
    return _ui_template(request, "ops.html", "Ops Live")


@app.get("/ui/portfolio")
async def ui_portfolio(request: Request):
    return _ui_template(request, "portfolio.html", "Portfolio")


@app.get("/ui/manual")
async def ui_manual(request: Request):
    return _ui_template(request, "manual.html", "Manual Ops")


@app.get("/ui/reports")
async def ui_reports(request: Request):
    return _ui_template(request, "reports.html", "Reports")


@app.get("/ui/doctor")
async def ui_doctor(request: Request):
    return _ui_template(request, "doctor.html", "Project Doctor")


@app.get("/ui/api")
async def ui_api(request: Request):
    return _ui_template(request, "api.html", "API")


@app.get("/ui/learn")
async def ui_learn(request: Request):
    return _ui_template(request, "learn.html", "Learn")


@app.get("/ui/alerts")
async def ui_alerts(request: Request):
    return _ui_template(request, "alerts.html", "Alerts")


@app.get("/ui/go_live")
async def ui_go_live(request: Request):
    return _ui_template(request, "go_live.html", "Go Live")


# ---------------------------
# Serve Unified UI (static SPA)
# ---------------------------
UI_DIST_DIR = os.getenv("UI_DIST_DIR", "/app/ui_dist")
if os.path.isdir(UI_DIST_DIR):
    app.mount("/", StaticFiles(directory=UI_DIST_DIR, html=True), name="ui")
