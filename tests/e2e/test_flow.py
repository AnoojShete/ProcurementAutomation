import requests
import time
import os
import hmac
import hashlib
import json

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8080/api")
ESIGN_SECRET = os.getenv("ESIGN_WEBHOOK_SECRET", "dev-esign-secret-change-me")

def test_full_procurement_flow():
    print("1. Logging in as requester...")
    resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "requester@demo.example.com", "password": "DemoPass123!"})
    assert resp.status_code == 200, "Failed to login as requester"
    req_token = resp.json()["data"]["access_token"]
    req_headers = {"Authorization": f"Bearer {req_token}"}

    print("2. Uploading synthetic invoice...")
    invoice_path = os.path.join(os.path.dirname(__file__), "../../data/synthetic-invoices/00_invoice_hpindiasalespvtltd_INV-2026-00001.pdf")
    with open(invoice_path, "rb") as invoice_file:
        files = {'file': ('invoice.pdf', invoice_file, 'application/pdf')}
        resp = requests.post(f"{BASE_URL}/documents/upload", files=files, headers=req_headers)
    assert resp.status_code in [200, 202], "Failed to upload document"

    print("3. Creating purchase request...")
    resp = requests.post(f"{BASE_URL}/requests/", json={
        "request_type": "hardware",
        "department": "Engineering",
        "amount": 15000,
        "currency": "INR"
    }, headers=req_headers)
    assert resp.status_code in [200, 201], "Failed to create request"
    req_id = resp.json()["data"]["id"]

    print("4. Logging in as approver...")
    resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "approver@demo.example.com", "password": "DemoPass123!"})
    app_token = resp.json()["data"]["access_token"]
    app_headers = {"Authorization": f"Bearer {app_token}"}

    print("5. Approving request...")
    resp = requests.post(f"{BASE_URL}/requests/{req_id}/approve", json={"decided_by": "dept_manager"}, headers=app_headers)
    assert resp.status_code == 200, "Failed to approve request"

    print("6. Polling for workflow completion...")
    for _ in range(15):
        resp = requests.get(f"{BASE_URL}/requests/{req_id}", headers=app_headers)
        if resp.json()["data"]["status"] == "approved":
            break
        time.sleep(1)
    assert resp.json()["data"]["status"] == "approved", "Workflow did not mark request as approved"

    print("7. Generating Contract...")
    resp = requests.post(f"{BASE_URL}/contracts/generate", json={
        "purchase_request_id": req_id,
        "template_name": "hardware_purchase"
    }, headers=app_headers)
    assert resp.status_code == 200, "Failed to generate contract"
    contract_id = resp.json()["data"]["id"]

    print("8. Testing E-Sign Webhook Callback with Signature Verification & Replay Protection...")
    payload = {
        "provider_event_id": f"evt_{time.time()}",
        "contract_id": contract_id,
        "signed_by": "signer@demo.example.com",
        "signed_at": "2026-09-23T00:00:00+00:00",
    }
    unsigned_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["signature"] = hmac.new(ESIGN_SECRET.encode(), unsigned_payload.encode(), hashlib.sha256).hexdigest()
    
    # 8a. Test invalid signature rejection (fraud check)
    bad_payload = dict(payload, signature="invalid-signature-hash")
    bad_resp = requests.post(f"{BASE_URL}/webhooks/esign", json=bad_payload)
    assert bad_resp.status_code == 401, "Webhook accepted forged signature"

    # 8b. Real webhook delivery with valid HMAC-SHA256 signature
    resp = requests.post(f"{BASE_URL}/webhooks/esign", json=payload)
    assert resp.status_code == 200, f"Webhook rejected valid signature: {resp.text}"
    assert resp.json()["data"]["status"] == "signed"

    # 8c. Test replay protection with identical provider_event_id
    replay_resp = requests.post(f"{BASE_URL}/webhooks/esign", json=payload)
    assert replay_resp.status_code == 200
    assert replay_resp.json()["data"]["status"] == "already_processed", "Webhook failed replay protection check"
    
    print("9. Testing mid-test Business Rule Mutation via Admin API...")
    resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "admin@demo.example.com", "password": "DemoPass123!"})
    assert resp.status_code == 200, "Failed to login as admin"
    admin_token = resp.json()["data"]["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    patch_resp = requests.patch(
        f"{BASE_URL}/admin/business-rules/license.anomaly_watch_threshold",
        json={"new_value": 0.55, "justification": "E2E threshold mutation test without restart"},
        headers=admin_headers,
    )
    assert patch_resp.status_code == 200, f"Failed to patch business rule: {patch_resp.text}"
    assert patch_resp.json()["data"]["current_value"] == 0.55

    print("10. Verifying Business Rule History Audit Trail...")
    hist_resp = requests.get(
        f"{BASE_URL}/admin/business-rules/history?rule_key=license.anomaly_watch_threshold",
        headers=admin_headers,
    )
    assert hist_resp.status_code == 200, f"Failed to get history: {hist_resp.text}"
    history_items = hist_resp.json()["data"]
    assert len(history_items) > 0
    assert history_items[0]["justification"] == "E2E threshold mutation test without restart"

    print("11. Restoring Business Rule to Default...")
    reset_resp = requests.post(
        f"{BASE_URL}/admin/business-rules/license.anomaly_watch_threshold/reset",
        json={"justification": "Restoring default after E2E test"},
        headers=admin_headers,
    )
    assert reset_resp.status_code == 200, f"Failed to reset business rule: {reset_resp.text}"

    print("E2E Validation Passed. Pipeline and Business Rules flow end-to-end successfully.")

if __name__ == "__main__":
    test_full_procurement_flow()