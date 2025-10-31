import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient

def main():
    load_dotenv()

    host = os.getenv("CLOB_HOST", "https://clob.polymarket.com")
    chain_id = int(os.getenv("CHAIN_ID", "137"))

    private_key = os.getenv("PRIVATE_KEY")
    api_key = os.getenv("API_KEY")
    api_secret = os.getenv("API_SECRET")
    api_passphrase = os.getenv("API_PASSPHRASE")

    if not api_key or not api_secret or not api_passphrase:
        # No creds yet → generate them
        if not private_key:
            raise Exception("Missing PRIVATE_KEY in .env")
        client = ClobClient(host=host, key=private_key, chain_id=chain_id)
        creds = client.create_or_derive_api_creds()
        print("✅ API Key:", creds.api_key)
        print("✅ API Secret:", creds.api_secret)
        print("✅ API Passphrase:", creds.api_passphrase)
        print("👉 Save these in your .env for future use")
    else:
        # Already have creds → use them to fetch order
        client = ClobClient(
            host=host,
            key=api_key,
            secret=api_secret,
            passphrase=api_passphrase,
            chain_id=chain_id,
            auth_type="api"
        )
        order_id = "0x8d27bc8a0bcfa84dd78dd6acc44cb36ce1d248e50e9856d9eaba8889751d1d74"
        order = client.get_order(order_id)
        print("📦 Order info:", order)

if __name__ == "__main__":
    main()
