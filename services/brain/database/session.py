from sqlalchemy.orm import sessionmaker, Session
from database.engine import get_engine

_engine = get_engine(echo=False)

SessionLocal = sessionmaker(
    bind=_engine,
    autocommit=False,
    autoflush=False,
    future=True
)

def get_session() -> Session:
    """
    Provides a transactional database session.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
