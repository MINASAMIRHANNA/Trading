from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
import os

# Default to SQLite for local development
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./trading_intelligence.db"
)

def get_engine(echo: bool = False) -> Engine:
    """
    Create and return SQLAlchemy Engine.
    Execution is read-only by design for analytics purposes.
    """
    engine = create_engine(
        DATABASE_URL,
        echo=echo,
        future=True
    )
    return engine
