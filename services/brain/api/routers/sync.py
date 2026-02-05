from __future__ import annotations

from typing import Optional
from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from api.deps import get_db, get_dataset
from database.models.sync_state import SyncState
from database.models.trade_features import TradeFeature
from ingestion.mina.sync_trades import get_source_engine, _resolve_source_schema, _source_counts
from ingestion.mina.sync_trades import sync_mina_trades

router = APIRouter()
logger = logging.getLogger(__name__)
VALID_ROLES = ("paper", "live", "pump")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def _status_payload(role: Optional[str], db: Session) -> dict:
    if not role:
        items = db.query(SyncState).order_by(SyncState.updated_at.desc()).limit(100).all()
        out = []
        for x in items:
            out.append(
                {
                    "role": x.role,
                    "last_trade_id": int(x.last_trade_id or 0),
                    "updated_at": x.updated_at.isoformat() if x.updated_at else None,
                }
            )
        return {"ok": True, "items": out, "count": len(out)}

    state = db.get(SyncState, role)
    schema = _resolve_source_schema(role)
    source_engine = get_source_engine()
    source_counts = _source_counts(source_engine, schema)
    valid_filter = (
        TradeFeature.source_trade_id > 0,
        TradeFeature.source_role.in_(VALID_ROLES),
    )
    brain_total = int(db.query(TradeFeature).filter(*valid_filter).count())
    brain_role = int(
        db.query(TradeFeature)
        .filter(TradeFeature.source_role == role, *valid_filter)
        .count()
    )

    return {
        "ok": True,
        "role": role,
        "schema": schema,
        "sync_state": {
            "role": role,
            "last_trade_id": int(state.last_trade_id) if state else 0,
            "updated_at": state.updated_at.isoformat() if state and state.updated_at else None,
        },
        "source_counts": source_counts,
        "brain_counts": {"total": brain_total, "by_role": brain_role},
    }


@router.get("/status")
def status(role: Optional[str] = Query(default=None), db: Session = Depends(get_db)):
    return _status_payload(role, db)


@router.post("/status")
def status_post(role: Optional[str] = Query(default=None), db: Session = Depends(get_db)):
    return _status_payload(role, db)


@router.post("/reset")
def reset(role: str = Query(..., description="paper | live | pump"), db: Session = Depends(get_db)):
    state = db.get(SyncState, role)
    prev = int(state.last_trade_id) if state else 0
    if state is None:
        state = SyncState(role=role, last_trade_id=0)
        db.add(state)
    else:
        state.last_trade_id = 0
    db.commit()
    return {"ok": True, "role": role, "previous_last_trade_id": prev, "new_last_trade_id": 0}


@router.post("/cleanup")
def cleanup(role: Optional[str] = Query(default=None, description="Optional role filter"), db: Session = Depends(get_db)):
    # Build invalid rows filter
    invalid_filter = (
        (TradeFeature.source_role.is_(None))
        | (TradeFeature.source_role == "unknown")
        | (TradeFeature.source_trade_id.is_(None))
        | (TradeFeature.source_trade_id <= 0)
    )

    q = db.query(TradeFeature).filter(invalid_filter)
    if role:
        q = q.filter(
            (TradeFeature.source_role == role)
            | (TradeFeature.source_role.is_(None))
            | (TradeFeature.source_role == "unknown")
        )

    deleted = q.delete(synchronize_session=False)
    db.commit()

    remaining = int(
        db.query(TradeFeature)
        .filter(
            TradeFeature.source_trade_id > 0,
            TradeFeature.source_role.in_(VALID_ROLES),
        )
        .count()
    )

    return {
        "ok": True,
        "role": role or "all",
        "deleted": int(deleted or 0),
        "remaining": remaining,
    }

@router.post("/run")
def run(
    role: Optional[str] = Query(default=None, description="paper | live | pump (optional). If omitted, sync all roles."),
    symbol: Optional[str] = Query(default=None, description="Optional symbol filter, e.g. BTCUSDT."),
    limit: Optional[int] = Query(default=None, ge=1, le=200000, description="Optional max trades to fetch per role."),
    dry_run: bool = Query(default=False, description="If true, do not write anything to the Brain DB."),
    force: bool = Query(default=False, description="If true, ignore sync_state and rescan from id=0."),
    since_id: Optional[int] = Query(default=None, description="Optional override for the starting trade id."),
    db: Session = Depends(get_db),
):
    try:
        out = sync_mina_trades(
            db,
            role=role,
            symbol=symbol,
            limit=limit,
            dry_run=dry_run,
            force=force,
            since_id=since_id,
        )
        # Clear dataset cache so overview/decision reflect new data immediately.
        try:
            get_dataset.cache_clear()
        except Exception:
            pass
        return out
    except Exception as exc:
        logger.exception("sync/run failed", extra={"role": role, "symbol": symbol, "limit": limit})
        payload = {
            "ok": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "role": role or "all",
            "ts_utc": _utc_now(),
        }
        return JSONResponse(status_code=500, content=payload)
