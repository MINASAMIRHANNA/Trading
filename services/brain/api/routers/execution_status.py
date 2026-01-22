from fastapi import APIRouter
from execution.config import EXECUTION_ENABLED, DRY_RUN_ONLY

router = APIRouter()

@router.get("/status")
def execution_status():
    return {
        "execution_enabled": EXECUTION_ENABLED,
        "mode": "dry-run" if DRY_RUN_ONLY else "live",
        "ready": True,
        "reason": (
            "Execution disabled in v1 (safety lock)"
            if not EXECUTION_ENABLED
            else "Execution enabled"
        )
    }
