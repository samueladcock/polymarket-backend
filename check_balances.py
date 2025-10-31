from web3 import Web3
from eth_account import Account
import os, json

# Load private key from .env (or paste directly here)
pk = os.getenv("PRIVATE_KEY") or "0x..."
acct = Account.from_key(pk)
addr = acct.address
print("Wallet address:", addr)

# Polygon RPC (public endpoint)
RPC = "https://polygon-rpc.com"
w3 = Web3(Web3.HTTPProvider(RPC))

if not w3.is_connected():
    raise RuntimeError("Could not connect to Polygon RPC")

# ---- MATIC balance ----
matic_bal = w3.eth.get_balance(addr)
print(f"MATIC: {w3.from_wei(matic_bal, 'ether'):.6f}")

# ---- USDC.e balance ----
USDCe = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
abi = [
    {"constant":True,"inputs":[{"name":"_owner","type":"address"}],
     "name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],
     "type":"function"}
]
usdc_contract = w3.eth.contract(address=USDCe, abi=abi)
usdc_raw = usdc_contract.functions.balanceOf(addr).call()
# USDC.e has 6 decimals
usdc = usdc_raw / 1e6
print(f"USDC.e: {usdc:.2f}")

