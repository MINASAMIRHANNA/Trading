from fastapi import APIRouter
from datetime import datetime, timezone
import random

from database.session import get_session
from database.models.trade_features import TradeFeature

router = APIRouter()

@router.post("/seed")
def seed(n: int = 20, symbol: str = "BTCUSDT"):
    """Insert demo TradeFeature rows for local testing."""
    n = max(1, min(int(n or 20), 500))
    now = datetime.now(timezone.utc)
    base_id = int(now.timestamp() * 1000)

    inserted = 0
    for session in get_session():
        for i in range(n):
            pnl = random.uniform(-0.8, 1.2)  # pnl_pct
            f = {
                "trade_time": now.isoformat().replace("+00:00","Z"),
                "entry_vs_close_pct": pnl,
                "entry_vs_ema_20_pct": random.uniform(-1.0, 1.0),
                "entry_vs_ema_50_pct": random.uniform(-1.5, 1.5),
                "atr_pct_at_entry": random.uniform(0.1, 2.5),
                "rsi_bucket": random.choice([20, 30, 40, 50, 60, 70, 80]),
                "market_regime_encoded": random.choice([0, 1, 2]),
                "directional_alignment": random.choice([0, 1]),
                "pnl_pct": pnl,
                "market_join_valid": True,
            }
            obj = TradeFeature(
                symbol=symbol,
                timestamp_utc=now,
                features=f,
                source_role="paper",
                source_trade_id=base_id + i + 1,
                source_status="CLOSED",
                source_closed_at_ms=base_id,
                source_pnl=pnl,
            )
            session.add(obj)
            inserted += 1
    return {"ok": True, "inserted": inserted, "symbol": symbol}
