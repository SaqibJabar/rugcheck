import os
import re
import json
import time
from pathlib import Path
from dotenv import load_dotenv
from groq import Groq
import requests

# Load environment variables from .env file
load_dotenv()

# Initialize Groq client (will use GROQ_API_KEY env var automatically)
client = Groq()
ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY")
BSCSCAN_API_KEY = os.environ.get("BSCSCAN_API_KEY")
POLYGONSCAN_API_KEY = os.environ.get("POLYGONSCAN_API_KEY")
ARBISCAN_API_KEY = os.environ.get("ARBISCAN_API_KEY")
BASESCAN_API_KEY = os.environ.get("BASESCAN_API_KEY")

# Cache and history files
WORKDIR = Path(os.path.dirname(__file__) or '.')
CACHE_FILE = WORKDIR.joinpath(".cache.json")
HISTORY_FILE = WORKDIR.joinpath(".history.json")
CACHE_TTL = int(os.environ.get("RUGCHECK_CACHE_TTL", 60 * 60))
CACHE_VERSION = int(os.environ.get("RUGCHECK_CACHE_VERSION", 2))

# Chain ID mappings
CHAIN_NAMES = {
    "1": "Ethereum",
    "56": "BNB Chain",
    "sol": "Solana",
    "137": "Polygon",
    "42161": "Arbitrum",
    "8453": "Base"
}

# API endpoints for different chains (legacy use only, V2 uses unified Etherscan base)
BLOCKSCAN_ENDPOINTS = {
    "1": "https://api.etherscan.io/api",
    "56": "https://api.bscscan.com/api",
    "137": "https://api.polygonscan.com/api",
    "42161": "https://api.arbiscan.io/api",
    "8453": "https://api.basescan.org/api"
}

ETHERSCAN_V2_BASE = "https://api.etherscan.io/v2/api"
CHAIN_ID_MAP = {
    "1": "1",
    "56": "56",
    "137": "137",
    "42161": "42161",
    "8453": "8453",
    "sol": None
}

CHAIN_SPECIFIC_KEYS = {
    "1": "ETHERSCAN_API_KEY",
    "56": "BSCSCAN_API_KEY",
    "137": "POLYGONSCAN_API_KEY",
    "42161": "ARBISCAN_API_KEY",
    "8453": "BASESCAN_API_KEY",
}

SUSPICIOUS_SOURCE_PATTERNS = {
    "blacklist": [r"blacklist", r"isblacklisted", r"is_blacklisted", r"blocked", r"userblacklist", r"blacklist.*bot"],
    "mint": [r"mint", r"_mint", r"mintable", r"setmint", r"mintfunction"],
    "pause": [r"pause", r"paused", r"pausable", r"pauseTransfer", r"transferPausable"],
    "only_owner": [r"onlyowner", r"owner\(|msg\.sender == owner", r"require\(owner"],
    "tax_change": [r"setSellTax", r"setBuyTax", r"tax.*rate", r"setTax", r"changeTax"],
    "liquidity_control": [r"addLiquidity", r"removeLiquidity", r"unlockLiquidity", r"lockLiquidity", r"liquidity.*lock"],
    "transfer_control": [r"canTransfer", r"isTransferable", r"whitelist", r"isWhitelisted"],
    "renounce": [r"renounceOwnership", r"transferOwnership"],
}


def get_public_token_fallback(contract_address, chain_id="1"):
    """Use public, keyless metadata providers when GoPlus returns incomplete data."""
    chain_map = {
        "1": "ethereum",
        "56": "binance-smart-chain",
        "137": "polygon-pos",
        "42161": "arbitrum-one",
        "8453": "base",
    }
    platform = chain_map.get(chain_id, "ethereum")
    fallback = {}

    # CoinGecko public metadata endpoint (no API key required)
    try:
        gecko_url = f"https://api.coingecko.com/api/v3/coins/{platform}:{contract_address}"
        gecko_resp = requests.get(gecko_url, timeout=12)
        if gecko_resp.ok:
            gecko_data = gecko_resp.json()
            market = gecko_data.get("market_data") or {}
            fallback.update({
                "token_name": gecko_data.get("name") or gecko_data.get("id"),
                "token_symbol": gecko_data.get("symbol", "").upper(),
                "decimals": market.get("decimals") or gecko_data.get("detail_platforms", {}).get(platform, {}).get("decimal_place"),
                "price_usd": market.get("current_price", {}).get("usd"),
                "market_cap_usd": market.get("market_cap", {}).get("usd"),
                "total_volume_usd": market.get("total_volume", {}).get("usd"),
                "community_score": gecko_data.get("community_score"),
                "developer_score": gecko_data.get("developer_score"),
                "sentiment_votes_up": gecko_data.get("sentiment_votes_up_percentage"),
                "sentiment_votes_down": gecko_data.get("sentiment_votes_down_percentage"),
                "source": "coingecko-public",
            })
    except Exception as e:
        print(f"CoinGecko fallback error: {e}")

    # DexScreener public token endpoint (no API key required)
    if not fallback:
        try:
            ds_url = f"https://api.dexscreener.com/latest/dex/tokens/{chain_id}:{contract_address}"
            ds_resp = requests.get(ds_url, timeout=12)
            if ds_resp.ok:
                ds_data = ds_resp.json()
                pair = (ds_data.get("pairs") or [{}])[0]
                liquidity = pair.get("liquidity") or {}
                volume = pair.get("volume") or {}
                fallback.update({
                    "token_name": pair.get("baseToken", {}).get("name") or pair.get("baseToken", {}).get("symbol"),
                    "token_symbol": pair.get("baseToken", {}).get("symbol"),
                    "price_usd": pair.get("priceUsd"),
                    "pair_liquidity_usd": liquidity.get("usd"),
                    "pair_volume_usd_24h": volume.get("h24"),
                    "pair_fdv_usd": pair.get("fdv"),
                    "social_score": pair.get("socialScore"),
                    "source": "dexscreener-public",
                })
        except Exception as e:
            print(f"DexScreener fallback error: {e}")

    return fallback


def get_token_data(contract_address, chain_id="1"):
    """Fetch token data from GoPlus API; fall back to public keyless providers if needed."""
    try:
        url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}"
        params = {"contract_addresses": contract_address}
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("code") in ["0", "1", 0, 1] and "result" in data:
            result = data.get("result") or {}
            if not isinstance(result, dict):
                return get_public_token_fallback(contract_address, chain_id)
            token_data = result.get(contract_address) or result.get(contract_address.lower()) or {}
            if isinstance(token_data, dict) and token_data:
                fallback = get_public_token_fallback(contract_address, chain_id)
                return {"_data_source": "goplus", **fallback, **token_data}
        return get_public_token_fallback(contract_address, chain_id)
    except Exception as e:
        print(f"Error fetching GoPlus data: {str(e)}")
        return {"_data_source": "public-fallback", **get_public_token_fallback(contract_address, chain_id)}


def _load_cache():
    try:
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text())
    except Exception:
        return {}
    return {}


def _save_cache(cache):
    try:
        CACHE_FILE.write_text(json.dumps(cache))
    except Exception as e:
        print(f"Error saving cache: {e}")


def get_cached_analysis(key):
    cache = _load_cache()
    item = cache.get(key)
    if not item:
        return None
    value = item.get("value")
    if not isinstance(value, dict) or "risk_score" not in value:
        try:
            del cache[key]
            _save_cache(cache)
        except Exception:
            pass
        return None
    # TTL check
    if time.time() - item.get("ts", 0) > CACHE_TTL:
        try:
            del cache[key]
            _save_cache(cache)
        except Exception:
            pass
        return None
    return item.get("value")


def set_cached_analysis(key, value):
    cache = _load_cache()
    cache[key] = {"ts": time.time(), "value": value}
    _save_cache(cache)


def append_history(key, entry):
    try:
        history = {}
        if HISTORY_FILE.exists():
            history = json.loads(HISTORY_FILE.read_text())
        arr = history.get(key, [])
        arr.append(entry)
        # keep last 20
        history[key] = arr[-20:]
        HISTORY_FILE.write_text(json.dumps(history))
    except Exception as e:
        print(f"Error writing history: {e}")


def read_history(key):
    try:
        if HISTORY_FILE.exists():
            history = json.loads(HISTORY_FILE.read_text())
            return history.get(key, [])
    except Exception:
        pass
    return []


def get_etherscan_source(contract_address, chain_id="1"):
    """Fetch verified contract source code from BlockScan for EVM chains."""
    if not ETHERSCAN_API_KEY or chain_id == "sol":
        return None

    try:
        url = BLOCKSCAN_ENDPOINTS.get(chain_id, "https://api.etherscan.io/api")
        params = {
            "module": "contract",
            "action": "getsourcecode",
            "address": contract_address,
            "apikey": ETHERSCAN_API_KEY,
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "1" and data.get("result"):
            return data["result"][0]
    except Exception as e:
        print(f"Error fetching source code: {str(e)}")
    return None


def extract_source_flags(source_code):
    """Detect suspicious contract source patterns."""
    if not source_code:
        return []

    flags = []
    normalized = source_code.lower()

    for label, patterns in SUSPICIOUS_SOURCE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, normalized, flags=re.I):
                if label == "blacklist":
                    flags.append("Blacklist or bot-blocking logic detected")
                elif label == "mint":
                    flags.append("Minting functions detected")
                elif label == "pause":
                    flags.append("Pause / transfer control logic detected")
                elif label == "only_owner":
                    flags.append("Ownership-only function detected")
                elif label == "tax_change":
                    flags.append("Tax change function detected")
                elif label == "liquidity_control":
                    flags.append("Liquidity control or lock/unlock logic detected")
                elif label == "transfer_control":
                    flags.append("Transfer control / whitelisting logic detected")
                elif label == "renounce":
                    flags.append("Ownership transfer/renounce functionality detected")
                break
    return list(dict.fromkeys(flags))


def get_holder_info(contract_address, chain_id="1"):
    """Get top holders info from BlockScan for EVM chains, Solana data unavailable"""
    if chain_id == "sol" or not ETHERSCAN_API_KEY:
        return None

    try:
        url = BLOCKSCAN_ENDPOINTS.get(chain_id, "https://api.etherscan.io/api")
        # Holder list is only available for Ethereum
        if chain_id != "1":
            return None
            
        params = {
            "module": "token",
            "action": "tokenholderlist",
            "contractaddress": contract_address,
            "page": "1",
            "offset": "100",
            "apikey": ETHERSCAN_API_KEY,
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "1":
            return data.get("result", [])
    except Exception as e:
        print(f"Error fetching holder info: {str(e)}")
    return None


def get_recent_token_transfers(contract_address, chain_id="1", limit=100):
    """Fetch recent token transfers using explorer APIs for supported EVM chains."""
    if chain_id == "sol":
        return []

    v2_chain = CHAIN_ID_MAP.get(chain_id)
    if not v2_chain:
        return []

    key = ETHERSCAN_API_KEY
    if chain_id == "56":
        key = BSCSCAN_API_KEY or key
    elif chain_id == "137":
        key = POLYGONSCAN_API_KEY or key
    elif chain_id == "42161":
        key = ARBISCAN_API_KEY or key
    elif chain_id == "8453":
        key = BASESCAN_API_KEY or key

    if not key:
        return []

    # Prefer unified V2 endpoint when available; fallback to legacy chain-specific endpoint.
    try:
        url = ETHERSCAN_V2_BASE
        params = {
            "chainid": v2_chain,
            "module": "account",
            "action": "tokentx",
            "contractaddress": contract_address,
            "page": 1,
            "offset": limit,
            "sort": "desc",
            "apikey": key,
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "1":
            return data.get("result", [])
        # fallback if v2 restricted
        if data.get("message") and "deprecated" not in data.get("message").lower():
            return []
    except Exception as e:
        print(f"Etherscan V2 error fetching transfers: {e}")

    try:
        url = BLOCKSCAN_ENDPOINTS.get(chain_id, ETHERSCAN_V2_BASE)
        params = {
            "module": "account",
            "action": "tokentx",
            "contractaddress": contract_address,
            "page": 1,
            "offset": limit,
            "sort": "desc",
            "apikey": key,
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "1":
            return data.get("result", [])
    except Exception as e:
        print(f"Legacy endpoint error fetching transfers: {e}")

    return []


def summarize_token_transfers(transfers, owner_address=None, total_supply=None):
    """Summarize recent transfers for suspicious pattern detection."""
    if not transfers:
        return {
            "count": 0,
            "total_amount": 0,
            "largest_amount": 0,
            "largest_percent": 0,
            "suspicious": False,
            "suspicious_details": [],
            "owner_transfer_detected": False
        }

    amounts = []
    owner_address = owner_address.lower() if owner_address else None
    suspicious_details = []
    owner_transfer_detected = False

    for tx in transfers:
        try:
            amount = float(tx.get("value", 0))
        except Exception:
            continue
        amounts.append({
            "amount": amount,
            "from": (tx.get("from") or "").lower(),
            "to": (tx.get("to") or "").lower(),
            "hash": tx.get("hash")
        })

    total_amount = sum(item["amount"] for item in amounts) or 1
    largest = max(amounts, key=lambda item: item["amount"])
    largest_percent = (largest["amount"] / total_amount) * 100 if total_amount else 0

    suspicious = False
    if largest_percent >= 30:
        suspicious = True
        suspicious_details.append(f"Single transfer accounts for {largest_percent:.1f}% of recent transfer volume.")
    elif largest_percent >= 20:
        suspicious = True
        suspicious_details.append(f"Large transfer: {largest_percent:.1f}% of recent transfer volume.")

    if total_supply:
        try:
            supply_float = float(total_supply)
            if supply_float > 0 and largest["amount"] / supply_float >= 0.05:
                suspicious = True
                suspicious_details.append(f"One transfer is >=5% of total supply.")
        except Exception:
            pass

    if owner_address:
        if largest["from"] == owner_address or largest["to"] == owner_address:
            suspicious = True
            owner_transfer_detected = True
            suspicious_details.append("Largest transfer involves the owner address.")

    return {
        "count": len(amounts),
        "total_amount": total_amount,
        "largest_amount": largest["amount"],
        "largest_percent": round(largest_percent, 2),
        "suspicious": suspicious,
        "suspicious_details": suspicious_details,
        "owner_transfer_detected": owner_transfer_detected
    }


def calculate_holder_concentration(holders):
    """Calculate what % top 10 holders own"""
    if not holders:
        return None

    try:
        total_supply = float(holders[0].get("TokenHolderQuantity", 0))
        top_10_supply = sum(float(h.get("TokenHolderQuantity", 0)) for h in holders[:10])
        if total_supply <= 0:
            return None
        return round((top_10_supply / total_supply) * 100, 2)
    except Exception as e:
        print(f"Error calculating concentration: {str(e)}")
        return None


def parse_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def compute_data_completeness(token_data):
    """Measure how complete the token payload is for reliable scoring."""
    required_fields = ["buy_tax", "sell_tax", "lp_total_supply", "owner_address", "creator_address", "total_supply"]
    if not token_data:
        return 0.0, required_fields

    present = 0
    for field in required_fields:
        value = token_data.get(field)
        if value not in (None, "", "-", "None"):
            present += 1
    completeness = round((present / len(required_fields)) * 100, 1)
    return completeness, required_fields


def calculate_risk_score(data):
    score = 0
    token_symbol = str(data.get("token_symbol") or "").upper()
    market_cap_usd = parse_float(data.get("market_cap_usd", 0))
    pair_liquidity_usd = parse_float(data.get("pair_liquidity_usd", 0))
    community_score = parse_float(data.get("community_score", 0))
    developer_score = parse_float(data.get("developer_score", 0))
    token_name = str(data.get("token_name") or "").lower()
    stable_like = token_symbol in {"USDT", "USDC", "BUSD", "DAI", "USDP", "TUSD", "PYUSD", "FDUSD"} or any(word in token_name for word in ("stable", "usd", "tether", "usd coin", "dai"))
    completeness = float(data.get("data_completeness", 100.0) or 100.0)
    confidence = "high" if completeness >= 80 else "medium" if completeness >= 50 else "low"

    # Strong scam indicators are weighted more heavily, but stable-like assets still get a safety discount.
    if data.get("is_honeypot"):
        score += 35
    if data.get("cannot_sell_all"):
        score += 20
    if stable_like:
        score -= 20

    if data.get("is_blacklisted"):
        score += 8 if not stable_like else 0
    if data.get("is_mintable"):
        score += 8 if not stable_like else 0
    if data.get("owner_change_balance"):
        score += 8 if not stable_like else 0
    if data.get("transfer_pausable"):
        score += 8 if not stable_like else 0
    if data.get("slippage_modifiable"):
        score += 8 if not stable_like else 0
    if data.get("trading_cooldown"):
        score += 4 if not stable_like else 0
    if data.get("is_anti_whale"):
        score += 10 if confidence != "low" else 5
    if data.get("anti_whale_modifiable"):
        score += 8 if confidence != "low" else 4
    if data.get("can_take_back_ownership"):
        score += 10 if confidence != "low" else 5
    if data.get("hidden_owner"):
        score += 12 if confidence != "low" else 6

    buy_tax = parse_float(data.get("buy_tax", 0))
    sell_tax = parse_float(data.get("sell_tax", 0))
    if buy_tax > 25:
        score += 15
    elif buy_tax > 10:
        score += 8
    if sell_tax > 25:
        score += 15
    elif sell_tax > 10:
        score += 8

    if market_cap_usd > 0 and market_cap_usd < 50000:
        score += 4
    if pair_liquidity_usd > 0 and pair_liquidity_usd < 5000:
        score += 3
    if community_score > 0 and community_score < 30:
        score += 4
    if developer_score > 0 and developer_score < 30:
        score += 3

    if data.get("top_10_holder_percentage") is not None:
        top10 = data["top_10_holder_percentage"]
        if top10 > 80:
            score += 15
        elif top10 > 60:
            score += 10
        elif top10 > 50:
            score += 6

    creator_percent = parse_float(data.get("creator_percent", 0))
    if creator_percent >= 5:
        score += 10
    elif creator_percent >= 1:
        score += 6

    owner_percent = parse_float(data.get("owner_percent", 0))
    if owner_percent >= 0.5:
        score += 18
    elif owner_percent >= 0.1:
        score += 10
    elif owner_percent >= 0.01:
        score += 4

    transfer_summary = data.get("transfer_summary", {})
    if transfer_summary.get("suspicious"):
        score += 18 if confidence != "low" else 8
        if transfer_summary.get("owner_transfer_detected"):
            score += 5
        largest_percent = transfer_summary.get("largest_percent", 0)
        if largest_percent >= 40:
            score += 10
        elif largest_percent >= 25:
            score += 5

    source_flags = data.get("source_flags", [])
    if source_flags:
        score += min(12, 3 * len(source_flags))

    if confidence == "low":
        score = int(score * 0.8)
    elif confidence == "medium":
        score = int(score * 0.9)

    return max(0, min(100, int(score)))


def classify_risk(score):
    if score >= 80:
        return "SCAM"
    if score >= 60:
        return "RISKY"
    if score >= 35:
        return "WARNING"
    return "SAFE"


def analyze_token(contract_address, chain_id="1"):
    """Main analysis function - returns raw data"""
    cache_key = f"v{CACHE_VERSION}:{chain_id}:{contract_address.lower()}"
    cached = get_cached_analysis(cache_key)
    if cached:
        return cached

    token_data = get_token_data(contract_address, chain_id)
    external_data = get_public_token_fallback(contract_address, chain_id)
    token_data = {**external_data, **(token_data or {})}
    holders = get_holder_info(contract_address, chain_id) if chain_id == "1" else None
    holder_concentration = calculate_holder_concentration(holders)

    source_info = None
    source_flags = []
    if chain_id != "sol":
        source_info = get_etherscan_source(contract_address, chain_id)
        if source_info and source_info.get("SourceCode"):
            source_flags = extract_source_flags(source_info.get("SourceCode"))

    def safe_get(key, default=None):
        if not token_data:
            return default
        value = token_data.get(key, default)
        return value if value is not None and value != "" else default

    # detect data issues (missing important fields)
    data_issues = []
    completeness, required_fields = compute_data_completeness(token_data)
    public_source = token_data.get("source") in ("coingecko-public", "dexscreener-public") if isinstance(token_data, dict) else False
    if not token_data:
        data_issues.append("No GoPlus token data available")
    elif not public_source:
        for k in ("buy_tax", "sell_tax", "lp_total_supply"):
            if k not in token_data or token_data.get(k) in (None, "", "-"):
                data_issues.append(f"Missing {k} from GoPlus response")

    # transfer heuristics
    transfers = get_recent_token_transfers(contract_address, chain_id)
    transfer_summary = summarize_token_transfers(transfers, owner_address=analysis_owner if (analysis_owner := safe_get("owner_address")) else None, total_supply=safe_get("total_supply"))
    large_transfer_flag = transfer_summary["suspicious"]

    analysis_data = {
        "contract_address": contract_address,
        "chain": CHAIN_NAMES.get(chain_id, "Unknown"),
        "chain_id": chain_id,
        "token_name": safe_get("token_name", "Unknown"),
        "token_symbol": safe_get("token_symbol", "UNKNOWN"),
        "decimals": safe_get("decimals", "18"),

        "is_honeypot": safe_get("is_honeypot", "0") == "1",
        "is_anti_whale": safe_get("is_anti_whale", "0") == "1",
        "anti_whale_modifiable": safe_get("anti_whale_modifiable", "0") == "1",
        "can_take_back_ownership": safe_get("can_take_back_ownership", "0") == "1",
        "hidden_owner": safe_get("hidden_owner", "0") == "1",
        "owner_change_balance": safe_get("owner_change_balance", "0") == "1",
        "cannot_sell_all": safe_get("cannot_sell_all", "0") == "1",
        "slippage_modifiable": safe_get("slippage_modifiable", "0") == "1",
        "is_blacklisted": safe_get("is_blacklisted", "0") == "1",
        "is_whitelisted": safe_get("is_whitelisted", "0") == "1",
        "is_in_dex": safe_get("is_in_dex", "0") == "1",
        "is_proxy": safe_get("is_proxy", "0") == "1",
        "is_mintable": safe_get("is_mintable", "0") == "1",
        "owner_address": safe_get("owner_address"),
        "creator_address": safe_get("creator_address"),
        "creator_percent": safe_get("creator_percent"),
        "owner_percent": safe_get("owner_percent"),

        "total_supply": safe_get("total_supply"),
        "transfer_pausable": safe_get("transfer_pausable", "0") == "1",
        "buy_tax": safe_get("buy_tax"),
        "sell_tax": safe_get("sell_tax"),
        "liquidity_holder_count": safe_get("liquidity_holder_count"),
        "is_open_source": safe_get("is_open_source", "0") == "1",
        "trading_cooldown": safe_get("trading_cooldown", "0") == "1",
        "lp_holders": safe_get("lp_holders"),
        "lp_total_supply": safe_get("lp_total_supply"),
        "holders": holders,
        "top10_holder_rate": holder_concentration,

        "top_10_holder_percentage": holder_concentration,
        "market_cap_usd": safe_get("market_cap_usd"),
        "price_usd": safe_get("price_usd"),
        "pair_liquidity_usd": safe_get("pair_liquidity_usd"),
        "pair_volume_usd_24h": safe_get("pair_volume_usd_24h"),
        "community_score": safe_get("community_score"),
        "developer_score": safe_get("developer_score"),
        "social_score": safe_get("social_score"),
        "data_completeness": completeness,
        "required_fields": required_fields,
        "source_flags": source_flags,
        "source_verified": bool(source_info and source_info.get("SourceCode")),
        "source_contract_name": source_info.get("ContractName") if source_info else None,
        "source_proxy": source_info.get("Proxy") if source_info else None,
        "data_issues": data_issues,
        "recent_transfers_checked": transfer_summary["count"],
        "large_transfer_detected": large_transfer_flag,
        "transfer_summary": transfer_summary,
    }

    analysis_data["risk_score"] = calculate_risk_score(analysis_data)
    analysis_data["risk_level"] = classify_risk(analysis_data["risk_score"])
    analysis_data["confidence"] = "high" if analysis_data.get("data_completeness", 0) >= 80 else "medium" if analysis_data.get("data_completeness", 0) >= 50 else "low"

    # cache and history
    try:
        set_cached_analysis(cache_key, analysis_data)
        append_history(cache_key, {"ts": time.time(), "score": analysis_data["risk_score"]})
    except Exception:
        pass

    return analysis_data


def _safe_extract_ai_fields(text):
    """Best-effort extraction for malformed AI JSON responses."""
    cleaned = text.replace("```json", "").replace("```", "").strip()
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)

    result = {}
    for key in ("risk_score", "risk_level", "explanation", "recommendation"):
        match = re.search(rf'"{key}"\s*:\s*("(?:\\.|[^"\\])*"|\d+)', cleaned)
        if match:
            value = match.group(1)
            if key == "risk_score":
                try:
                    result[key] = int(value)
                except Exception:
                    result[key] = None
            else:
                result[key] = value.strip('"') if isinstance(value, str) else value
    return result


def _fallback_ai_report(analysis_data):
    score = int(analysis_data.get("risk_score", 0))
    level = analysis_data.get("risk_level", "SAFE")
    red_flags = sum(1 for key in ("is_honeypot", "cannot_sell_all", "is_blacklisted", "is_mintable", "slippage_modifiable", "owner_change_balance", "transfer_pausable") if analysis_data.get(key))
    if red_flags:
        explanation = f"The token shows {red_flags} notable risk indicators, so treat it cautiously until more data confirms safety."
        recommendation = "Verify the contract controls and holder distribution before trading."
    else:
        explanation = "The token currently looks low-risk based on the available metadata and transfer checks."
        recommendation = "Continue monitoring for owner or liquidity changes."
    return {
        "risk_score": score,
        "risk_level": level,
        "explanation": explanation,
        "recommendation": recommendation,
    }


def generate_ai_report(analysis_data):
    """Use Groq AI to generate plain English report"""
    if "error" in analysis_data:
        return {
            "risk_score": 0,
            "risk_level": "ERROR",
            "explanation": analysis_data["error"],
            "recommendation": "Invalid token address or chain"
        }

    red_flags = []
    green_flags = []

    if analysis_data["is_honeypot"]:
        red_flags.append("🔴 HONEYPOT: Cannot sell this token")
    if analysis_data["cannot_sell_all"]:
        red_flags.append("🔴 Cannot sell 100% of tokens")
    if analysis_data["is_blacklisted"]:
        red_flags.append("🔴 Blacklist function active")
    if analysis_data["is_mintable"]:
        red_flags.append("🔴 Owner can mint unlimited tokens")
    if analysis_data["slippage_modifiable"]:
        red_flags.append("🔴 Slippage can be changed by owner")
    if analysis_data["owner_change_balance"]:
        red_flags.append("🔴 Owner can change balances")
    if analysis_data["transfer_pausable"]:
        red_flags.append("🔴 Transfers can be paused")
    if analysis_data["trading_cooldown"]:
        red_flags.append("🔴 Trading cooldown enabled")

    if analysis_data["source_flags"]:
        red_flags.extend([f"🔴 {flag}" for flag in analysis_data["source_flags"]])

    buy_tax = parse_float(analysis_data["buy_tax"])
    sell_tax = parse_float(analysis_data["sell_tax"])
    if buy_tax > 25:
        red_flags.append(f"🔴 Very high buy tax: {buy_tax}%")
    if sell_tax > 25:
        red_flags.append(f"🔴 Very high sell tax: {sell_tax}%")

    if analysis_data["top_10_holder_percentage"]:
        top10 = analysis_data["top_10_holder_percentage"]
        if top10 > 80:
            red_flags.append(f"?? Top 10 holders own {top10}% - EXTREME concentration")
        elif top10 > 50:
            red_flags.append(f"?? Top 10 holders own {top10}% - High concentration")

    if analysis_data["is_open_source"]:
        green_flags.append("? Open source code")
    if not analysis_data["is_proxy"]:
        green_flags.append("? Not a proxy contract")
    if analysis_data["liquidity_holder_count"] != "0":
        green_flags.append("? Multiple liquidity holders")

    transfer_summary = analysis_data.get("transfer_summary", {})
    if transfer_summary.get("suspicious"):
        red_flags.append(f"🔴 Suspicious transfer pattern: {transfer_summary.get('largest_percent', 0)}% of recent transfer volume")
        if transfer_summary.get("owner_transfer_detected"):
            red_flags.append("🔴 Owner-related transfer detected in recent volume")

    prompt = f"""You are a crypto security expert. Analyze this token and provide a short risk assessment.

TOKEN: {analysis_data['token_name']} ({analysis_data['token_symbol']}) on {analysis_data['chain']}

RED FLAGS:
{chr(10).join(red_flags) if red_flags else 'None detected'}

GREEN FLAGS:
{chr(10).join(green_flags) if green_flags else 'None'}

Using the risk score {analysis_data['risk_score']} and level {analysis_data['risk_level']}, respond with valid JSON only:
{{"risk_score": <0-100>, "risk_level": "<SCAM|RISKY|WARNING|SAFE>", "explanation": "<2 sentences>", "recommendation": "<1 action>"}}"""

    try:
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            max_tokens=200,
        )
        response_text = completion.choices[0].message.content.strip()
        print(f"AI Response: {response_text}")

        cleaned = response_text.replace("```json", "").replace("```", "").strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        candidate = cleaned[start:end] if start != -1 and end > start else cleaned

        try:
            ai_report = json.loads(candidate)
        except Exception:
            ai_report = _safe_extract_ai_fields(candidate)

        if isinstance(ai_report, dict) and ai_report:
            ai_report["risk_score"] = int(analysis_data.get("risk_score", ai_report.get("risk_score", 0)))
            ai_report["risk_level"] = analysis_data.get("risk_level", ai_report.get("risk_level", "SAFE"))
            ai_report.setdefault("explanation", "Analysis completed")
            ai_report.setdefault("recommendation", "Always DYOR before investing")
            return ai_report
    except Exception as e:
        print(f"AI Error: {str(e)}")

    return _fallback_ai_report(analysis_data)


def full_analysis(contract_address, chain_id="1"):
    """Complete analysis: raw data + AI report"""
    raw_data = analyze_token(contract_address, chain_id)
    ai_report = generate_ai_report(raw_data)

    # attach recent history for frontend display
    try:
        cache_key = f"v{CACHE_VERSION}:{chain_id}:{contract_address.lower()}"
        raw_data["history"] = read_history(cache_key)
    except Exception:
        raw_data["history"] = []

    return {
        "raw_data": raw_data,
        "ai_report": ai_report
    }
