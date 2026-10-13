import asyncio
import httpx
import sys
from shared.auth.jwt_tokens import create_access_token

BASE_URL = "http://localhost:8006"

# Create test tokens directly matching your platform's demo roles
ADMIN_TOKEN = create_access_token(
    user_id="00000000-0000-0000-0000-000000000001",
    email="admin@demo.example.com",
    role="admin"
)
REQUESTER_TOKEN = create_access_token(
    user_id="00000000-0000-0000-0000-000000000002",
    email="requester@demo.example.com",
    role="requester"
)

async def test_health():
    print("\n[TEST 1] Checking chatbot-agent health...")
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE_URL}/health")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        print("  ✓ Chatbot service is healthy.")

async def test_admin_procurement_summary():
    print("\n[TEST 2] Testing E2E Tool: 'get_procurement_summary' as Admin...")
    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(
            f"{BASE_URL}/chat/",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            json={"message": "Can you give me a summary of our procurement status and pending approvals?"}
        )
        assert r.status_code == 200, f"Failed: {r.status_code} - {r.text}"
        data = r.json()
        print(f"  ✓ Assistant Reply:\n{data.get('message')}\n")

async def test_search_and_vendor_risk():
    print("\n[TEST 3] Testing Multi-Tool Chaining: search_vendors -> get_vendor_risk...")
    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(
            f"{BASE_URL}/chat/",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            json={"message": "Check the risk score and status of any vendor you find."}
        )
        assert r.status_code == 200, f"Failed: {r.status_code} - {r.text}"
        data = r.json()
        print(f"  ✓ Assistant Reply:\n{data.get('message')}\n")

async def test_rbac_requester_boundary():
    print("\n[TEST 4] Testing RBAC Boundary as Requester...")
    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(
            f"{BASE_URL}/chat/",
            headers={"Authorization": f"Bearer {REQUESTER_TOKEN}"},
            json={"message": "Show me the secret risk scores of all vendors."}
        )
        assert r.status_code == 200, f"Failed: {r.status_code} - {r.text}"
        data = r.json()
        print(f"  ✓ Assistant Reply:\n{data.get('message')}\n")

async def main():
    try:
        await test_health()
        await test_admin_procurement_summary()
        await test_search_and_vendor_risk()
        await test_rbac_requester_boundary()
        print("\n==========================================")
        print(" ALL CHATBOT E2E TESTS PASSED SUCCESSFULLY ")
        print("==========================================")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
