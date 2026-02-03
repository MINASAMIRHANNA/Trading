from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.deps import get_db
from database.models.sync_state import SyncState
from ingestion.mina.sync_trades import sync_mina_trades

router = APIRouter()

@router.get("/status")
def status(db: Session = Depends(get_db)):
    items = db.query(SyncState).order_by(SyncState.updated_at.desc()).limit(100).all()
    def _row(x: SyncState):
        return {
            "role": x.role,
            "last_trade_id": int(x.last_trade_id or 0),
            "updated_at": x.updated_at.isoformat() if x.updated_at else None,
        }
    return {"ok": True, "items": [_row(x) for x in items], "count": len(items)}

@router.post("/run")
def run(
    role: Optional[str] = Query(default=None, description="paper | live | pump (optional). If omitted, sync all roles."),
    symbol: Optional[str] = Query(default=None, description="Optional symbol filter, e.g. BTCUSDT."),
    limit: Optional[int] = Query(default=None, ge=1, le=200000, description="Optional max trades to fetch per role."),
    dry_run: bool = Query(default=False, description="If true, do not write anything to the Brain DB."),
    db: Session = Depends(get_db),
):
    out = sync_mina_trades(
        db,
        role=role,
        symbol=symbol,
        limit=limit,
        dry_run=dry_run,
    )
    return out
