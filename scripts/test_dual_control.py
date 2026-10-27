"""Test reviewer separation and review endpoints on target vendor e4b1673e-3b1c-4fdc-82d3-fa86c90feba5."""
import asyncio
import httpx
from fastapi import FastAPI
from app.api import vendors
from shared.auth import get_current_user
from shared.auth.middleware import CurrentUser

TARGET_VENDOR_ID = "e4b1673e-3b1c-4fdc-82d3-fa86c90feba5"


async def main():
    app = FastAPI()
    app.state.kafka_producer = None
    app.include_router(vendors.router, prefix="/vendors")

    # Current user context switcher
    current_user_obj = CurrentUser(id="u-onboarder", email="onboarder@example.com", role="admin")
    app.dependency_overrides[get_current_user] = lambda: current_user_obj

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Breach Review Dual Control
        print("--- 1. Testing Breach Review Dual Control ---")
        # As onboarder -> 403
        current_user_obj = CurrentUser(id="u-onboarder", email="onboarder@example.com", role="admin")
        resp = await client.post(
            f"/vendors/{TARGET_VENDOR_ID}/risk/breach-review",
            json={
                "breach_name": "ADDA",
                "decision": "same_entity",
                "notes": "Same company based on registration details",
            },
        )
        print("Onboarder breach review status (expected 403):", resp.status_code)
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

        # As independent reviewer -> 200
        current_user_obj = CurrentUser(id="u-reviewer", email="independent_reviewer@example.com", role="admin")
        resp = await client.post(
            f"/vendors/{TARGET_VENDOR_ID}/risk/breach-review",
            json={
                "breach_name": "ADDA",
                "decision": "same_entity",
                "notes": "Verified domain match adda.io and legal entity",
            },
        )
        print("Independent reviewer breach review status (expected 200):", resp.status_code)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()["data"]
        print("Recorded review decision:", data.get("decision"))

        # 2. GST Review Dual Control
        print("\n--- 2. Testing GST Review Dual Control ---")
        # As onboarder -> 403
        current_user_obj = CurrentUser(id="u-onboarder", email="onboarder@example.com", role="admin")
        resp = await client.post(
            f"/vendors/{TARGET_VENDOR_ID}/risk/gst-review",
            json={
                "decision": "confirmed",
                "notes": "Verified trade name matching on GST portal",
            },
        )
        print("Onboarder GST review status (expected 403):", resp.status_code)
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

        # As independent reviewer -> 200
        current_user_obj = CurrentUser(id="u-reviewer", email="independent_reviewer@example.com", role="admin")
        resp = await client.post(
            f"/vendors/{TARGET_VENDOR_ID}/risk/gst-review",
            json={
                "decision": "confirmed",
                "notes": "Verified trade name matching on GST portal certificate",
            },
        )
        print("Independent reviewer GST review status (expected 200):", resp.status_code)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

        # 3. Cert Waiver Dual Control
        print("\n--- 3. Testing Cert Waiver Dual Control ---")
        # As onboarder -> 403
        current_user_obj = CurrentUser(id="u-onboarder", email="onboarder@example.com", role="admin")
        resp = await client.post(
            f"/vendors/{TARGET_VENDOR_ID}/risk/cert-waiver",
            json={
                "certification_name": "ISO 27001",
                "rationale": "Waiver granted for 90 days pending audit",
                "valid_months": 3,
            },
        )
        print("Onboarder cert waiver status (expected 403):", resp.status_code)
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

        # As independent reviewer -> 200
        current_user_obj = CurrentUser(id="u-reviewer", email="independent_reviewer@example.com", role="admin")
        resp = await client.post(
            f"/vendors/{TARGET_VENDOR_ID}/risk/cert-waiver",
            json={
                "certification_name": "ISO 27001",
                "rationale": "Waiver granted for 90 days pending audit",
                "valid_months": 3,
            },
        )
        print("Independent reviewer cert waiver status (expected 200):", resp.status_code)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

        print("\nAll Dual Control & Reviewer Separation tests PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
