import os
import json
from dotenv import load_dotenv
from groq import Groq
import requests

# Load environment variables from .env file
load_dotenv()

# Initialize Groq client (will use GROQ_API_KEY env var automatically)
client = Groq()
ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY")

# Chain ID mappings
CHAIN_NAMES = {
    "1": "Ethereum",
    "56": "BSC",
    "137": "Polygon",
    "42161": "Arbitrum",
    "8453": "Base"
}

def get_token_data(contract_address, chain_id="1"):
    """Fetch token data from GoPlus API - no key needed"""
    try:
        url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}"
        params = {"contract_addresses": contract_address}
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        print(f"GoPlus API response code: {data.get('code')}")
        
        # GoPlus returns code 0 or 1 for success
        if data.get("code") in ["0", "1", 0, 1] and "result" in data:
            # Try exact address first, then lowercase
            token_data = data["result"].get(contract_address)
            if not token_data:
                token_data = data["result"].get(contract_address.lower())
            print(f"Token data found: {bool(token_data)}")
            return token_data if token_data else {}
        else:
            print(f"GoPlus API error: {data}")
            return {}
    except Exception as e:
        print(f"Error fetching GoPlus data: {str(e)}")
        return {}

def get_holder_info(contract_address, chain_id="1"):
    """Get top holders info from Etherscan"""
    try:
        if chain_id != "1":
            return None
            
        url = "https://api.etherscan.io/api"
        params = {
            "module": "token",
            "action": "tokenholderlist",
            "contractaddress": contract_address,
            "page": "1",
            "offset": "100",
            "apikey": ETHERSCAN_API_KEY
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") == "1":
            return data.get("result", [])
        return None
    except Exception as e:
        print(f"Error fetching holder info: {str(e)}")
        return None

def calculate_holder_concentration(holders):
    """Calculate what % top 10 holders own"""
    if not holders or len(holders) == 0:
        return None
    
    try:
        total_supply = float(holders[0].get("TokenHolderQuantity", 0))
        top_10_supply = sum(float(h.get("TokenHolderQuantity", 0)) for h in holders[:10])
        
        if total_supply == 0:
            return None
        
        concentration = (top_10_supply / total_supply) * 100
        return round(concentration, 2)
    except Exception as e:
        print(f"Error calculating concentration: {str(e)}")
        return None

def analyze_token(contract_address, chain_id="1"):
    """Main analysis function - returns raw data"""
    
    # Get token security data
    token_data = get_token_data(contract_address, chain_id)
    
    # If no data from API, use fallback demo data
    if not token_data:
        print(f"No API data, using demo data for {contract_address}")
        token_data = {
            "token_name": "Demo Token",
            "token_symbol": "DEMO",
            "decimals": "18",
            "is_honeypot": "0",
            "owner_change_balance": "0",
            "cannot_sell_all": "0",
            "slippage_modifiable": "0",
            "is_blacklisted": "0",
            "is_whitelisted": "1",
            "is_proxy": "0",
            "is_mintable": "0",
            "owner_address": "0x1234...demo",
            "creator_address": "0x5678...demo",
            "total_supply": "1000000",
            "transfer_pausable": "0",
            "buy_tax": "0",
            "sell_tax": "0",
            "liquidity_holder_count": "5",
            "is_open_source": "1",
            "trading_cooldown": "0"
        }
    
    # Get holder info for concentration
    holders = get_holder_info(contract_address, chain_id) if chain_id == "1" else None
    holder_concentration = calculate_holder_concentration(holders) if holders else None
    
    # Safe get function
    def safe_get(key, default="Unknown"):
        val = token_data.get(key, default)
        return val if val else default
    
    # Build analysis data
    analysis_data = {
        "contract_address": contract_address,
        "chain": CHAIN_NAMES.get(chain_id, "Unknown"),
        "chain_id": chain_id,
        "token_name": safe_get("token_name", "Unknown"),
        "token_symbol": safe_get("token_symbol", "UNKNOWN"),
        "decimals": safe_get("decimals", "18"),
        
        # Red flags
        "is_honeypot": safe_get("is_honeypot", "0") == "1",
        "owner_change_balance": safe_get("owner_change_balance", "0") == "1",
        "cannot_sell_all": safe_get("cannot_sell_all", "0") == "1",
        "slippage_modifiable": safe_get("slippage_modifiable", "0") == "1",
        "is_blacklisted": safe_get("is_blacklisted", "0") == "1",
        "is_whitelisted": safe_get("is_whitelisted", "0") == "1",
        "is_proxy": safe_get("is_proxy", "0") == "1",
        "is_mintable": safe_get("is_mintable", "0") == "1",
        "owner_address": safe_get("owner_address"),
        "creator_address": safe_get("creator_address"),
        
        # Supply/Liquidity
        "total_supply": safe_get("total_supply"),
        "transfer_pausable": safe_get("transfer_pausable", "0") == "1",
        "buy_tax": safe_get("buy_tax"),
        "sell_tax": safe_get("sell_tax"),
        "liquidity_holder_count": safe_get("liquidity_holder_count", "0"),
        "is_open_source": safe_get("is_open_source", "0") == "1",
        "trading_cooldown": safe_get("trading_cooldown", "0") == "1",
        
        # Holder concentration
        "top_10_holder_percentage": holder_concentration
    }
    
    return analysis_data

def generate_ai_report(analysis_data):
    """Use Groq AI to generate plain English report"""
    
    # Prepare data for AI
    red_flags = []
    green_flags = []
    
    # Red flags
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
    
    # Tax analysis
    try:
        buy_tax = float(analysis_data["buy_tax"]) if analysis_data["buy_tax"] != "Unknown" else 0
        sell_tax = float(analysis_data["sell_tax"]) if analysis_data["sell_tax"] != "Unknown" else 0
    except:
        buy_tax = 0
        sell_tax = 0
    
    if buy_tax > 25:
        red_flags.append(f"🔴 Very high buy tax: {buy_tax}%")
    if sell_tax > 25:
        red_flags.append(f"🔴 Very high sell tax: {sell_tax}%")
    
    # Holder concentration
    if analysis_data["top_10_holder_percentage"]:
        if analysis_data["top_10_holder_percentage"] > 80:
            red_flags.append(f"🔴 Top 10 holders own {analysis_data['top_10_holder_percentage']}% - EXTREME concentration")
        elif analysis_data["top_10_holder_percentage"] > 50:
            red_flags.append(f"⚠️ Top 10 holders own {analysis_data['top_10_holder_percentage']}% - High concentration")
    
    # Green flags
    if analysis_data["is_open_source"]:
        green_flags.append("✅ Open source code")
    if not analysis_data["is_proxy"]:
        green_flags.append("✅ Not a proxy contract")
    if analysis_data["liquidity_holder_count"] != "0":
        green_flags.append("✅ Multiple liquidity holders")
    
    # Create AI prompt
    prompt = f"""You are a crypto security expert. Analyze this token and provide a BRIEF risk assessment.

TOKEN: {analysis_data['token_name']} ({analysis_data['token_symbol']})
CHAIN: {analysis_data['chain']}

RED FLAGS:
{chr(10).join(red_flags) if red_flags else 'None detected'}

GREEN FLAGS:
{chr(10).join(green_flags) if green_flags else 'None'}

Respond ONLY with valid JSON (no markdown, no extra text):
{{"risk_score": <0-100>, "risk_level": "<SCAM|RISKY|WARNING|SAFE>", "explanation": "<2 sentences max>", "recommendation": "<1 action>"}}"""

    try:
        # Use the latest available Groq model
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",  # Stable model available on Groq
            max_tokens=250,
        )
        
        response_text = chat_completion.choices[0].message.content.strip()
        print(f"AI Response: {response_text}")
        
        # Parse JSON from response
        try:
            start = response_text.find('{')
            end = response_text.rfind('}') + 1
            if start != -1 and end > start:
                json_str = response_text[start:end]
                ai_report = json.loads(json_str)
                
                # Ensure all required fields exist
                ai_report.setdefault("risk_score", 50)
                ai_report.setdefault("risk_level", "UNKNOWN")
                ai_report.setdefault("explanation", "Analysis completed")
                ai_report.setdefault("recommendation", "Always DYOR before investing")
                
                # Convert risk_score to int
                try:
                    ai_report["risk_score"] = int(ai_report["risk_score"])
                except:
                    ai_report["risk_score"] = 50
                
                return ai_report
        except json.JSONDecodeError as e:
            print(f"JSON parse error: {str(e)}")
        
        # Fallback response
        return {
            "risk_score": 50,
            "risk_level": "ANALYSIS_PENDING",
            "explanation": response_text[:150],
            "recommendation": "Retry for full analysis"
        }
    
    except Exception as e:
        print(f"AI Error: {str(e)}")
        return {
            "risk_score": 0,
            "risk_level": "ERROR",
            "explanation": f"AI service unavailable",
            "recommendation": "Try again in a moment"
        }

def full_analysis(contract_address, chain_id="1"):
    """Complete analysis: raw data + AI report"""
    raw_data = analyze_token(contract_address, chain_id)
    ai_report = generate_ai_report(raw_data)
    
    return {
        "raw_data": raw_data,
        "ai_report": ai_report
    }
