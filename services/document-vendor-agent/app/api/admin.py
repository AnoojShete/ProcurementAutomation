from fastapi import APIRouter, Depends
from pydantic import BaseModel
from shared.auth.middleware import RequireRole

router = APIRouter(dependencies=[Depends(RequireRole("admin"))])

class LiveModeUpdate(BaseModel):
    enabled: bool

# Shared mock state for demonstration
QUOTAS = {
    "gstin_live": {"calls_used": 15, "calls_limit": 20, "remaining": 5},
    "opencorporates": {"calls_used": 50, "calls_limit": 100, "remaining": 50}
}
LIVE_MODE_ENABLED = True

@router.get("/live-mode")
async def get_live_mode():
    return {
        "enabled": LIVE_MODE_ENABLED,
        "quotas": [{"api_name": k, **v} for k, v in QUOTAS.items()]
    }

@router.patch("/live-mode")
async def update_live_mode(req: LiveModeUpdate):
    global LIVE_MODE_ENABLED
    
    # Auto-safety cutoff
    for api, usage in QUOTAS.items():
        if usage["calls_used"] >= usage["calls_limit"] * 0.8:
            LIVE_MODE_ENABLED = False
            print(f"WARN: Live mode auto-disabled due to {api} quota hitting safety margin.")
            return {
                "enabled": False, 
                "message": "Auto-safety cutoff triggered. Live mode disabled.",
                "quotas": [{"api_name": k, **v} for k, v in QUOTAS.items()]
            }

    LIVE_MODE_ENABLED = req.enabled
    return {
        "enabled": LIVE_MODE_ENABLED,
        "quotas": [{"api_name": k, **v} for k, v in QUOTAS.items()]
    }