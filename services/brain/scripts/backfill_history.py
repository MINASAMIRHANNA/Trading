from ingestion.binance.fetch_trades import fetch_futures_trades
from ingestion.binance.save_trades import save_trades

def run():
    trades = fetch_futures_trades()
    saved = save_trades(trades)
    print(f"✅ Saved {saved} new trades")

if __name__ == "__main__":
    run()
