"""GST and TDS compliance (feature expansion Phase 4), end to end through
the gateway against the running stack:

    python tests/e2e/gst_flow.py

  tax check   a correct intra-state e-invoice passes and its signed QR
              verifies; IGST on an intra-state supply is flagged (review +
              invoice.tax_flagged); a USD SaaS invoice is reverse charge with
              GST payable; a QR whose total was altered, or signed with
              another key, fails
  TDS         the vendor's tax profile; booking the matched invoice keeps TDS
              (194J(a), 2% of the amount before GST) and the net payable
  MSME        the invoice of a small enterprise has a 45-day deadline;
              recording it paid clears it
  GSTR-2B     an upload matches our invoice, lists ours that is missing and
              the 2B entry we don't have
  rules       the seven Phase 4 rules are seeded and validated

Needs the stack in development mode (the demo e-invoice key) and pyjwt +
cryptography on the host (tests/e2e/requirements.txt). Data stays behind like
every e2e suite's.
"""
import hashlib
import hmac
import io
import json
import os
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "document-vendor-agent", "scripts"))
from gst_invoice_lib import build_pdf, demo_signing_key, gst_invoice  # noqa: E402

GW = os.getenv("GATEWAY", "http://localhost:8080") + "/api"
PASSWORD = "DemoPass123!"
ESIGN_SECRET = os.getenv("ESIGN_WEBHOOK_SECRET", "dev-esign-secret-change-me")
RUN = uuid.uuid4().hex[:6].upper()
BUYER = "29AAACA1234B1ZE"
TODAY = date.today()
results = []
H = {}


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  [{detail}]" if detail and not cond else ""))
    return bool(cond)


def step(title):
    print(f"\n── {title}")


def login(role):
    for _ in range(5):
        r = requests.post(f"{GW}/auth/login", json={"email": f"{role}@demo.example.com", "password": PASSWORD})
        if r.status_code != 429:
            break
        time.sleep(15)
    check(f"login {role}", r.status_code == 200, r.text[:120])
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


def poll(fn, until, timeout=90, interval=2):
    deadline, last = time.time() + timeout, None
    while time.time() < deadline:
        last = fn()
        if until(last):
            return last
        time.sleep(interval)
    return last


def upload(name, pdf):
    r = requests.post(f"{GW}/documents/upload", headers=H["finance"], files={"file": (name, pdf, "application/pdf")})
    if r.status_code != 201:
        check(f"upload {name}", False, f"{r.status_code} {r.text[:150]}")
        return None
    doc_id = r.json()["data"]["document_id"]
    return poll(lambda: requests.get(f"{GW}/documents/{doc_id}", headers=H["finance"]).json()["data"],
                lambda d: d["status"] not in ("pending", "processing"), timeout=180)


def get_req(rid):
    return requests.get(f"{GW}/requests/{rid}", headers=H["admin"]).json()["data"]


def approve_and_sign(rid):
    for role in ("approver", "finance"):
        if get_req(rid)["status"] != "pending_approval":
            break
        requests.post(f"{GW}/requests/{rid}/approve", headers=H[role], json={"comments": "gst e2e"})
        time.sleep(2)
    poll(lambda: get_req(rid), lambda r: r["status"] != "pending_approval", timeout=30)
    c = poll(lambda: next((c for c in requests.get(f"{GW}/contracts/?limit=200", headers=H["admin"]).json()["data"]
                           if c["purchase_request_id"] == rid), None),
             lambda c: c is not None and c["status"] == "pending_signature", timeout=60)
    if not c:
        return None
    body = {"provider_event_id": f"evt-gst-{RUN}", "contract_id": c["id"], "signed_by": "vendor@e2e.example",
            "signed_at": datetime.now(timezone.utc).isoformat()}
    sig = hmac.new(ESIGN_SECRET.encode(), json.dumps(body, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
    requests.post(f"{GW}/webhooks/esign", json=dict(body, signature=sig))
    return poll(lambda: get_req(rid), lambda r: r["status"] == "ordered", timeout=30)


SELLER = {"name": f"Kaveri Infotech {RUN} Pvt Ltd", "gstin": "29AABCD5678E1ZG"}
SUPPORT = [{"name": f"IT support retainer {RUN}", "hsn": "998313", "quantity": 1, "unit_price": 100000.0}]


def tables_and_roles():
    step("Rate tables and who may see them")
    rates = requests.get(f"{GW}/gst/rates", headers=H["finance"])
    check("GST rate table seeded (HSN/SAC for IT)", rates.status_code == 200 and len(rates.json()["data"]) >= 15,
          rates.text[:120])
    sections = requests.get(f"{GW}/tds/sections", headers=H["finance"])
    check("TDS sections seeded", sections.status_code == 200 and {"194C", "194J(a)", "194J(b)", "194Q"}
          <= {s["section"] for s in sections.json()["data"]}, sections.text[:120])
    check("requester can't see GST or TDS -> 403", requests.get(f"{GW}/gst/rates", headers=H["requester"]).status_code == 403
          and requests.get(f"{GW}/tds/sections", headers=H["requester"]).status_code == 403)
    r = requests.put(f"{GW}/gst/rates/8471", headers=H["approver"],
                     json={"code": "8471", "description": "x", "category": "hardware", "rate_pct": 5})
    check("approver can't change a GST rate -> 403", r.status_code == 403, str(r.status_code))


def correct_invoice_with_tds():
    step("Correct intra-state e-invoice, booked with TDS")
    # The vendor: created from its quote, like every vendor seen first on a document.
    q_lines, _, _ = gst_invoice(SELLER, BUYER, f"QT-{RUN}", TODAY, SUPPORT)
    q_lines = [ln.replace("TAX INVOICE", "QUOTATION").replace("Invoice Number", "Quote Number")
               .replace("Invoice Date", "Quote Date") for ln in q_lines]
    q_lines.insert(q_lines.index(f"Quote Date: {TODAY.isoformat()}") + 1, f"Valid Until: {(TODAY + timedelta(days=30)).isoformat()}")
    quote = upload(f"quote_{RUN}.pdf", build_pdf(q_lines))
    vendor_id = quote and quote.get("vendor_id")
    if not check("vendor created from its quote", bool(vendor_id), quote and quote.get("status")):
        return None
    check("quote read as a quote, so no tax check", quote["document_type"] == "quote" and not quote.get("tax_check"),
          quote["document_type"])
    bad = requests.put(f"{GW}/tds/vendors/{vendor_id}", headers=H["finance"], json={"pan": "AB12"})
    check("invalid PAN -> 422", bad.status_code == 422 and "invalid_pan" in bad.text, bad.text[:120])
    bad = requests.put(f"{GW}/tds/vendors/{vendor_id}", headers=H["finance"], json={"msme_udyam_number": "UDYAM-KR-03-0012345"})
    check("Udyam number without a category -> 422", bad.status_code == 422, bad.text[:120])
    r = requests.put(f"{GW}/tds/vendors/{vendor_id}", headers=H["finance"], json={
        "pan": "AABCD5678E", "msme_udyam_number": "UDYAM-KR-03-0012345", "msme_category": "small"})
    check("tax profile saved (PAN, small enterprise)", r.status_code == 200 and r.json()["data"]["msme_tracked"], r.text[:150])
    check("approver can't edit a tax profile -> 403",
          requests.put(f"{GW}/tds/vendors/{vendor_id}", headers=H["approver"], json={}).status_code == 403)

    pr = requests.post(f"{GW}/requests/", headers=H["requester"], json={
        "request_type": "saas", "requested_by": "ignored", "department": f"E2E GST {RUN}", "amount": 118000,
        "currency": "INR", "vendor_id": vendor_id,
        "items": [{"name": SUPPORT[0]["name"], "quantity": 1, "unit_price": 100000}]}).json()["data"]
    ordered = approve_and_sign(pr["id"])
    if not check("request approved and contract signed -> ordered", ordered and ordered["status"] == "ordered",
                 ordered and ordered["status"]):
        return None

    lines, total, token = gst_invoice(SELLER, BUYER, f"INV-{RUN}-1", TODAY, SUPPORT, sign_with=demo_signing_key())
    lines.insert(lines.index(f"Invoice Date: {TODAY.isoformat()}") + 1, f"PO Reference: PO-{pr['id'][:8].upper()}")
    doc = upload(f"gst_ok_{RUN}.pdf", build_pdf(lines, token))
    tax = (doc or {}).get("tax_check") or {}
    check("tax check passes: CGST + SGST within Karnataka", tax.get("status") == "ok" and tax.get("supply_type") == "intra_state",
          f"{tax.get('status')} {tax.get('issues')}")
    check("signed e-invoice QR found and verified", (tax.get("einvoice") or {}).get("verified") is True and
          not (tax.get("einvoice") or {}).get("mismatches"), tax.get("einvoice"))
    check("rate checked against SAC 998313 (18%)", tax.get("expected_rate_pct") == 18.0, tax.get("expected_rate_pct"))
    led = poll(lambda: requests.get(f"{GW}/invoices/ledger/{pr['id']}", headers=H["finance"]).json()["data"],
               lambda l: l["invoices"], timeout=30)
    inv = (led or {}).get("invoices", [{}])[0]
    check("invoice booked against the request", inv.get("status") == "matched", inv)
    check("TDS 194J(a): 2% of ₹1,00,000 before GST = ₹2,000; net payable ₹1,16,000",
          inv.get("tds_section") == "194J(a)" and inv.get("tds_amount") == 2000 and inv.get("net_payable") == 116000,
          {k: inv.get(k) for k in ("tds_section", "tds_amount", "net_payable", "tds_notes")})
    reg = requests.get(f"{GW}/tds/register", headers=H["finance"]).json()["data"]
    check("TDS register lists it under its quarter", any(i["document_id"] == doc["id"] and i["tds_amount"] == 2000
                                                       for i in reg["invoices"]), reg.get("totals"))
    return {"doc": doc, "vendor_id": vendor_id, "request_id": pr["id"], "total": total}


def msme(booked):
    step("MSME payment deadline")
    items = requests.get(f"{GW}/tds/msme", headers=H["finance"]).json()["data"]
    mine = next((i for i in items if i["document_id"] == booked["doc"]["id"]), None)
    due = (TODAY + timedelta(days=45)).isoformat()
    check("small enterprise's invoice due 45 days after acceptance", mine and mine["due_date"] == due and mine["status"] == "ok",
          mine)
    r = requests.post(f"{GW}/tds/invoices/{booked['doc']['id']}/paid", headers=H["finance"], json={"reference": f"UTR{RUN}"})
    check("recording it paid (outside the platform)", r.status_code == 200 and r.json()["data"]["paid_by"] == "finance@demo.example.com",
          r.text[:150])
    items = requests.get(f"{GW}/tds/msme", headers=H["finance"]).json()["data"]
    check("paid invoice leaves the deadline list", all(i["document_id"] != booked["doc"]["id"] for i in items))
    again = requests.post(f"{GW}/tds/invoices/{booked['doc']['id']}/paid", headers=H["finance"], json={})
    check("recording it twice -> 409", again.status_code == 409, str(again.status_code))


def flagged_invoices():
    step("Invoices the tax check flags")
    lines, _, _ = gst_invoice(SELLER, BUYER, f"INV-{RUN}-2", TODAY, SUPPORT, split="inter")
    doc = upload(f"gst_igst_{RUN}.pdf", build_pdf(lines))
    tax = (doc or {}).get("tax_check") or {}
    check("IGST on a supply within the state -> flagged", tax.get("status") == "flagged" and
          any("expected CGST + SGST" in i for i in tax.get("issues", [])), tax.get("issues"))
    check("flagged invoice goes to review", doc and doc["needs_review"] is True)
    events = poll(lambda: requests.get(f"{GW}/admin/control-panel/events", headers=H["admin"],
                                       params={"topic": "invoice.tax_flagged", "since_hours": 1}).json()["data"]["events"],
                  lambda ev: any((e.get("fields") or {}).get("document_id") == doc["id"] for e in ev), timeout=30)
    check("invoice.tax_flagged published (Control Panel event log)",
          any((e.get("fields") or {}).get("document_id") == doc["id"] for e in events or []))

    lines, total, token = gst_invoice(SELLER, BUYER, f"INV-{RUN}-3", TODAY, SUPPORT, sign_with=demo_signing_key(),
                                      qr_overrides={"TotInvVal": 108000.0})
    doc3 = upload(f"gst_altered_{RUN}.pdf", build_pdf(lines, token))
    qr = ((doc3 or {}).get("tax_check") or {}).get("einvoice") or {}
    check("QR signed for ₹1,08,000 on an invoice showing ₹1,18,000 -> mismatch, flagged",
          qr.get("verified") is True and any("total value" in m for m in qr.get("mismatches", []))
          and doc3["tax_check"]["status"] == "flagged", qr)

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    lines, _, token = gst_invoice(SELLER, BUYER, f"INV-{RUN}-4", TODAY, SUPPORT, sign_with=other)
    doc4 = upload(f"gst_forged_{RUN}.pdf", build_pdf(lines, token))
    qr = ((doc4 or {}).get("tax_check") or {}).get("einvoice") or {}
    check("QR signed with another key -> signature fails, flagged",
          qr.get("verified") is False and doc4["tax_check"]["status"] == "flagged", qr)

    lines, total, _ = gst_invoice({"name": f"Cloudnine Software {RUN} Inc", "city": "Seattle"}, None, f"CN-{RUN}", TODAY,
                                  [{"name": "Notion Team seat licence", "quantity": 25, "unit_price": 18.0}],
                                  foreign=True, currency="USD")
    doc5 = upload(f"saas_usd_{RUN}.pdf", build_pdf(lines))
    tax = (doc5 or {}).get("tax_check") or {}
    fx = (doc5 or {}).get("fx") or {}
    check("USD SaaS invoice from abroad -> reverse charge", tax.get("status") == "reverse_charge" and tax.get("reverse_charge"),
          f"{tax.get('status')} {tax.get('notes')}")
    check("GST payable = 18% of the INR amount", fx.get("total_inr") and abs(tax.get("gst_payable_inr", 0) - fx["total_inr"] * 0.18) < 1,
          f"{tax.get('gst_payable_inr')} vs {fx.get('total_inr')}")
    return doc


def gstr2b(booked, missing_doc):
    step("GSTR-2B reconciliation")
    period = f"{TODAY.month:02d}{TODAY.year}"
    ok = booked["doc"]
    two_b = {"data": {"gstin": BUYER, "rtnprd": period, "docdata": {"b2b": [
        {"ctin": SELLER["gstin"], "trdnm": SELLER["name"].upper(), "inv": [
            {"inum": f"INV/{RUN}/1", "dt": TODAY.strftime("%d-%m-%Y"), "val": 118000, "txval": 100000,
             "cgst": 9000, "sgst": 9000, "igst": 0, "itcavl": "Y"},
            {"inum": f"GHOST-{RUN}", "dt": TODAY.strftime("%d-%m-%Y"), "val": 59000, "txval": 50000, "cgst": 4500, "sgst": 4500},
        ]}]}}}
    files = {"file": (f"2b_{RUN}.json", io.BytesIO(json.dumps(two_b).encode()), "application/json")}
    check("requester can't upload a 2B -> 403",
          requests.post(f"{GW}/gst/2b", headers=H["requester"], files=files).status_code == 403)
    other = json.loads(json.dumps(two_b))
    other["data"]["gstin"] = "29AABCD5678E2ZF"
    r = requests.post(f"{GW}/gst/2b", headers=H["finance"], files={"file": ("x.json", json.dumps(other), "application/json")})
    check("a 2B for another GSTIN -> 422", r.status_code == 422 and "wrong_gstin" in r.text, r.text[:150])
    r = requests.post(f"{GW}/gst/2b", headers=H["finance"], files={"file": ("x.json", b"{not json", "application/json")})
    check("not JSON -> 422", r.status_code == 422, str(r.status_code))
    r = requests.post(f"{GW}/gst/2b", headers=H["finance"],
                      files={"file": (f"2b_{RUN}.json", json.dumps(two_b), "application/json")})
    if not check("2B uploaded and reconciled", r.status_code == 201, r.text[:200]):
        return
    rows = r.json()["data"]["rows"]
    by_doc = {x["document_id"]: x for x in rows if x["document_id"]}
    check("our booked invoice matched (number written differently in the 2B)",
          by_doc.get(ok["id"], {}).get("result") == "matched", by_doc.get(ok["id"]))
    check("our invoice the supplier hasn't filed -> missing in 2B (ITC at risk)",
          by_doc.get(missing_doc["id"], {}).get("result") == "missing_in_2b", by_doc.get(missing_doc["id"]))
    check("2B entry we don't have -> not in books",
          any(x["result"] == "not_in_books" and x["invoice_number"] == f"GHOST-{RUN}" for x in rows))
    summary = requests.get(f"{GW}/gst/summary", headers=H["finance"]).json()["data"]
    check("monthly summary: input tax, reverse charge payable, last 2B",
          summary["input_tax"]["cgst"] >= 18000 / 2 and summary["reverse_charge_payable_inr"] > 0
          and summary["last_2b"] and summary["last_2b"]["id"] == r.json()["data"]["id"], summary)


def rules():
    step("Rules")
    keys = {x["rule_key"] for g in requests.get(f"{GW}/admin/business-rules", headers=H["admin"]).json()["data"].values() for x in g}
    phase4 = ("gst.buyer_gstin", "gst.tax_tolerance_inr", "gst.require_breakdown", "gst.einvoice_required_turnover_inr",
              "tds.category_sections", "msme.payment_days", "msme.warning_days")
    check("the seven Phase 4 rules are seeded", set(phase4) <= keys, sorted(set(phase4) - keys))
    for key, value in (("gst.buyer_gstin", "not-a-gstin"), ("tds.category_sections", {"furniture": "194C"}),
                       ("msme.payment_days", 60)):
        r = requests.patch(f"{GW}/admin/business-rules/{key}", headers=H["admin"],
                           json={"new_value": value, "justification": "gst e2e"})
        check(f"{key} = {value!r} refused -> 400", r.status_code == 400, f"{r.status_code} {r.text[:100]}")


def main():
    for role in ("requester", "approver", "finance", "admin"):
        H[role] = login(role)
    tables_and_roles()
    booked = correct_invoice_with_tds()
    missing = flagged_invoices()
    if booked:
        msme(booked)
        if missing:
            gstr2b(booked, missing)
    rules()
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("Failed:\n  " + "\n  ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
