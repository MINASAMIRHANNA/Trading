from __future__ import annotations

import os
import json
import re
from typing import Any, Dict

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from learning.ai_chat import ask_ai_coach
from api.routers.strategy_ranking import strategy_ranking

router = APIRouter()

GATEWAY_API_URL = os.getenv("GATEWAY_API_URL", "http://gateway_api:8200").rstrip("/")

class CoachChatRequest(BaseModel):
    question: str
    symbol: str | None = None


def _mask_secrets(obj: Any) -> Any:
    secret_key_re = re.compile(r"(key|secret|token|pass|pwd)", re.IGNORECASE)
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if secret_key_re.search(str(k)):
                out[k] = "******"
            else:
                out[k] = _mask_secrets(v)
        return out
    if isinstance(obj, list):
        return [_mask_secrets(v) for v in obj]
    if isinstance(obj, str) and len(obj) > 12 and "sk-" in obj:
        return "******"
    return obj


def _safe_get(client: httpx.Client, path: str, params: dict | None = None) -> dict:
    url = f"{GATEWAY_API_URL}{path}"
    try:
        r = client.get(url, params=params, timeout=6)
        if r.status_code >= 400:
            return {"ok": False, "error": "upstream_error", "status": r.status_code, "body": r.text[:600]}
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/chat")
def ai_coach_chat(req: CoachChatRequest):
    # Build system snapshot from Gateway (unified overview + audit + health + logs)
    snapshot: Dict[str, Any] = {"ok": True}
    with httpx.Client() as client:
        snapshot["unified_overview"] = _safe_get(client, "/api/unified/overview")
        snapshot["audit"] = _safe_get(client, "/api/audit", params={"limit": 20})
        snapshot["health"] = {
            "paper": _safe_get(client, "/api/unified/paper/system_health"),
            "live": _safe_get(client, "/api/unified/live/system_health"),
            "pump": _safe_get(client, "/api/unified/pump/system_health"),
        }
        snapshot["logs"] = {
            "paper": _safe_get(client, "/api/unified/paper/logs", params={"limit": 50}),
            "live": _safe_get(client, "/api/unified/live/logs", params={"limit": 50}),
            "pump": _safe_get(client, "/api/unified/pump/logs", params={"limit": 50}),
        }

    # Brain-side strategy ranking (local)
    try:
        snapshot["strategy_ranking"] = strategy_ranking(symbol=req.symbol)
    except Exception as e:
        snapshot["strategy_ranking"] = {"ok": False, "error": str(e)}

    masked = _mask_secrets(snapshot)
    context = json.dumps(masked, ensure_ascii=False)
    answer = ask_ai_coach(req.question, context)
    return {"ok": True, "answer": answer, "snapshot": masked}
