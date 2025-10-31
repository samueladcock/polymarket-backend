import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient

def main():
    load_dotenv()

    host = os.getenv("CLOB_HOST", "https://clob.polymarket.com")
    chain_id = int(os.getenv("CHAIN_ID", "137"))

    api_key = os.getenv("API_KEY")
    api_secret = os.getenv("API_SECRET")
    api_passphrase = os.getenv("API_PASSPHRASE")

    if not (api_key and api_secret and api_passphrase):
        raise Exception("❌ Missing API credentials in .env")

    # Bundle creds into a dict
    api_creds = {
        "key": api_key,
        "secret": api_secret,
        "passphrase": api_passphrase,
    }

    # Initialise client with L2 API credentials
    client = ClobClient(host=host, api_creds=api_creds, chain_id=chain_id)

    # Your order id
    order_id = "0x8d27bc8a0bcfa84dd78dd6acc44cb36ce1d248e50e9856d9eaba8889751d1d74"
    order = client.get_order(order_id)

    print("📦 Order details:")
    print(order)

if __name__ == "__main__":
    main()
