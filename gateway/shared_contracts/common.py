from __future__ import annotations

from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict

from .version import SCHEMA_VERSION


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BotIdentity(BaseModel):
    """Identity of the producer."""

    bot_id: str = Field(..., min_length=1)
    bot_role: str = Field(..., min_length=1)
    bot_version: str = Field(..., min_length=1)


class TraceContext(BaseModel):
    decision_id: str = Field(..., min_length=8, description='Stable id for a decision (UUID recommended)')
    trace_id: str = Field(..., min_length=8, description='End-to-end trace id (UUID recommended)')


class EventBase(BaseModel):
    """Base event contract for v1.

    - `schema_version` locks required fields.
    - `extra=allow` enables forward-compat.
    """

    model_config = ConfigDict(
        extra='allow',
        protected_namespaces=(),  # allow fields like `model_version` without warnings
    )

    schema_version: int = Field(default=SCHEMA_VERSION)
    timestamp_utc: datetime = Field(default_factory=utcnow)

    identity: BotIdentity
    trace: TraceContext
