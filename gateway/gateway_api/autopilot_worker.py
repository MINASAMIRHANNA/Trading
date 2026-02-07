from __future__ import annotations

import os
import time
import uuid
import datetime as dt
from typing import Any, Dict, List

import httpx


def _env(name: str, default: str | None = None) -> str:
    val = os.getenv(name)
    if val is None or str(val).strip() == "":
        return default if default is not None else ""
    return str(val)


GATEWAY_URL = _env("GATEWAY_URL", "http://gateway_api:8200").rstrip("/")
GATEWAY_API_KEY = _env("GATEWAY_API_KEY", "")
AUTOPILOT_TICK_SEC = int(float(_env("AUTOPILOT_TICK_SEC", "10")))
AUTOPILOT_MAX_SIGNALS_PER_ROLE = int(float(_env("AUTOPILOT_MAX_SIGNALS_PER_ROLE", "50")))
AUTOPILOT_ROLES = [r.strip() for r in _env("AUTOPILOT_ROLES", "paper,live,pump").split(",") if r.strip()]


SCALP_TFS = {"1m", "3m", "5m"}


def _now_utc() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _trace_id() -> str:
    return uuid.uuid4().hex


def _truthy(val: Any) -> bool:
    if val is None:
        return False
    s = str(val).strip().lower()
    return s in {"1", "true", "yes", "on"}


def _safe_float(val: Any) -> float | None:
    try:
        return float(val)
    except Exception:
        return None


def _normalize_confidence(val: Any) -> float | None:
    f = _safe_float(val)
    if f is None:
        return None
    # If confidence looks like 0-100, normalize to 0-1.
    if f > 1.0:
        return f / 100.0
    return f


def _threshold_from_settings(settings: Dict[str, Any], key: str) -> float:
    raw = settings.get(key)
    f = _safe_float(raw)
    if f is None:
        return 1.0
    return max(0.0, min(f / 100.0, 1.0))


def _pick_timeframe(sig: Dict[str, Any]) -> str:
    for k in ("timeframe", "tf", "interval"):
        v = sig.get(k)
        if v:
            return str(v).strip()
    return ""


def _get_pending_signals(signals_payload: Any) -> List[Dict[str, Any]]:
    if isinstance(signals_payload, dict):
        items = signals_payload.get("items")
        if isinstance(items, list):
            signals = items
        else:
            signals = []
    elif isinstance(signals_payload, list):
        signals = signals_payload
    else:
        signals = []
    out = []
    for s in signals:
        try:
            status = str(s.get("status") or "").strip().upper()
        except Exception:
            status = ""
        if status == "PENDING":
            out.append(s)
    return out


def _decide_action(settings: Dict[str, Any], sig: Dict[str, Any]) -> tuple[str, str, Dict[str, Any]]:
    confidence = _normalize_confidence(sig.get("confidence"))
    if confidence is None:
        return "reject", "missing_confidence", {"confidence": None}

    tf = _pick_timeframe(sig)
    is_scalp = tf in SCALP_TFS
    key = "min_conf_scalp" if is_scalp else "min_conf_swing"
    threshold = _threshold_from_settings(settings, key)

    action = "approve" if confidence >= threshold else "reject"
    reason = "confidence_ok" if action == "approve" else "below_threshold"
    meta = {
        "timeframe": tf,
        "is_scalp": is_scalp,
        "threshold": threshold,
        "confidence": confidence,
        "threshold_key": key,
    }
    return action, reason, meta


def _headers(trace_id: str) -> Dict[str, str]:
    headers = {"X-Actor": "autopilot", "X-Trace-Id": trace_id}
    if GATEWAY_API_KEY:
        headers["X-API-Key"] = GATEWAY_API_KEY
    return headers


def _post_shadow_decision(client: httpx.Client, role: str, signal_id: Any, would_action: str, reason: str, meta: Dict[str, Any]) -> None:
    trace_id = _trace_id()
    payload = {
        "role": role,
        "signal_id": signal_id,
        "would_action": would_action,
        "reason": reason,
        "meta": meta,
        "trace_id": trace_id,
    }
    client.post(f"{GATEWAY_URL}/api/autopilot/shadow_decision", json=payload, headers=_headers(trace_id))


def _post_heartbeat(client: httpx.Client, ok: bool, last_error: str | None) -> None:
    trace_id = _trace_id()
    payload = {
        "last_cycle_utc": _now_utc(),
        "ok": bool(ok),
        "last_error": last_error,
        "trace_id": trace_id,
    }
    client.post(f"{GATEWAY_URL}/api/autopilot/heartbeat", json=payload, headers=_headers(trace_id))


def _require_dashboard_approval(settings: Dict[str, Any]) -> bool:
    return _truthy(settings.get("require_dashboard_approval"))


def _run_cycle(client: httpx.Client) -> None:
    ap = client.get(f"{GATEWAY_URL}/api/unified/autopilot", headers=_headers(_trace_id())).json()
    roles = ap.get("roles") or {}

    for role in AUTOPILOT_ROLES:
        role_info = roles.get(role) or {}
        effective = str(role_info.get("effective_mode") or "OFF").upper()
        if effective == "OFF":
            continue

        settings = client.get(f"{GATEWAY_URL}/api/unified/{role}/settings", headers=_headers(_trace_id())).json()
        if _truthy(settings.get("kill_switch")):
            continue

        signals_payload = client.get(
            f"{GATEWAY_URL}/api/unified/{role}/signals",
            params={"limit": 200},
            headers=_headers(_trace_id()),
        ).json()
        pending = _get_pending_signals(signals_payload)[:AUTOPILOT_MAX_SIGNALS_PER_ROLE]
        if not pending:
            continue

        for sig in pending:
            signal_id = sig.get("id")
            action, reason, meta = _decide_action(settings, sig)
            shadow_only = effective == "SHADOW" or _require_dashboard_approval(settings)

            if shadow_only:
                _post_shadow_decision(client, role, signal_id, action, reason, meta)
                continue

            if action == "approve":
                note = f"autopilot approve (conf={meta.get('confidence')}, thr={meta.get('threshold')})"
                payload = {"note": note}
                client.post(
                    f"{GATEWAY_URL}/api/unified/{role}/signals/{int(signal_id)}/approve",
                    json=payload,
                    headers=_headers(_trace_id()),
                )
            else:
                note = f"autopilot reject (conf={meta.get('confidence')}, thr={meta.get('threshold')})"
                payload = {"reason": reason, "note": note}
                client.post(
                    f"{GATEWAY_URL}/api/unified/{role}/signals/{int(signal_id)}/reject",
                    json=payload,
                    headers=_headers(_trace_id()),
                )


def main() -> None:
    if not GATEWAY_API_KEY:
        print("⚠️  GATEWAY_API_KEY is not set. Autopilot worker will idle.")
    client = httpx.Client(timeout=20.0)

    while True:
        last_error = None
        ok = True
        try:
            if not GATEWAY_API_KEY:
                time.sleep(max(2, AUTOPILOT_TICK_SEC))
                continue
            _run_cycle(client)
        except Exception as e:
            ok = False
            last_error = f"{type(e).__name__}: {e}"
            print(f"⚠️  [autopilot_worker] cycle error: {last_error}")
        try:
            _post_heartbeat(client, ok=ok, last_error=last_error)
        except Exception as e:
            print(f"⚠️  [autopilot_worker] heartbeat error: {e}")
        time.sleep(max(2, AUTOPILOT_TICK_SEC))


if __name__ == "__main__":
    main()
