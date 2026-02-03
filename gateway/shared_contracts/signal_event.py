from __future__ import annotations

from typing import Literal, Optional, Dict, Any
from pydantic import Field

from .common import EventBase

Side = Literal['LONG', 'SHORT']
Decision = Literal['DO_NOT_TRADE', 'TRADE_SELECTIVELY', 'TRADE']


class SignalEvent(EventBase):
    event_type: Literal['SignalEvent'] = 'SignalEvent'

    symbol: str = Field(..., min_length=3)
    market: str = Field(default='futures')
    timeframe: str = Field(default='1m')

    side: Side
    decision: Decision = Field(default='DO_NOT_TRADE')

    probability_calibrated: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_bucket: str = Field(default='UNKNOWN')
    regime: str = Field(default='UNKNOWN')

    veto_passed: bool = Field(default=False)
    veto_reasons: list[str] = Field(default_factory=list)

    rationale: Optional[str] = None
    model_version: Optional[str] = None
    feature_version: Optional[str] = None

    risk_params: Dict[str, Any] = Field(default_factory=dict)
