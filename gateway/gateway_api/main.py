from __future__ import annotations

import os
import json
import asyncio
import uuid
import time
import hmac
import hashlib
import datetime as dt

from typing import Literal, Optional, Dict, Any

import httpx
import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from gateway_api.contracts_v1 import json_schema as contracts_v1_schema

from gateway_api.audit import ensure_audit_schema_and_table, get_dsn as _audit_get_dsn, insert_audit_event, new_trace_id, fetch_audit_events, fetch_audit_event_by_id


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

AUDIT_DSN = _audit_get_dsn()
AUDIT_ENABLED = True

MINA_PAPER_URL = _env("MINA_PAPER_URL", "http://mina_dashboard_paper:8000")
MINA_LIVE_URL = _env("MINA_LIVE_URL", "http://mina_dashboard_live:8001")
MINA_PUMP_URL = _env("MINA_PUMP_URL", "http://mina_dashboard_pump:8002")
MINA_SCHEMA_PREFIX = _env("MINA_SCHEMA_PREFIX", "mina_")

ROLE_URLS: Dict[str, str] = {
    "paper": MINA_PAPER_URL,
    "live": MINA_LIVE_URL,
    "pump": MINA_PUMP_URL,
}

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

app = FastAPI(title="Trading Gateway", version="0.2.2")

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
    try:
        return await c.request(method, url, headers=headers, params=params, json=json_body)
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail={"error": "upstream_request_error", "url": url, "exception": repr(e)},
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
    # Aggregate health from brain + 3 dashboards
    out = {"gateway": "ok", "brain": None, "dashboards": {}}
    # Brain
    try:
        out["brain"] = await _fetch_json(f"{BRAIN_API_URL}/api/overview")
    except HTTPException as e:
        out["brain"] = _http_exc_detail(e)

    # Dashboards system health
    headers = {"X-API-Key": DASHBOARD_API_KEY}
    for role, base in ROLE_URLS.items():
        try:
            out["dashboards"][role] = await _fetch_json(f"{base}/api/system_health", headers=headers)
        except HTTPException as e:
            out["dashboards"][role] = {"error": e.detail}
    return out

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
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    headers = {"X-API-Key": DASHBOARD_API_KEY}
    return await _fetch_json(f"{base}/api/system_health", headers=headers)


@app.get("/api/mina/{role}/health")
async def mina_health(role: Role):
    """Health check for Mina dashboard.

    In some Mina dashboard builds, `/health` serves an HTML login page (text/html)
    instead of JSON, which breaks a JSON-only proxy. For the unified stack we
    treat `/api/system_health` as the canonical JSON health endpoint.

    This route provides a stable JSON health response for the role.
    """
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")

    headers = {"X-API-Key": DASHBOARD_API_KEY} if DASHBOARD_API_KEY else {}

    # Canonical JSON health endpoint
    try:
        return await _fetch_json(f"{base}/api/system_health", headers=headers)
    except HTTPException as e:
        # Last resort: attempt `/health` but wrap non-JSON into a safe payload.
        if getattr(e, "status_code", None) in (404, 405):
            return await _fetch_json(f"{base}/health", headers=headers)
        raise

@app.get("/api/unified/roles")
async def api_unified_roles():
    return {
        "roles": ["paper", "live", "pump"],
        "proxy_example": "/api/mina/paper/signals?limit=10",
        "api_key_header": "X-API-Key",
    }

@app.get("/api/unified/overview")
async def api_unified_overview():
    """Unified overview: Gateway + Brain + per-role dashboards + latest audit/events."""
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

    # Brain health + overview
    try:
        out["brain_api"] = await _fetch_json(f"{BRAIN_API_URL}/health")
    except HTTPException as e:
        out["brain_api"] = _http_exc_detail(e)
    try:
        out["brain"] = await _fetch_json(f"{BRAIN_API_URL}/api/overview")
    except HTTPException as e:
        out["brain"] = _http_exc_detail(e)

    headers = {"X-API-Key": DASHBOARD_API_KEY}
    for role, base in ROLE_URLS.items():
        role_out = {"stats": None, "signals_preview": None, "system_health": None}
        try:
            role_out["system_health"] = await _fetch_json(f"{base}/api/system_health", headers=headers)
        except HTTPException as e:
            role_out["system_health"] = _http_exc_detail(e)
        try:
            role_out["stats"] = await _fetch_json(f"{base}/api/stats", headers=headers)
        except HTTPException as e:
            role_out["stats"] = _http_exc_detail(e)
        try:
            role_out["signals_preview"] = await _fetch_json(f"{base}/api/signals", headers=headers, params={"limit": 5})
        except HTTPException as e:
            role_out["signals_preview"] = _http_exc_detail(e)
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


@app.post("/api/unified/autopilot/{role}")
async def api_unified_autopilot_set_role(role: Role, request: Request):
    body = await request.json()
    mode = _normalize_mode(body.get("role_mode"))
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
    """One-call snapshot for a single dashboard role."""
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    headers = {"X-API-Key": DASHBOARD_API_KEY}
    out = {"schema_version": "v1", "role": role, "system_health": None, "stats": None, "positions": None, "signals": None}
    try:
        out["system_health"] = await _fetch_json(f"{base}/api/system_health", headers=headers)
    except HTTPException as e:
        out["system_health"] = _http_exc_detail(e)
    try:
        out["stats"] = await _fetch_json(f"{base}/api/stats", headers=headers)
    except HTTPException as e:
        out["stats"] = _http_exc_detail(e)
    try:
        out["positions"] = await _fetch_json(f"{base}/api/positions", headers=headers)
    except HTTPException as e:
        out["positions"] = _http_exc_detail(e)
    try:
        out["signals"] = await _fetch_json(f"{base}/api/signals", headers=headers, params={"limit": 10})
    except HTTPException as e:
        out["signals"] = _http_exc_detail(e)
    return out



@app.get("/api/unified/{role}/system_health")
async def api_unified_role_system_health(role: Role):
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    headers = {"X-API-Key": DASHBOARD_API_KEY}
    return await _fetch_json(f"{base}/api/system_health", headers=headers)

@app.get("/api/unified/{role}/stats")
async def api_unified_role_stats(role: Role):
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    headers = {"X-API-Key": DASHBOARD_API_KEY}
    return await _fetch_json(f"{base}/api/stats", headers=headers)

@app.get("/api/unified/{role}/positions")
async def api_unified_role_positions(role: Role):
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    headers = {"X-API-Key": DASHBOARD_API_KEY}
    return await _fetch_json(f"{base}/api/positions", headers=headers)

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
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    headers = {"X-API-Key": DASHBOARD_API_KEY}
    return await _fetch_json(f"{base}/api/commands", headers=headers, params={"limit": int(limit)})

@app.get("/api/unified/{role}/signals")
async def api_unified_role_signals(role: Role, limit: int = 30, status: str | None = None):
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    headers = {"X-API-Key": DASHBOARD_API_KEY}
    params: dict[str, object] = {"limit": int(limit)}
    if status:
        params["status"] = status
    return await _fetch_json(f"{base}/api/signals", headers=headers, params=params)

@app.get("/api/unified/{role}/signals/{signal_id}")
async def api_unified_signal_detail(role: Role, signal_id: int):
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    headers = {"X-API-Key": DASHBOARD_API_KEY}
    return await _fetch_json(f"{base}/api/signals/{int(signal_id)}", headers=headers)
@app.get("/api/unified/{role}/signals/{signal_id}/decision")
async def unified_signal_decision(role: str, signal_id: int):
    """Best-effort decision precheck for a Mina signal (fetches recent signals and matches by id)."""
    trace_id = new_trace_id()

    signals = await _dashboard_get_json(role, "/api/signals", params={"limit": 200})
    sig = None
    if isinstance(signals, list):
        for s in signals:
            try:
                if int(s.get("id")) == int(signal_id):
                    sig = s
                    break
            except Exception:
                continue

    if not sig:
        raise HTTPException(status_code=404, detail=f"Signal not found: {signal_id}")

    symbol = sig.get("symbol")
    if not symbol:
        raise HTTPException(status_code=400, detail="Signal has no symbol")

    decision = await _brain_get_json("/api/decision", params={"symbol": symbol})

    audit_id = None
    if AUDIT_ENABLED:
        # Audit failures should never break the API.
        try:
            audit_id = await _audit_write(
                actor="ui",
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
        "signal": sig,
        "decision": decision,
        "trace_id": trace_id,
        "audit_id": audit_id,
    }



@app.post("/api/unified/{role}/signals/publish")
async def api_unified_signal_publish(role: Role, request: Request):
    """Publish (stage) a signal into Mina dashboard inbox for the selected role.
    Proxies to Mina dashboard /publish. Does NOT approve or execute.
    """
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")

    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {"raw": body}
    except Exception:
        body = {}

    headers: Dict[str, str] = {}
    token = request.headers.get("x-dashboard-token") or request.headers.get("X-Dashboard-Token")
    if token:
        headers["x-dashboard-token"] = token

    return await _audited_post_json(
        request=request,
        action="SIGNAL_PUBLISH",
        role=role,
        target_id=str(body.get("symbol") or body.get("pair") or ""),
        url=f"{base}/publish",
        headers=headers if headers else None,
        json_body=body,
    )


@app.get("/api/unified/{role}/logs")
async def api_unified_role_logs(role: Role, limit: int = 200):
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    headers = {"X-API-Key": DASHBOARD_API_KEY}
    return await _fetch_json(f"{base}/api/logs", headers=headers, params={"limit": int(limit)})


@app.get("/api/unified/{role}/settings")
async def api_unified_role_settings(role: Role, request: Request):
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    headers = {"X-API-Key": DASHBOARD_API_KEY}
    return await _audited_get_json(
        request=request,
        action="SETTINGS_GET",
        role=role,
        target_id=None,
        url=f"{base}/api/settings",
        headers=headers,
    )


@app.post("/api/unified/{role}/settings")
async def api_unified_role_settings_update(role: Role, request: Request):
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Body must be an object")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    headers = {"X-API-Key": DASHBOARD_API_KEY}
    return await _audited_post_json(
        request=request,
        action="SETTINGS_SET",
        role=role,
        target_id=None,
        url=f"{base}/api/settings",
        headers=headers,
        json_body=body,
    )


@app.get("/api/unified/{role}/env_secrets")
async def api_unified_role_env_secrets(role: Role, request: Request):
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    headers = {"X-API-Key": DASHBOARD_API_KEY}
    return await _audited_get_json(
        request=request,
        action="ENV_SECRETS_GET",
        role=role,
        target_id=None,
        url=f"{base}/api/env_secrets",
        headers=headers,
    )


@app.post("/api/unified/{role}/env_secrets")
async def api_unified_role_env_secrets_update(role: Role, request: Request):
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Body must be an object")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    headers = {"X-API-Key": DASHBOARD_API_KEY}
    return await _audited_post_json(
        request=request,
        action="ENV_SECRETS_SET",
        role=role,
        target_id=None,
        url=f"{base}/api/env_secrets",
        headers=headers,
        json_body=body,
    )


@app.post("/api/unified/{role}/control/restart_bot")
async def api_unified_control_restart_bot(role: Role, request: Request):
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    headers = {"X-API-Key": DASHBOARD_API_KEY}
    return await _audited_post_json(
        request=request,
        action="CONTROL_RESTART_BOT",
        role=role,
        target_id="restart_bot",
        url=f"{base}/api/control/restart_bot",
        headers=headers,
        json_body={},
    )


@app.post("/api/unified/{role}/control/restart_monitor")
async def api_unified_control_restart_monitor(role: Role, request: Request):
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    headers = {"X-API-Key": DASHBOARD_API_KEY}
    return await _audited_post_json(
        request=request,
        action="CONTROL_RESTART_MONITOR",
        role=role,
        target_id="restart_monitor",
        url=f"{base}/api/control/restart_monitor",
        headers=headers,
        json_body={},
    )


@app.post("/api/unified/{role}/control/clear_kill_switch")
async def api_unified_control_clear_kill_switch(role: Role, request: Request):
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    headers = {"X-API-Key": DASHBOARD_API_KEY}
    return await _audited_post_json(
        request=request,
        action="CONTROL_CLEAR_KILL_SWITCH",
        role=role,
        target_id="clear_kill_switch",
        url=f"{base}/api/control/clear_kill_switch",
        headers=headers,
        json_body={},
    )

@app.post("/api/unified/{role}/signals/{signal_id}/approve")
async def api_unified_signal_approve(role: Role, signal_id: int, request: Request):
    """Approve a signal in the selected dashboard role."""
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    body = {}
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}

    payload = {"id": int(signal_id)}
    # allow note/payload passthrough (optional)
    if "note" in body:
        payload["note"] = body.get("note")
    if isinstance(body.get("payload"), dict):
        payload["payload"] = body.get("payload")

    headers = {"X-API-Key": DASHBOARD_API_KEY}
    return await _audited_post_json(request=request, action="SIGNAL_APPROVE", role=role, target_id=str(signal_id), url=f"{base}/api/signals/approve", headers=headers, json_body=payload)

@app.post("/api/unified/{role}/signals/{signal_id}/reject")
async def api_unified_signal_reject(role: Role, signal_id: int, request: Request):
    """Reject a signal in the selected dashboard role."""
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    body = {}
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}

    payload = {"id": int(signal_id)}
    payload["reason"] = str(body.get("reason") or "Rejected from Unified UI")
    if "note" in body:
        payload["note"] = body.get("note")

    headers = {"X-API-Key": DASHBOARD_API_KEY}
    return await _audited_post_json(request=request, action="SIGNAL_REJECT", role=role, target_id=str(signal_id), url=f"{base}/api/signals/reject", headers=headers, json_body=payload)



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

    headers = {"X-API-Key": DASHBOARD_API_KEY} if DASHBOARD_API_KEY else None
    upstream = await _audited_post_json(
        request=request,
        action="BRAIN_SUGGEST_SIGNAL",
        role=str(role),
        target_id=symbol,
        url=_dash_url(str(role), "/publish"),
        json_body=publish_payload,
        headers=headers,
    )

    # include the decision for the UI
    try:
        upstream["decision"] = decision
    except Exception:
        pass

    return JSONResponse(upstream)

@app.post("/api/unified/{role}/commands/close_all")
async def api_unified_command_close_all(role: Role, request: Request):
    """Queue CLOSE_ALL_POSITIONS for the selected role."""
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}

    reason = str(body.get("reason") or "close_all").strip()
    json_body = {"cmd": "CLOSE_ALL_POSITIONS", "params": {"reason": reason}}
    headers = {"X-API-Key": DASHBOARD_API_KEY}
    return await _audited_post_json(
        request=request,
        action="COMMAND_QUEUE",
        role=role,
        target_id="CLOSE_ALL_POSITIONS",
        url=f"{base}/api/commands/queue",
        headers=headers,
        json_body=json_body,
    )

@app.post("/api/unified/{role}/commands/kill_switch")
async def api_unified_command_kill_switch(role: Role, request: Request):
    """Toggle KILL_SWITCH_ON / KILL_SWITCH_OFF for the selected role."""
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}

    enabled_raw = body.get("enabled", True)
    enabled = bool(enabled_raw)
    if isinstance(enabled_raw, str):
        enabled = enabled_raw.strip().lower() in ("1", "true", "yes", "on")

    reason_default = "kill_switch_on" if enabled else "kill_switch_off"
    reason = str(body.get("reason") or reason_default).strip()
    cmd = "KILL_SWITCH_ON" if enabled else "KILL_SWITCH_OFF"
    json_body = {"cmd": cmd, "params": {"reason": reason, "enabled": enabled}}
    headers = {"X-API-Key": DASHBOARD_API_KEY}
    return await _audited_post_json(
        request=request,
        action="COMMAND_QUEUE",
        role=role,
        target_id=cmd,
        url=f"{base}/api/commands/queue",
        headers=headers,
        json_body=json_body,
    )

@app.post("/api/unified/{role}/commands")
async def api_unified_queue_command(role: Role, request: Request):
    """Queue a command into the selected dashboard role (for execution_monitor/risk_monitor)."""
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    cmd = str(body.get("cmd") or "").strip().upper()
    params = body.get("params")
    if not cmd:
        raise HTTPException(status_code=400, detail="cmd is required")

    json_body = {"cmd": cmd, "params": params if isinstance(params, dict) else {}}
    headers = {"X-API-Key": DASHBOARD_API_KEY}
    return await _audited_post_json(request=request, action="COMMAND_QUEUE", role=role, target_id=cmd, url=f"{base}/api/commands/queue", headers=headers, json_body=json_body)

@app.get("/api/mina/{role}/{path:path}")
async def mina_proxy(role: Role, path: str, request: Request):
    """
    Proxy Mina dashboard /api/* endpoints via Gateway using X-API-Key.
    Example:
      /api/mina/paper/signals?limit=10  ->  http://mina_dashboard_paper:8000/api/signals?limit=10
    """
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")

    # Prevent proxying non-api paths
    # We always proxy to /api/{path}
    upstream = f"{base}/api/{path}".rstrip("/")
    headers = {"X-API-Key": DASHBOARD_API_KEY}

    # Forward query params
    params = dict(request.query_params)

    return await _fetch_json(upstream, headers=headers, params=params)


@app.post("/api/mina/{role}/{path:path}")
async def mina_proxy_post(role: Role, path: str, request: Request):
    """
    Proxy Mina dashboard /api/* POST endpoints via Gateway using X-API-Key.
    Example:
      /api/mina/pump/pump/candidates/reject -> http://mina_dashboard_pump:8002/api/pump/candidates/reject
    """
    base = ROLE_URLS.get(role)
    if not base:
        raise HTTPException(status_code=404, detail="Unknown role")

    upstream = f"{base}/api/{path}".rstrip("/")
    headers = {"X-API-Key": DASHBOARD_API_KEY}

    try:
        body = await request.json()
    except Exception:
        body = {}

    return await _post_json(upstream, headers=headers, json_body=body)


# ---------------------------
# Brain passthrough proxy
# ---------------------------

_RESERVED_API_PREFIXES = (
    "unified",
    "mina",
    "audit",
    "audit_log",
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
# Serve Unified UI (static SPA)
# ---------------------------
UI_DIST_DIR = os.getenv("UI_DIST_DIR", "/app/ui_dist")
if os.path.isdir(UI_DIST_DIR):
    app.mount("/", StaticFiles(directory=UI_DIST_DIR, html=True), name="ui")
