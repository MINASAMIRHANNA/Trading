import os
from dotenv import load_dotenv
from binance.client import Client

load_dotenv()

def get_binance_client() -> Client:
    """
    Create a READ-ONLY Binance client.
    Supports Live and Futures Testnet.
    """
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    environment = os.getenv("ENVIRONMENT", "paper").lower()

    if not api_key or not api_secret:
        raise ValueError("Binance API keys are missing")

    trading_enabled = os.getenv("BINANCE_TRADING_ENABLED", "false").lower()
    if trading_enabled == "true":
        raise RuntimeError("Trading is disabled by design")

    client = Client(api_key, api_secret)

    # 🔁 IMPORTANT: Testnet vs Live
    if environment == "testnet":
        client.FUTURES_URL = "https://testnet.binancefuture.com/fapi"
        print("🧪 Binance Futures TESTNET mode enabled")

    else:
        print("🌐 Binance Futures LIVE mode enabled (read-only)")

    return client
