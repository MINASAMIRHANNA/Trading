"""Contracts v1 for Gateway Unified API.

These models are intentionally permissive (extra allowed) to remain backward compatible
with upstream dashboards/brain responses during phased integration.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ConfigDict


SchemaVersion = Literal["v1"]
Role = Literal["paper", "live", "pump"]


class BrainOverview(BaseModel):
    model_config = ConfigDict(extra="allow")

    trades: int = 0
    win_rate: float = 0.0
    avg_pnl: float = 0.0
    expectancy: float = 0.0


class DashboardStats(BaseModel):
    model_config = ConfigDict(extra="allow")

    trades: int = 0
    win_rate: float = 0.0
    pnl: float = 0.0


class SignalItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    received_at: Optional[str] = None
    received_at_ms: Optional[int] = None
    source: Optional[str] = None
    status: Optional[str] = None
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    strategy: Optional[str] = None
    side: Optional[str] = None
    confidence: Optional[float] = None
    score: Optional[float] = None
    note: Optional[str] = None
    dedupe_key: Optional[str] = None


class RoleOverview(BaseModel):
    model_config = ConfigDict(extra="allow")

    stats: DashboardStats | Dict[str, Any] | None = None
    signals_preview: List[SignalItem] | Dict[str, Any] | None = None


class UnifiedOverview(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: SchemaVersion = "v1"
    brain: BrainOverview | Dict[str, Any] | None = None
    dashboards: Dict[Role, RoleOverview] = Field(default_factory=dict)
    ts_utc: str


def json_schema() -> Dict[str, Any]:
    """Return JSON schema for the main unified payload."""
    return UnifiedOverview.model_json_schema()
