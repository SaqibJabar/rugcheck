import time
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel
from analyzer import full_analysis
import os
from typing import Optional, Any, Dict

# Load environment variables
load_dotenv()


app = FastAPI()

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AnalysisRequest(BaseModel):
    contract_address: str
    chain_id: str = "1"
    license_key: Optional[str] = None

class AnalysisResponse(BaseModel):
    raw_data: Dict[str, Any]
    ai_report: Dict[str, Any]
    analysis_time_seconds: float
    is_licensed: bool

# Valid license keys for paid version
VALID_LICENSES = set()

def verify_license(key):
    """Check if a license key is valid"""
    return key in VALID_LICENSES

@app.get("/")
async def root():
    """Serve the frontend"""
    return FileResponse("index.html", media_type="text/html")

@app.post("/api/analyze")
async def analyze(request: AnalysisRequest):
    """
    Analyze a token for rug pull risk.
    
    First analysis is FREE.
    Subsequent analyses require a license key (paid via Gumroad).
    """
    
    # Validate contract address format
    if not request.contract_address or len(request.contract_address) < 5:
        raise HTTPException(status_code=400, detail="Invalid contract address")
    
    # Validate chain ID
    valid_chains = ["1", "56", "sol", "137", "42161", "8453"]
    if request.chain_id not in valid_chains:
        raise HTTPException(status_code=400, detail="Invalid chain ID. Supported: Ethereum (1), BSC (56), Solana (sol), Polygon (137), Arbitrum (42161), Base (8453)")
    
    # Run analysis
    start_time = time.monotonic()
    try:
        result = full_analysis(request.contract_address, request.chain_id)
        analysis_time_seconds = round(time.monotonic() - start_time, 2)

        raw_data = result.get("raw_data", {})
        if raw_data.get("error"):
            raise HTTPException(status_code=502, detail=raw_data["error"])

        return {
            "raw_data": raw_data,
            "ai_report": result.get("ai_report", {}),
            "analysis_time_seconds": analysis_time_seconds,
            "is_licensed": False
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

@app.post("/api/verify-license")
async def verify_license_endpoint(request: dict):
    """Verify if a license key is valid"""
    key = request.get("license_key")
    
    if not key:
        return {"valid": False}
    
    # For now, any non-empty key is "valid" - you'll update this after Gumroad setup
    # Pattern: tokens from Gumroad will be stored in VALID_LICENSES set
    return {"valid": key in VALID_LICENSES}

@app.get("/health")
async def health():
    """Health check"""
    return {"status": "alive", "service": "rugcheck-api"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
