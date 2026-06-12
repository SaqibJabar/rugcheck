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
        
        if data.get("code") == "0" and "result" in data:
            token_data = data["result"].get(contract_address, {})
            return token_data
        else:
            return None
    except Exception as e:
        print(f"Error fetching GoPlus data: {e}")
        return None

def get_holder_info(contract_address, chain_id="1"):
    """Get top holders info from Etherscan"""
    try:
        if chain_id == "1":  # Ethereum
            url = "https://api.etherscan.io/api"
        else:
            return None  # For simplicity, only Etherscan for now
        
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
        print(f"Error fetching holder info: {e}")
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
    except:
        return None

def analyze_token(contract_address, chain_id="1"):
    """Main analysis function - returns raw data"""
    
    # Get token security data
    token_data = get_token_data(contract_address, chain_id)
    
    if not token_data:
                # Use demo data for testing
                print(f"Using demo data for {contract_address}")
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
        else:
            return {
                "error": "Could not fetch token data. Check address and chain.",
                "contract_address": contract_address,
                "chain_id": chain_id
            }
    
    # Get holder info for concentration
    holders = get_holder_info(contract_address, chain_id) if chain_id == "1" else None
    holder_concentration = calculate_holder_concentration(holders) if holders else None
    
    # Extract relevant fields
    analysis_data = {
        "contract_address": contract_address,
        "chain": CHAIN_NAMES.get(chain_id, "Unknown"),
        "chain_id": chain_id,
        "token_name": token_data.get("token_name", "Unknown"),
        "token_symbol": token_data.get("token_symbol", "Unknown"),
        "decimals": token_data.get("decimals", "Unknown"),
        
        # Red flags
        "is_honeypot": token_data.get("is_honeypot") == "1",
        "owner_change_balance": token_data.get("owner_change_balance") == "1",
        "cannot_sell_all": token_data.get("cannot_sell_all") == "1",
        "slippage_modifiable": token_data.get("slippage_modifiable") == "1",
        "is_blacklisted": token_data.get("is_blacklisted") == "1",
        "is_whitelisted": token_data.get("is_whitelisted") == "1",
        "is_proxy": token_data.get("is_proxy") == "1",
        "is_mintable": token_data.get("is_mintable") == "1",
        "owner_address": token_data.get("owner_address", "Not found"),
        "creator_address": token_data.get("creator_address", "Not found"),
        
        # Supply/Liquidity
        "total_supply": token_data.get("total_supply", "Unknown"),
        "transfer_pausable": token_data.get("transfer_pausable") == "1",
        "buy_tax": token_data.get("buy_tax", "Unknown"),
        "sell_tax": token_data.get("sell_tax", "Unknown"),
        "liquidity_holder_count": token_data.get("liquidity_holder_count", "0"),
        "is_open_source": token_data.get("is_open_source") == "1",
        "trading_cooldown": token_data.get("trading_cooldown") == "1",
        
        # Holder concentration
        "top_10_holder_percentage": holder_concentration
    }
    
    return analysis_data

def generate_ai_report(analysis_data):
    """Use Groq AI to generate plain English report"""
    
    if "error" in analysis_data:
        return {
            "risk_score": 0,
            "risk_level": "ERROR",
            "explanation": analysis_data["error"],
            "recommendation": "Invalid token address or chain"
        }
    
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
    
    buy_tax = float(analysis_data["buy_tax"]) if analysis_data["buy_tax"] != "Unknown" else 0
    sell_tax = float(analysis_data["sell_tax"]) if analysis_data["sell_tax"] != "Unknown" else 0
    
    if buy_tax > 25:
        red_flags.append(f"🔴 Very high buy tax: {buy_tax}%")
    if sell_tax > 25:
        red_flags.append(f"🔴 Very high sell tax: {sell_tax}%")
    
    if analysis_data["top_10_holder_percentage"] and analysis_data["top_10_holder_percentage"] > 80:
        red_flags.append(f"🔴 Top 10 holders own {analysis_data['top_10_holder_percentage']}% - extremely centralized")
    elif analysis_data["top_10_holder_percentage"] and analysis_data["top_10_holder_percentage"] > 50:
        red_flags.append(f"⚠️ Top 10 holders own {analysis_data['top_10_holder_percentage']}% - high concentration")
    
    # Green flags
    if analysis_data["is_open_source"]:
        green_flags.append("✅ Open source code")
    if not analysis_data["is_proxy"]:
        green_flags.append("✅ Not a proxy contract")
    if analysis_data["liquidity_holder_count"] != "0":
        green_flags.append("✅ Multiple liquidity holders")
    
    # Create AI prompt
    prompt = f"""You are a crypto security expert. Analyze this token and provide a risk assessment.

TOKEN DATA:
Name: {analysis_data['token_name']}
Symbol: {analysis_data['token_symbol']}
Chain: {analysis_data['chain']}
Owner: {analysis_data['owner_address']}

RED FLAGS DETECTED:
{chr(10).join(red_flags) if red_flags else "None"}

GREEN FLAGS:
{chr(10).join(green_flags) if green_flags else "None"}

Based on this analysis:
1. Give a RISK SCORE (0-100, where 100 is certain rug pull)
2. Classify as SCAM / RISKY / WARNING / SAFE
3. Provide a 2-sentence plain English explanation
4. Give 1 specific recommendation

Format your response as JSON with keys: risk_score, risk_level, explanation, recommendation
Keep it brief and serious."""

    try:
        message = client.messages.create(
            model="mixtral-8x7b-32768",  # Free Groq model
            max_tokens=300,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        response_text = message.content[0].text
        
        # Try to parse as JSON
        try:
            # Find JSON in response
            start = response_text.find('{')
            end = response_text.rfind('}') + 1
            if start != -1 and end > start:
                json_str = response_text[start:end]
                ai_report = json.loads(json_str)
            else:
                ai_report = {
                    "risk_score": 50,
                    "risk_level": "UNABLE_TO_PARSE",
                    "explanation": response_text,
                    "recommendation": "Unable to parse AI response"
                }
        except json.JSONDecodeError:
            ai_report = {
                "risk_score": 50,
                "risk_level": "ANALYSIS_ERROR",
                "explanation": response_text,
                "recommendation": "Retry analysis"
            }
        
        return ai_report
    
    except Exception as e:
        return {
            "risk_score": 0,
            "risk_level": "ERROR",
            "explanation": f"AI analysis failed: {str(e)}",
            "recommendation": "Try again later"
        }

def full_analysis(contract_address, chain_id="1"):
    """Complete analysis: raw data + AI report"""
    raw_data = analyze_token(contract_address, chain_id)
    ai_report = generate_ai_report(raw_data)
    
    return {
        "raw_data": raw_data,
        "ai_report": ai_report
    }
