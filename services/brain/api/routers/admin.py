from __future__ import annotations

from fastapi import APIRouter

from api.deps import get_dataset

router = APIRouter()


@router.post("/dataset/refresh")
def refresh_dataset():
    try:
        get_dataset.cache_clear()
    except Exception:
        pass
    return {"ok": True, "cleared": ["dataset_cache"]}
