# main.py — Polymarket Order Service (FastAPI)
# - DRY_RUN=true (default): echoes normalized order
# - DRY_RUN=false: places a real limit order via py-clob-client
# - Accepts token_id (preferred) or slug+outcome (we resolve token_id via Gamma API)
# - Optional shared-secret header x-api-key (SHEETS_SECRET) to protect mutating endpoints
# - Adds: /order_status, /orders_open, /fills, /gamma_preview
#
# ENV (.env) — required:
#   PRIVATE_KEY=0x...
#   POLYMARKET_PROXY=0xYourProxyAddress   # from your Polymarket profile
#
# Optional (defaults shown):
#   SIGNATURE_TYPE=1                      # 2=browser wallet (MetaMask/Coinbase), 1=Magic/email
#   CLOB_HOST=https://clob.polymarket.com
#   CHAIN_ID=137
#   DRY_RUN=true
#   SHEETS_SECRET=
#   API_KEY=

from fastapi import FastAPI, HTTPException, Header, Query
from pydantic import BaseModel, field_validator
from typing import Optional, Literal, List, Any, Dict
from dotenv import load_dotenv
import os, requests, json

from eth_account import Account

# ── Env ───────────────────────────────────────────────────────────────────────
load_dotenv()
PRIVATE_KEY       = (os.getenv("PRIVATE_KEY") or "").strip()
API_KEY           = (os.getenv("API_KEY") or "").strip()             # used for REST fallbacks only
CLOB_HOST         = (os.getenv("CLOB_HOST") or "https://clob.polymarket.com").strip()
CHAIN_ID          = int(os.getenv("CHAIN_ID") or "137")              # 137=Polygon mainnet
DRY_RUN           = (os.getenv("DRY_RUN") or "true").lower() in ("1", "true", "yes")
SHEETS_SECRET     = (os.getenv("SHEETS_SECRET") or "").strip()

# NEW: signature + proxy funder (to spend from Polymarket balance)
SIGNATURE_TYPE    = int(os.getenv("SIGNATURE_TYPE") or "2")          # 2=browser wallet, 1=Magic/email
POLYMARKET_PROXY  = (os.getenv("POLYMARKET_PROXY") or "").strip()    # proxy wallet from Polymarket profile

def _assert_trading_ready():
    if not PRIVATE_KEY:
        raise RuntimeError("PRIVATE_KEY missing in .env")
    if not PRIVATE_KEY.startswith("0x") or len(PRIVATE_KEY) != 66:
        raise RuntimeError("PRIVATE_KEY must be a 32-byte hex key prefixed with 0x (length 66).")
    if CHAIN_ID not in (137, 80002, 80001):
        raise RuntimeError(f"Unexpected CHAIN_ID={CHAIN_ID}. Expected 137 (Polygon mainnet) or testnets 80001/80002.")
    if not POLYMARKET_PROXY or not POLYMARKET_PROXY.startswith("0x") or len(POLYMARKET_PROXY) != 42:
        raise RuntimeError("POLYMARKET_PROXY missing/invalid in .env (0x… address from your Polymarket profile).")
    if SIGNATURE_TYPE not in (1, 2):
        raise RuntimeError("SIGNATURE_TYPE must be 1 (Magic/email) or 2 (browser wallet).")

def _mask(s: Optional[str], keep: int = 6) -> Optional[str]:
    if not s:
        return None
    s = str(s)
    return "*" * max(0, len(s) - keep) + s[-keep:]

def _http_get(url: str, *, params: Dict[str, Any] = None, headers: Dict[str, str] = None, timeout: int = 20):
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        return r
    except requests.RequestException as e:
        raise HTTPException(502, f"Network error to {url}: {e}")

def _trade_address() -> str:
    """
    The address whose open orders / fills we should query.
    Prefer the Polymarket proxy (that’s where your Polymarket balance and orders live).
    """
    if POLYMARKET_PROXY:
        return POLYMARKET_PROXY
    return Account.from_key(PRIVATE_KEY).address

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Polymarket Order Service", version="0.7.0")

@app.get("/health")
def health():
    return {"ok": True, "service": "polymarket-order-service", "dry_run": DRY_RUN}

@app.get("/config")
def config():
    return {
        "ok": True,
        "clob_host": CLOB_HOST,
        "chain_id": CHAIN_ID,
        "has_api_key": bool(API_KEY),
        "dry_run": DRY_RUN,
        "auth_required": bool(SHEETS_SECRET),
        "signature_type": SIGNATURE_TYPE,
        "has_proxy": bool(POLYMARKET_PROXY),
        "proxy_masked": _mask(POLYMARKET_PROXY),
    }

@app.get("/whoami")
def whoami():
    try:
        eoa = Account.from_key(PRIVATE_KEY).address if PRIVATE_KEY else None
    except Exception:
        eoa = None
    return {
        "ok": True,
        "eoa_address": eoa,
        "proxy_address": POLYMARKET_PROXY or None,
        "using_proxy": bool(POLYMARKET_PROXY),
        "signature_type": SIGNATURE_TYPE,
        "chain_id": CHAIN_ID,
        "clob_host": CLOB_HOST,
        "dry_run": DRY_RUN,
        "has_api_key": bool(API_KEY),
        "api_key_masked": _mask(API_KEY),
        "auth_required_for_place_order": bool(SHEETS_SECRET),
    }

# ── Models ────────────────────────────────────────────────────────────────────
Side = Literal["BUY", "SELL"]

class PlaceOrderIn(BaseModel):
    token_id: Optional[str] = None        # preferred (clobTokenId)
    slug: Optional[str] = None            # optional if token_id given
    outcome: Optional[str] = None         # optional if token_id given (case-insensitive)
    side: Side
    price_cents: float                    # e.g., 34.5 => 0.345 prob
    size: float                           # shares
    client_tag: Optional[str] = None

    @field_validator("side")
    @classmethod
    def v_side(cls, v: str) -> str:
        v2 = v.upper()
        if v2 not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        return v2

    @field_validator("price_cents")
    @classmethod
    def v_price_cents(cls, v: float) -> float:
        f = float(v)
        if not (0.5 <= f <= 99.5):
            raise ValueError("price_cents must be between 0.5 and 99.5")
        return f

    @field_validator("size")
    @classmethod
    def v_size(cls, v: float) -> float:
        f = float(v)
        if f <= 0:
            raise ValueError("size must be > 0")
        return f

def _normalize_price(prob_cents: float) -> float:
    """Convert 34.5¢ -> 0.345; quantize to 0.01 probability tick."""
    p = float(prob_cents) / 100.0
    # CLOB tick size is 0.01 probability => 1c
    return round(p, 2)

# ── Gamma API resolution (slug -> token_id) ───────────────────────────────────
def _as_list(v) -> List[Any]:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            parts = [s.strip() for s in v.split(",") if s.strip()]
            return parts if parts else []
    return []

def resolve_token_id_via_gamma(slug: str, outcome_name: str) -> dict:
    if not slug:
        raise HTTPException(400, "slug is required when token_id is not provided.")
    url = f"https://gamma-api.polymarket.com/markets?slug={requests.utils.quote(slug)}"
    r = _http_get(url, timeout=20)
    if r.status_code != 200:
        raise HTTPException(502, f"Gamma API error {r.status_code}: {r.text[:300]}")
    data = r.json()
    if not data or not isinstance(data, list):
        raise HTTPException(404, f"No markets returned for slug '{slug}'")

    best = None
    for m in data:
        outcomes = (
            _as_list(m.get("outcomes"))
            or _as_list(m.get("outcomeNames"))
            or _as_list(m.get("shortOutcomes"))
        )
        token_ids = _as_list(m.get("clobTokenIds"))
        prices    = _as_list(m.get("outcomePrices"))
        if token_ids:
            best = {
                "slug": m.get("slug", ""),
                "question": m.get("question") or m.get("title") or "(no title)",
                "outcomes": outcomes,
                "token_ids": [str(t) for t in token_ids],
                "prices": [float(p) for p in prices] if prices else [],
            }
            break
    if not best:
        raise HTTPException(404, f"Could not find outcome token IDs for slug '{slug}'")

    # Try exact (case-insensitive) match; if not found, show available
    target = (outcome_name or "").strip().lower()
    names = best["outcomes"] if best["outcomes"] else ["Yes", "No"]
    try_idx = None
    for i, n in enumerate(names):
        if str(n).strip().lower() == target:
            try_idx = i
            break
    if try_idx is None:
        raise HTTPException(
            404,
            f"Outcome '{outcome_name}' not found for slug '{slug}'. "
            f"Available: {', '.join(map(str, names))}"
        )

    token_id = best["token_ids"][try_idx]
    return {
        "token_id": token_id,
        "market_slug": best["slug"],
        "question": best["question"],
        "outcome_index": try_idx,
        "outcome_name": names[try_idx],
    }

# ── Live order via py-clob-client (proxy mode) ────────────────────────────────
def place_live_limit_order(token_id: str, side: str, price: float, size: float):
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY, SELL
    except Exception as e:
        raise HTTPException(500, f"py-clob-client import failed: {e}")

    try:
        # IMPORTANT: pass signature_type and funder (proxy) so settlement uses your Polymarket balance
        client = ClobClient(
            CLOB_HOST,
            key=PRIVATE_KEY,
            chain_id=CHAIN_ID,
            signature_type=SIGNATURE_TYPE,
            funder=POLYMARKET_PROXY
        )

        # Derive/set L2 creds (headers) for CLOB requests
        client.set_api_creds(client.create_or_derive_api_creds())

        side_const = BUY if side.upper() == "BUY" else SELL
        order_args = OrderArgs(
            price=float(price),
            size=float(size),
            side=side_const,
            token_id=str(token_id),
        )
        signed_order = client.create_order(order_args)
        return client.post_order(signed_order, OrderType.GTC)
    except Exception as e:
        raise HTTPException(500, f"Order placement failed: {e}")

# ── Routes ────────────────────────────────────────────────────────────────────
@app.post("/place_order")
def place_order(inp: PlaceOrderIn, x_api_key: Optional[str] = Header(None)):
    if SHEETS_SECRET and x_api_key != SHEETS_SECRET:
        raise HTTPException(401, "Unauthorized (x-api-key mismatch)")

    price_prob = _normalize_price(inp.price_cents)
    side  = inp.side
    size  = float(inp.size)

    # (Optional) $1 notional guard to reduce server-side 400s
    notional = (price_prob if side == "BUY" else (1.0 - price_prob)) * size
    if notional < 1.0:
        raise HTTPException(400, f"Order notional ${notional:.2f} is below $1 minimum.")

    # DRY RUN returns the normalized order that would be sent
    if DRY_RUN:
        return {
            "ok": True,
            "dry_run": True,
            "normalized": {
                "side": side,
                "token_id": inp.token_id,
                "slug": inp.slug,
                "outcome": inp.outcome,
                "price_prob": price_prob,
                "size": size,
                "client_tag": inp.client_tag,
            }
        }

    _assert_trading_ready()

    token_id = inp.token_id
    market_info = None
    if not token_id:
        if not inp.slug or not inp.outcome:
            raise HTTPException(400, "Provide either token_id OR (slug + outcome).")
        market_info = resolve_token_id_via_gamma(inp.slug, inp.outcome)
        token_id = market_info["token_id"]

    result = place_live_limit_order(token_id=token_id, side=side, price=price_prob, size=size)
    return {
        "ok": True,
        "dry_run": False,
        "result": result,
        "token_id": token_id,
        "slug": market_info["market_slug"] if market_info else None,
        "outcome": market_info["outcome_name"] if market_info else inp.outcome,
        "price_prob": price_prob,
        "size": size
    }

# --- Tracking: get one order by order_id -------------------------------------
@app.get("/order_status")
def order_status(
    order_id: str = Query(..., description="CLOB order id (0x...)"),
    x_api_key: Optional[str] = Header(None)
):
    if SHEETS_SECRET and x_api_key != SHEETS_SECRET:
        raise HTTPException(401, "Unauthorized (x-api-key mismatch)")

    try:
        from py_clob_client.client import ClobClient
        client = ClobClient(
            CLOB_HOST,
            key=PRIVATE_KEY,
            chain_id=CHAIN_ID,
            signature_type=SIGNATURE_TYPE,
            funder=POLYMARKET_PROXY or None
        )
        client.set_api_creds(client.create_or_derive_api_creds())
        order = client.get_order(order_id)
        return {"ok": True, "order": order}
    except Exception as e:
        # Optional REST fallback (may still require proper L2 headers)
        try:
            url = f"{CLOB_HOST}/data/order/{order_id}"
            headers = {}
            if API_KEY:
                headers["x-api-key"] = API_KEY
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code == 200:
                return {"ok": True, "order": r.json()}
            raise HTTPException(r.status_code, f"CLOB {r.status_code}: {r.text[:300]}")
        except Exception as e2:
            raise HTTPException(500, f"order_status failed: {e} | fallback: {e2}")

# --- Tracking: list open orders ----------------------------------------------
@app.get("/orders_open")
def orders_open(x_api_key: Optional[str] = Header(None)):
    if SHEETS_SECRET and x_api_key != SHEETS_SECRET:
        raise HTTPException(401, "Unauthorized (x-api-key mismatch)")

    try:
        from py_clob_client.client import ClobClient
        client = ClobClient(
            CLOB_HOST,
            key=PRIVATE_KEY,
            chain_id=CHAIN_ID,
            signature_type=SIGNATURE_TYPE,
            funder=POLYMARKET_PROXY or None
        )
        client.set_api_creds(client.create_or_derive_api_creds())
        try:
            return {"ok": True, "orders": client.get_open_orders()}
        except Exception:
            # Fallback to REST by address (prefer proxy)
            addr = _trade_address()
            r = _http_get(
                f"{CLOB_HOST}/orders",
                params={"address": addr, "status": "OPEN"},
                headers={"x-api-key": API_KEY} if API_KEY else {},
                timeout=20
            )
            if r.status_code != 200:
                raise HTTPException(r.status_code, f"CLOB {r.status_code}: {r.text[:300]}")
            return {"ok": True, "orders": r.json()}
    except Exception as e:
        raise HTTPException(500, f"orders_open failed: {e}")

# --- Tracking: recent fills (executed trades) ---------------------------------
@app.get("/fills")
def fills(limit: int = 50, x_api_key: Optional[str] = Header(None)):
    if SHEETS_SECRET and x_api_key != SHEETS_SECRET:
        raise HTTPException(401, "Unauthorized (x-api-key mismatch)")

    addr = _trade_address()
    r = _http_get(
        f"{CLOB_HOST}/trades",
        params={"address": addr, "limit": int(limit)},
        headers={"x-api-key": API_KEY} if API_KEY else {},
        timeout=20
    )
    if r.status_code != 200:
        raise HTTPException(r.status_code, f"CLOB {r.status_code}: {r.text[:300]}")
    return {"ok": True, "fills": r.json()}

# --- Debug helper: inspect slug/outcomes/tokenIds -----------------------------
@app.get("/gamma_preview")
def gamma_preview(slug: str):
    url = f"https://gamma-api.polymarket.com/markets?slug={requests.utils.quote(slug)}"
    r = _http_get(url, timeout=20)
    if r.status_code != 200:
        raise HTTPException(502, f"Gamma API error {r.status_code}: {r.text[:300]}")
    rows = []
    for m in r.json() if isinstance(r.json(), list) else []:
        rows.append({
            "slug": m.get("slug"),
            "question": m.get("question") or m.get("title"),
            "outcomes": _as_list(m.get("outcomes")) or _as_list(m.get("outcomeNames")) or _as_list(m.get("shortOutcomes")),
            "clobTokenIds": _as_list(m.get("clobTokenIds")),
            "outcomePrices": _as_list(m.get("outcomePrices")),
        })
    if not rows:
        raise HTTPException(404, f"No markets found for slug '{slug}'.")
    return {"ok": True, "markets": rows}

# Run with:
# uvicorn main:app --host 127.0.0.1 --port 8010 --reload

# --- Mutating: cancel a single order ------------------------------------------
@app.get("/cancel_order")
def cancel_order(
    order_id: str = Query(..., description="CLOB order id (0x...)"),
    x_api_key: Optional[str] = Header(None)
):
    if SHEETS_SECRET and x_api_key != SHEETS_SECRET:
        raise HTTPException(401, "Unauthorized (x-api-key mismatch)")

    _assert_trading_ready()

    try:
        from py_clob_client.client import ClobClient
        client = ClobClient(
            CLOB_HOST,
            key=PRIVATE_KEY,
            chain_id=CHAIN_ID,
            signature_type=SIGNATURE_TYPE,
            funder=POLYMARKET_PROXY or None
        )
        client.set_api_creds(client.create_or_derive_api_creds())
        result = client.cancel_order(order_id)
        return {"ok": True, "result": result}
    except Exception as e:
        raise HTTPException(500, f"cancel_order failed: {e}")

