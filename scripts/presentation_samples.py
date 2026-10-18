#!/usr/bin/env python3
"""Collects one real input → output example per agent from the running
stack into docs/results/samples/ for the report's "Results and Evaluation"
sections (FR-12). Read-only: it picks existing demo items, creates nothing.

    GATEWAY=http://localhost:8080 python scripts/presentation_samples.py

Needs the stack running and the demo data seeded (./scripts/seed-demo-data.sh).
"""
import json
import os
import sys

import requests

GW = os.environ.get("GATEWAY", "http://localhost:8080") + "/api"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "results", "samples")
DROP = {"contract_text", "signature_image", "raw_text"}   # long or binary; not useful on a slide


def session(role):
    s = requests.Session()
    r = s.post(f"{GW}/auth/login", json={"email": f"{role}@demo.example.com", "password": "DemoPass123!"})
    r.raise_for_status()
    s.headers["Authorization"] = "Bearer " + r.json()["data"]["access_token"]
    return s


def trim(obj):
    if isinstance(obj, dict):
        return {k: ("<omitted>" if k in DROP else trim(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [trim(x) for x in obj[:10]]
    return obj


def save(name, data):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w") as f:
        json.dump(trim(data), f, indent=2, default=str)
    print("wrote", os.path.join("docs/results/samples", name))


def main():
    admin, fin = session("admin"), session("finance")

    # Document & Vendor: the newest classified invoice from a known vendor.
    docs = admin.get(f"{GW}/documents/?limit=100").json()["data"]
    doc = next((d for d in docs if d.get("document_type") == "invoice" and d.get("status") == "classified" and d.get("vendor_id")), None)
    if doc:
        detail = admin.get(f"{GW}/documents/{doc['id']}").json()["data"]
        save("document-vendor-agent.json", {
            "agent": "document-vendor-agent",
            "input": {"file": detail.get("original_filename"), "uploaded_by": detail.get("uploaded_by"), "source": detail.get("source")},
            "output": detail,
        })

    # Approval & Inventory: a request that has been decided, with its history.
    reqs = admin.get(f"{GW}/requests/?limit=200").json()["data"]
    req = next((r for r in reqs if r.get("approval_history")), None)
    if req:
        save("approval-inventory-agent.json", {
            "agent": "approval-inventory-agent",
            "input": {k: req.get(k) for k in ("request_type", "department", "amount", "currency", "items", "requested_by")},
            "output": admin.get(f"{GW}/requests/{req['id']}").json()["data"],
        })
    inv = admin.get(f"{GW}/inventory/").json()["data"]
    save("inventory-and-licences.json", {
        "agent": "approval-inventory-agent",
        "input": "GET /api/inventory/ (stock + licence usage)",
        "output": {"hardware": inv["hardware"], "licenses": inv["licenses"],
                   "anomaly_summary": admin.get(f"{GW}/inventory/licenses/anomaly-summary").json()["data"]},
    })

    # Contract & Risk: a signed contract with its certificate, and a vendor's risk.
    contracts = admin.get(f"{GW}/contracts/?limit=200").json()["data"]
    signed = next((c for c in contracts if c.get("status") == "signed"), None)
    if signed:
        save("contract-risk-agent-contract.json", {
            "agent": "contract-risk-agent",
            "input": {"purchase_request_id": signed.get("purchase_request_id"), "template": signed.get("template_used")},
            "output": admin.get(f"{GW}/contracts/{signed['id']}").json()["data"],
        })
    vendor_id = "11111111-1111-1111-1111-111111111111"
    save("contract-risk-agent-risk.json", {
        "agent": "contract-risk-agent",
        "input": {"vendor_id": vendor_id, "signals": fin.get(f"{GW}/vendors/{vendor_id}/risk-signals").json()["data"]},
        "output": fin.get(f"{GW}/vendors/{vendor_id}/risk").json()["data"],
    })

    # Notification: the newest sent notification.
    log = admin.get(f"{GW}/notifications/log?limit=200").json()["data"]
    sent = next((n for n in log if n.get("status") == "sent" and n.get("event_type") == "approval.requested"),
                next((n for n in log if n.get("status") == "sent"), log[0] if log else None))
    if sent:
        save("notification-agent.json", {"agent": "notification-agent",
                                          "input": {"event_type": sent.get("event_type")}, "output": sent})

    # Auth & business rules: one rule with its definition.
    rules = [r for g in admin.get(f"{GW}/admin/business-rules").json()["data"].values() for r in g]
    save("auth-service-rule.json", {"agent": "auth-service", "input": "GET /api/admin/business-rules",
                                    "output": next(r for r in rules if r["rule_key"] == "approval.spend_tiers")})


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        sys.exit(f"Is the stack running at {GW}? {e}")
