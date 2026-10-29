"""Five FICTIONAL vendors that land in different risk bands, for the demo.

They are not real companies (names, GSTINs and domains are made up; the
domains end in .example, so the website and e-mail probes use their
simulated results). Every fact is recorded through the same endpoints a
finance user would use, so the scorecard computes the band itself:

    vendor                       expected   what drives it
    Tarangini Office Supplies    Low        AA rating, 22 years old, good ratings
    Velmora Cloud Services       Low        ISO 27001 expired, 2 years old, average ratings
    Kestrel Freight Systems      Medium     no certification, BB+ rating, <1 year old, poor ratings, 1 incident
    Orvane Components            High       GSTIN registered to another company, defaulted rating,
                                            no certification, very poor ratings, 3 incidents
    Zagros Trade Link            High       registered in Iran (prohibited country: override)

    python scripts/seed_demo_risk_vendors.py            # create (or reuse) and score
    python scripts/seed_demo_risk_vendors.py --rescore  # score the existing ones again
"""
import argparse
import os
import sys

import requests

GW = os.getenv("GATEWAY", "http://localhost:8080") + "/api"
PASSWORD = "DemoPass123!"
NOTE = "Fictional demo vendor (not a real company)."
_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin(state: str, pan: str) -> str:
    """A well-formed GSTIN (state + PAN + entity 1 + Z + check digit)."""
    body = f"{state}{pan}1Z"
    total, factor = 0, 1
    for ch in body:
        product = factor * _CHARS.index(ch)
        total += product // 36 + product % 36
        factor = 2 if factor == 1 else 1
    return body + _CHARS[(36 - total % 36) % 36]


def gst(title):
    return {"evidence_type": "gst_certificate", "title": title, "notes": NOTE}


def rating(agency, grade):
    return {"evidence_type": "credit_rating", "title": f"{agency} {grade} (demo)", "notes": NOTE,
            "metadata": {"agency": agency, "grade": grade}}


def incorporated(on):
    return {"evidence_type": "certificate_of_incorporation", "title": f"Incorporated {on} (demo)",
            "valid_from": on, "notes": NOTE}


VENDORS = [
    {"profile": {"name": "Tarangini Office Supplies Pvt Ltd", "country": "IN", "inherent_tier": "moderate",
                 "category": "Office supplies", "website": "https://tarangini-supplies.example",
                 "gstin": gstin("29", "AAICT4821K")},
     "evidence": [gst("Tarangini Office Supplies Pvt Ltd"), rating("CRISIL", "AA"), incorporated("2004-03-15")],
     "ratings": [5, 4, 5], "incidents": []},
    {"profile": {"name": "Velmora Cloud Services Pvt Ltd", "country": "IN", "inherent_tier": "high",
                 "category": "Cloud hosting", "website": "https://velmora-cloud.example",
                 "gstin": gstin("27", "AAJCV7310M")},
     "evidence": [gst("Velmora Cloud Services Pvt Ltd"), rating("ICRA", "BBB-"), incorporated("2024-06-10"),
                  {"evidence_type": "iso27001", "title": "ISO/IEC 27001:2022 (demo, lapsed)", "notes": NOTE,
                   "valid_until": "2026-03-31", "scope_covers_service": True}],
     "ratings": [4, 3, 4, 3], "incidents": []},
    {"profile": {"name": "Kestrel Freight Systems Pvt Ltd", "country": "IN", "inherent_tier": "critical",
                 "category": "Logistics", "website": "https://kestrel-freight.example",
                 "gstin": gstin("33", "AAKCK5092P")},
     "evidence": [gst("Kestrel Freight Systems Pvt Ltd"), rating("CARE", "BB+"), incorporated("2026-01-15")],
     "ratings": [2, 2, 1, 2, 2],
     "incidents": ["Shipment of 40 laptops delayed 19 days; no tracking updates for a week."]},
    {"profile": {"name": "Orvane Components Pvt Ltd", "country": "IN", "inherent_tier": "critical",
                 "category": "Hardware components", "website": "https://orvane-components.example",
                 "gstin": gstin("07", "AAHCO6644D")},
     # The GST registry names a different company for this GSTIN (identity mismatch).
     "evidence": [gst("Ravindra Metal Traders"), rating("CRISIL", "D"), incorporated("2026-05-20")],
     "ratings": [1, 2, 1, 2],
     "incidents": ["Delivered refurbished drives invoiced as new; 120 units returned.",
                   "Invoice raised twice for the same purchase order; caught at three-way match.",
                   "Support line unreachable for 5 working days during an outage."]},
    {"profile": {"name": "Zagros Trade Link Co", "country": "IR", "inherent_tier": "high",
                 "category": "Industrial spares", "website": "https://zagros-tradelink.example"},
     "evidence": [incorporated("2011-09-01")], "ratings": [], "incidents": []},
]


def login(role):
    r = requests.post(f"{GW}/auth/login", json={"email": f"{role}@demo.example.com", "password": PASSWORD})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


def call(method, path, headers, ok=(200, 201, 202), **kw):
    r = requests.request(method, f"{GW}{path}", headers=headers, timeout=120, **kw)
    if r.status_code not in ok:
        sys.exit(f"{method} {path} -> {r.status_code} {r.text[:300]}")
    return r.json().get("data")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rescore", action="store_true")
    args = ap.parse_args()
    admin, finance, approver = login("admin"), login("finance"), login("approver")
    existing = {v["name"]: v["id"] for v in call("GET", "/vendors/", admin, params={"limit": 1000})}
    for spec in VENDORS:
        name = spec["profile"]["name"]
        vendor_id = existing.get(name)
        if vendor_id is None and not args.rescore:
            vendor_id = call("POST", "/vendors/onboard", admin,
                             json={**spec["profile"], "confirm": ["lookalike", "no_gstin"],
                                   "no_gstin_reason": "Foreign vendor" if spec["profile"]["country"] != "IN" else None})["id"]
            for ev in spec["evidence"]:
                call("POST", f"/vendors/{vendor_id}/evidence", finance, json=ev)
            for i, stars in enumerate(spec["ratings"]):
                call("POST", f"/vendors/{vendor_id}/feedback", approver,
                     json={"overall_rating": stars, "dimension": ("service_quality", "delivery", "support")[i % 3]})
            for text in spec["incidents"]:
                call("POST", f"/vendors/{vendor_id}/incidents", finance, json={"description": text})
        if vendor_id is None:
            print(f"{name}: not seeded yet, skipped")
            continue
        call("POST", f"/vendors/{vendor_id}/screen-sanctions", admin)
        call("POST", f"/vendors/{vendor_id}/risk/reevaluate", admin)
        risk = call("GET", f"/vendors/{vendor_id}/risk", admin)
        print(f"{name:36} {risk['final_band']:7} {risk['rating_status']:12} {risk['total_points']:>3} pts  "
              f"score {round((risk.get('risk_score') or 0) * 100):>3}/100")


if __name__ == "__main__":
    main()
