from __future__ import annotations

from typing import Literal, Optional
from pydantic import Field

from .common import EventBase

TradeAction = Literal['OPEN', 'CLOSE', 'UPDATE', 'PARTIAL_CLOSE']
ExitReason = Literal['TP', 'SL', 'TRAIL', 'MANUAL', 'RISK_KILL', 'TIMEOUT', 'ERROR', 'UNKNOWN']


class TradeEvent(EventBase):
    event_type: Literal['TradeEvent'] = 'TradeEvent'

    symbol: str = Field(..., min_length=3)
    action: TradeAction

    order_id: Optional[str] = None
    position_id: Optional[str] = None

    price: Optional[float] = None
    qty: Optional[float] = None
    fees: Optional[float] = None

    slippage_bps: Optional[float] = None
    latency_ms: Optional[int] = None

    exit_reason: ExitReason = 'UNKNOWN'

    pnl_pct: Optional[float] = None
    pnl_usd: Optional[float] = None
