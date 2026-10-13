import httpx
import json
from app.config import settings
from shared.auth.jwt_tokens import create_access_token

async def fetch_procurement_summary(user_id: str) -> str:
    """Uses a service token to hit the internal orders API."""
    token = create_access_token(user_id="chatbot-agent", email="bot@internal", role="service")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.orders_api_base_url}/orders/summary/latest",
                headers={"Authorization": f"Bearer {token}"}
            )
            if resp.status_code == 200:
                return json.dumps(resp.json().get("data", {}))
            return json.dumps({"error": f"API returned {resp.status_code}"})
    except Exception as e:
        return json.dumps({"error": str(e)})