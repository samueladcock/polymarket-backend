import time
import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient

# Load environment variables from .env
load_dotenv()

PRIVATE_KEY = os.getenv("PRIVATE_KEY")
CLOB_HOST = os.getenv("CLOB_HOST", "https://clob.polymarket.com")

if not PRIVATE_KEY:
    raise ValueError("❌ PRIVATE_KEY not found in .env file")

# Connect to Polymarket client with private key
client = ClobClient(private_key=PRIVATE_KEY, host=CLOB_HOST)

def cancel_all_open_orders():
    try:
        open_orders = client.get_open_orders()
        if not open_orders:
            print("✅ No open orders")
            return

        print(f"⏱ Found {len(open_orders)} open orders, cancelling...")
        for order in open_orders:
            oid = order["id"]
            client.cancel_order(oid)
            print(f"❌ Cancelled order {oid}")

    except Exception as e:
        print("⚠️ Error while cancelling orders:", e)

if __name__ == "__main__":
    print("🚀 Starting cancel loop (every 30s)...")
    while True:
        cancel_all_open_orders()
        time.sleep(30)
