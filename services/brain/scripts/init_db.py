from database.engine import get_engine
from database.base import Base

# ⬇️ استيراد كل الموديلات (مهم جدًا)
from database.models.trades import Trade
from database.models.positions import Position
from database.models.accounts import AccountSnapshot
from database.models.trade_features import TradeFeature  # 👈 ده اللي كان ناقص


def init_db():
    engine = get_engine(echo=True)
    Base.metadata.create_all(bind=engine)
    print("✅ Database initialized successfully.")


if __name__ == "__main__":
    init_db()
