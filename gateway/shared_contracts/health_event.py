from __future__ import annotations

from typing import Literal, Optional, Dict, Any
from pydantic import Field

from .common import EventBase

HealthStatus = Literal['OK', 'DEGRADED', 'DOWN']


class HealthEvent(EventBase):
    event_type: Literal['HealthEvent'] = 'HealthEvent'

    service_name: str = Field(..., min_length=1)
    status: HealthStatus = 'OK'

    ws_connected: Optional[bool] = None
    queue_size: Optional[int] = None
    db_ok: Optional[bool] = None

    notes: Optional[str] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)
