import httpx
import json
from app.config import settings
from shared.auth.jwt_tokens import create_access_token
from shared.auth.middleware import CurrentUser

def _get_headers(user: CurrentUser):
    token = create_access_token(user_id=user.id, email=user.email, role=user.role)
    return {"Authorization": f"Bearer {token}"}

async def fetch_procurement_summary(user: CurrentUser) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{settings.orders_api_base_url}/orders/summary/latest", headers=_get_headers(user))
            return json.dumps(resp.json()) if resp.status_code == 200 else json.dumps({"error": f"HTTP {resp.status_code}", "detail": resp.text})
    except Exception as e:
        return json.dumps({"error": str(e)})

async def fetch_my_requests(user: CurrentUser) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{settings.orders_api_base_url}/requests/", headers=_get_headers(user))
            return json.dumps(resp.json()) if resp.status_code == 200 else json.dumps({"error": f"HTTP {resp.status_code}", "detail": resp.text})
    except Exception as e:
        return json.dumps({"error": str(e)})

async def search_purchase_requests(user: CurrentUser, status: str = None, amount_min: float = None) -> str:
    params = {}
    if status:
        params["status"] = status
    if amount_min is not None:
        params["amount_min"] = amount_min
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{settings.orders_api_base_url}/requests/search", params=params, headers=_get_headers(user))
            return json.dumps(resp.json()) if resp.status_code == 200 else json.dumps({"error": f"HTTP {resp.status_code}", "detail": resp.text})
    except Exception as e:
        return json.dumps({"error": str(e)})

async def fetch_license_anomaly_summary(user: CurrentUser) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{settings.orders_api_base_url}/licenses/anomaly-summary", headers=_get_headers(user))
            return json.dumps(resp.json()) if resp.status_code == 200 else json.dumps({"error": f"HTTP {resp.status_code}", "detail": resp.text})
    except Exception as e:
        return json.dumps({"error": str(e)})

async def search_vendors(user: CurrentUser, query: str = "") -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{settings.risk_api_base_url}/vendors/", headers=_get_headers(user))
            if resp.status_code != 200:
                return json.dumps({"error": f"HTTP {resp.status_code}", "detail": resp.text})
            vendors = resp.json().get("data", [])
            if query:
                q = query.lower()
                vendors = [v for v in vendors if q in v.get("name", "").lower()]
            return json.dumps({"data": vendors[:5]})
    except Exception as e:
        return json.dumps({"error": str(e)})

async def fetch_vendor_risk(user: CurrentUser, vendor_id: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{settings.risk_api_base_url}/vendors/{vendor_id}/risk", headers=_get_headers(user))
            return json.dumps(resp.json()) if resp.status_code == 200 else json.dumps({"error": f"HTTP {resp.status_code}", "detail": resp.text})
    except Exception as e:
        return json.dumps({"error": str(e)})
