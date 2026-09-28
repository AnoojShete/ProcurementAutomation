#!/usr/bin/env python3
"""Simulates an e-signature provider's webhook callback."""
import argparse
import hashlib
import hmac
import json
import uuid
import urllib.request
from datetime import datetime, timezone

def main():
    parser = argparse.ArgumentParser(description="Simulate an e-sign webhook callback")
    parser.add_argument("contract_id", help="UUID of the contract to sign")
    parser.add_argument("--secret", default="dev-esign-secret-change-me", help="HMAC secret")
    parser.add_argument("--url", default="http://localhost:8080/api/webhooks/esign", help="Webhook URL")
    args = parser.parse_args()

    payload = {
        "provider_event_id": str(uuid.uuid4()),
        "contract_id": args.contract_id,
        "signed_by": "simulated_signer@example.com",
        "signed_at": datetime.now(timezone.utc).isoformat(),
    }

    # Generate HMAC signature
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(args.secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    
    # Add signature to the request payload
    payload["signature"] = signature

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(args.url, data=data, headers={"Content-Type": "application/json"})
    
    try:
        with urllib.request.urlopen(req) as response:
            print(f"Success! Status: {response.status}")
            print(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"Failed! HTTP Error: {e.code}")
        print(e.read().decode("utf-8"))
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
