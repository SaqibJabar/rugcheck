import json
import os
import time
from datetime import datetime

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from groq import Groq


load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
GUMROAD_API_TOKEN = "r0Zp2trgcwjNcXhdzEUv9mByFDBFZYzHivl-uN1NDV0"
GUMROAD_PRODUCT_ID = "mbdpon"

if not GROQ_API_KEY or not ETHERSCAN_API_KEY:
    raise RuntimeError("Missing required API keys: GROQ_API_KEY and ETHERSCAN_API_KEY must be set")


app = FastAPI()
groq_client = Groq(api_key=GROQ_API_KEY)

license_cache = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _cache_get(key: str):
    cached = license_cache.get(key)
    if not cached:
        return None
    if cached.get("expires", 0) <= time.time():
        license_cache.pop(key, None)
        return None
    return cached


async def validate_gumroad_license(license_key: str) -> bool:
    if not license_key or len(license_key.strip()) < 5:
        return False

    license_key = license_key.strip()
    cache_key = f"license_{license_key}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return bool(cached.get("valid"))

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://api.gumroad.com/v2/licenses/verify",
                data={
                    "product_id": GUMROAD_PRODUCT_ID,
                    "license_key": license_key,
                },
                headers={
                    "Authorization": f"Bearer {GUMROAD_API_TOKEN}",
                },
            )
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        print(f"Gumroad license validation failed: {exc}")
        license_cache[cache_key] = {"valid": False, "expires": time.time() + 300}
        return False

    is_valid = bool(data.get("success"))
    license_cache[cache_key] = {"valid": is_valid, "expires": time.time() + 3600}
    return is_valid


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


def _extract_token_data(goplus_data: dict, contract_address: str) -> dict:
    result = goplus_data.get("result") or {}
    if not isinstance(result, dict):
        return {}

    return (
        result.get(contract_address)
        or result.get(contract_address.lower())
        or result.get(contract_address.upper())
        or next(iter(result.values()), {})
    )


def _extract_json_object(text: str) -> dict:
    cleaned = text.replace("```json", "").replace("```", "").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start != -1 and end > start:
        cleaned = cleaned[start:end]
    return json.loads(cleaned)


def _fallback_ai_report(token_data: dict) -> dict:
    score = 0
    if str(token_data.get("is_honeypot", "0")) == "1":
        score += 40
    if str(token_data.get("is_mintable", "0")) == "1":
        score += 15
    if str(token_data.get("is_blacklisted", "0")) == "1":
        score += 12
    if str(token_data.get("can_take_back_ownership", "0")) == "1":
        score += 12
    if str(token_data.get("owner_change_balance", "0")) == "1":
        score += 12

    for field in ("buy_tax", "sell_tax"):
        try:
            tax = float(token_data.get(field) or 0)
        except (TypeError, ValueError):
            tax = 0
        if tax > 25:
            score += 15
        elif tax > 10:
            score += 8

    score = min(score, 100)
    if score >= 70:
        recommendation = "AVOID"
    elif score >= 35:
        recommendation = "CAUTION"
    else:
        recommendation = "SAFE"

    return {
        "risk_score": score,
        "explanation": "AI response could not be parsed, so this fallback score uses the strongest available on-chain risk flags.",
        "recommendation": recommendation,
    }


def _build_analysis_prompt(contract_address: str, chain_id: str, token_data: dict) -> str:
    return f"""You are a blockchain security analyst. Analyze this cryptocurrency token for rug pull risk.

Contract address: {contract_address}
Chain ID: {chain_id}

Token metrics from GoPlus:
{json.dumps(token_data, indent=2)}

Focus on mint functions, ownership control, hidden owner risk, proxy risk, honeypot behavior, trading restrictions, blacklist/whitelist controls, buy/sell taxes, LP holders, liquidity values, holder concentration, creator/owner percentages, and any fields that indicate sell restrictions or balance manipulation.

Return valid JSON only with exactly these keys:
{{
  "risk_score": <integer from 0 to 100>,
  "explanation": "<short explanation>",
  "recommendation": "<AVOID|CAUTION|SAFE>"
}}"""


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.get("/api/status")
async def status():
    return {
        "status": "operational",
        "groq": bool(GROQ_API_KEY),
        "etherscan": bool(ETHERSCAN_API_KEY),
        "gumroad": bool(GUMROAD_API_TOKEN and GUMROAD_PRODUCT_ID),
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/api/analyze")
async def analyze(request: Request):
    start_time = time.monotonic()

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    contract_address = str(body.get("contract_address", "")).strip()
    chain_id = str(body.get("chain_id", "1")).strip() or "1"
    license_key = str(body.get("license_key", "")).strip()

    if not contract_address:
        raise HTTPException(status_code=400, detail="Contract address required")

    client_ip = _client_ip(request)
    is_licensed = False

    if license_key:
        is_licensed = await validate_gumroad_license(license_key)
        if not is_licensed:
            raise HTTPException(status_code=403, detail="invalid_license")
    else:
        session_key = f"free_{client_ip}"
        if _cache_get(session_key):
            raise HTTPException(status_code=403, detail="free_limit_reached")
        license_cache[session_key] = {"valid": True, "expires": time.time() + 86400}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}",
                params={"contract_addresses": contract_address},
            )
            response.raise_for_status()
            goplus_data = response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GoPlus API failed: {exc}")

    token_data = _extract_token_data(goplus_data, contract_address)
    if not token_data:
        raise HTTPException(status_code=404, detail="Token not found")

    prompt = _build_analysis_prompt(contract_address, chain_id, token_data)
    try:
        completion = groq_client.chat.completions.create(
            model="mixtral-8x7b-32768",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
        )
        ai_text = completion.choices[0].message.content.strip()
        ai_report = _extract_json_object(ai_text)
    except Exception as exc:
        print(f"Groq analysis failed: {exc}")
        ai_report = _fallback_ai_report(token_data)

    return {
        "raw_data": token_data,
        "ai_report": ai_report,
        "analysis_time_seconds": round(time.monotonic() - start_time, 2),
        "is_licensed": is_licensed,
    }


@app.get("/")
async def serve_frontend():
    return FileResponse("index.html", media_type="text/html")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
