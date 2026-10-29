"""Seed three real Indian IT vendors with public, sourced facts and score them.

Every fact below comes from a public source (listed next to it); nothing is
invented. Bank details are left out on purpose: a real account number is not
public, so the bank check is "not applicable (no bank details)".

    python scripts/seed_real_vendors.py            # create (or reuse) + score once
    python scripts/seed_real_vendors.py --rescore  # score the existing ones again

Re-running adds any evidence below that a vendor doesn't have yet, so new
evidence reaches vendors seeded earlier. The sanctions decisions below were
taken by the team on 29 Oct 2026 (fuzzy name hits, different companies) and
are recorded through the same endpoint a reviewer uses in the app.

Scoring reads the breach history from the local Have I Been Pwned catalogue,
so re-running it makes no HIBP calls. Needs the stack and live mode
(turned on here) for the website and e-mail probes.
"""
import argparse
import os
import sys

import requests

GW = os.getenv("GATEWAY", "http://localhost:8080") + "/api"
PASSWORD = "DemoPass123!"

VENDORS = [
    {
        "profile": {
            "name": "Infosys Limited", "country": "IN", "inherent_tier": "critical",
            "category": "IT services", "website": "https://www.infosys.com",
            # knowyourgst.com (aggregator of the GST portal), Bengaluru, registered 01/07/2017
            "gstin": "29AAACI4798L1ZU",
        },
        "evidence": [
            {"evidence_type": "gst_certificate", "title": "Infosys Limited",
             "notes": "GSTIN 29AAACI4798L1ZU, Karnataka (knowyourgst.com; confirm on gst.gov.in)"},
            # CRISIL rating rationale, 26 June 2026: Long Term Debt Crisil AAA/Stable (reaffirmed)
            {"evidence_type": "credit_rating", "title": "CRISIL AAA/Stable (26 Jun 2026)",
             "metadata": {"agency": "CRISIL", "grade": "AAA",
                          "source": "https://www.crisil.com/mnt/winshare/Ratings/RatingList/RatingDocs/InfosysLimited_June 26_ 2026_RR_398312.html"}},
            # MCA: CIN L85110KA1981PLC013115, incorporated 2 July 1981 (RoC Bangalore)
            {"evidence_type": "certificate_of_incorporation", "title": "CIN L85110KA1981PLC013115",
             "valid_from": "1981-07-02"},
            # infosys.com/about/esg/certifications.html: ISO 27001:2022, IND.24.16155/IS/U/A, valid to 17 Dec 2027
            {"evidence_type": "iso27001", "title": "ISO/IEC 27001:2022 (IND.24.16155/IS/U/A)",
             "valid_until": "2027-12-17", "scope_covers_service": True},
        ],
        # Only candidate: InfoRos (Russia), 71 %.
        "sanctions_clearance": "Not the listed entity. InfoRos is a Russian company; Infosys Limited is "
                               "incorporated in India (CIN L85110KA1981PLC013115, GSTIN 29AAACI4798L1ZU). "
                               "Only a 71 % fuzzy match on part of the name.",
    },
    {
        "profile": {
            "name": "Redington Limited", "country": "IN", "inherent_tier": "moderate",
            "category": "IT hardware distribution", "website": "https://www.redingtongroup.com",
            # knowyourgst.com, Chennai (Redington Tower, Saraswathy Nagar)
            "gstin": "33AABCR0347P1ZA",
        },
        "evidence": [
            {"evidence_type": "gst_certificate", "title": "Redington Limited",
             "notes": "GSTIN 33AABCR0347P1ZA, Tamil Nadu (knowyourgst.com; confirm on gst.gov.in)"},
            # CRISIL rating rationale, 27 May 2026: Crisil AA+/Stable/Crisil A1+ (reaffirmed)
            {"evidence_type": "credit_rating", "title": "CRISIL AA+/Stable (27 May 2026)",
             "metadata": {"agency": "CRISIL", "grade": "AA+",
                          "source": "https://www.crisil.com/mnt/winshare/Ratings/RatingList/RatingDocs/RedingtonLimited_May 27_ 2026_RR_396203.html"}},
            # MCA: CIN L52599TN1961PLC028758, incorporated 2 May 1961 (RoC Chennai)
            {"evidence_type": "certificate_of_incorporation", "title": "CIN L52599TN1961PLC028758",
             "valid_from": "1961-05-02"},
        ],
        # Candidates, all 70-74 %: Carlington Petrochem FZCO (UAE), Redin Exchange (Turkey),
        # Kingston Holding (France), JSC Freight One (Russia).
        "sanctions_clearance": "Not a listed entity. The candidates (Carlington Petrochem FZCO, UAE; Redin "
                               "Exchange, Turkey; Kingston Holding, France; JSC Freight One, Russia) are "
                               "different companies in other countries; Redington Limited is incorporated in "
                               "India (CIN L52599TN1961PLC028758, GSTIN 33AABCR0347P1ZA). Fuzzy matches of 70-74 %.",
    },
    {
        "profile": {
            "name": "Hathway Cable and Datacom Limited", "country": "IN", "inherent_tier": "high",
            "category": "Internet connectivity", "website": "https://www.hathway.com",
            # knowyourgst.com, Mumbai (Interface Building No. 11, Link Road)
            "gstin": "27AAACC6814B1Z4",
        },
        "evidence": [
            {"evidence_type": "gst_certificate", "title": "Hathway Cable & Datacom Limited",
             "notes": "GSTIN 27AAACC6814B1Z4, Maharashtra (knowyourgst.com; confirm on gst.gov.in)"},
            # MCA: CIN L64204MH1959PLC011421, incorporated 7 August 1959 (RoC Mumbai)
            {"evidence_type": "certificate_of_incorporation", "title": "CIN L64204MH1959PLC011421",
             "valid_from": "1959-08-07"},
            # No credit rating: India Ratings withdrew it in March 2022 at the company's
            # request (no debt), so finance scores the audited statements instead
            # (docs/business-rules.md, "Financial statement score").
            # Audited consolidated results, year ended 31 Mar 2026, filed 17 Apr 2026
            # (BSE 533162); auditor Nayan Parikh & Co., unmodified opinion. Rs crore.
            {"evidence_type": "financial_statement",
             "title": "Audited consolidated results, FY 2025-26 (filed 17 Apr 2026)",
             "valid_from": "2026-03-31",
             "notes": "Statement of assets and liabilities and results, pages 8-9 of the filing",
             "metadata": {"total_equity": 4466.74, "profit_after_tax": 82.24,
                          "current_assets": 2762.99, "current_liabilities": 689.61,
                          "total_borrowings": 0.47,   # non-current 0.01 + current 0.46
                          "unit": "Rs crore", "period_end": "2026-03-31",
                          "audit_opinion": "unmodified", "going_concern_doubt": False,
                          "source": "https://www.hathway.com/documents/Financial%20Results/25/Q4/Financial%20Results%20FY2025-26%20Q4.pdf"}},
        ],
    },
]


def login(role):
    r = requests.post(f"{GW}/auth/login", json={"email": f"{role}@demo.example.com", "password": PASSWORD})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


def call(method, path, headers, **kw):
    r = requests.request(method, f"{GW}{path}", headers=headers, timeout=120, **kw)
    if r.status_code >= 400:
        sys.exit(f"{method} {path} -> {r.status_code} {r.text[:300]}")
    return r.json().get("data")


def find_vendor(headers, name):
    rows = call("GET", "/vendors/", headers, params={"limit": 500})
    rows = rows.get("items", rows) if isinstance(rows, dict) else rows
    return next((v["id"] for v in rows if v.get("name") == name), None)


def summary(headers, vendor_id, name):
    exp = call("GET", f"/vendors/{vendor_id}/risk/explanation", headers)
    print(f"\n{name}: {exp['final_band']} ({exp['rating_status']}), {exp['total_points']}/100\n  {exp.get('headline')}")
    for r in exp.get("signals", []):
        print(f"   {r['rule_id']:9} {r['status']:20} +{r['points']:<3} {r['reason_text'][:120]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rescore", action="store_true", help="only score the existing vendors again")
    args = ap.parse_args()
    admin = login("admin")
    call("PATCH", "/admin/live-mode", admin, json={"enabled": True})
    for spec in VENDORS:
        name = spec["profile"]["name"]
        vendor_id = find_vendor(admin, name)
        if vendor_id is None:
            if args.rescore:
                print(f"{name}: not seeded yet, skipped")
                continue
            vendor_id = call("POST", "/vendors/onboard", admin,
                             json={**spec["profile"], "confirm": ["lookalike"]})["id"]
        have = {(e["evidence_type"], e["title"]) for e in call("GET", f"/vendors/{vendor_id}/evidence", admin)}
        for ev in spec["evidence"]:
            if (ev["evidence_type"], ev["title"]) not in have:
                call("POST", f"/vendors/{vendor_id}/evidence", admin, json=ev)
                print(f"{name}: added {ev['evidence_type']} ({ev['title']})")
        screening = call("POST", f"/vendors/{vendor_id}/screen-sanctions", admin)["screening"]
        if screening["status"] == "potential_match" and spec.get("sanctions_clearance"):
            call("POST", f"/vendors/{vendor_id}/clear-sanctions-flag", admin,
                 json={"justification": spec["sanctions_clearance"]})
            print(f"{name}: sanctions candidates cleared (not the listed entities)")
        call("POST", f"/vendors/{vendor_id}/risk/reevaluate", admin)
        summary(admin, vendor_id, name)


if __name__ == "__main__":
    main()
