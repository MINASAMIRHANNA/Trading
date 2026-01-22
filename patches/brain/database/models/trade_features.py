
from __future__ import annotations

from datetime import datetime
from sqlalchemy import Integer, String, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

# Prefer the project's Base if available
try:
    from database.base import Base  # type: ignore
except Exception:
    from sqlalchemy.orm import DeclarativeBase

    class Base(DeclarativeBase):  # type: ignore
        pass


class TradeFeature(Base):
    __tablename__ = "trade_features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=True)

    # Keep flexible feature storage
    features: Mapped[dict] = mapped_column(JSON, nullable=True)
