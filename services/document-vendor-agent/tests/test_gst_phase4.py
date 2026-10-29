"""Feature expansion Phase 4: GST details read from an invoice, the tax
check (split, rate, arithmetic, GSTINs, reverse charge), the signed
e-invoice QR, GSTR-2B reconciliation and the pipeline stage. Rule-by-rule
behaviour is in test_rules_wiring.py; the live flow in tests/e2e/gst_flow.py."""
import asyncio
import os
import sys
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import shared.rules_engine as rules_engine
from app.services import einvoice, gstr2b, pipeline, tax_check
from app.services.field_extraction import extract_fields
from app.services.tax_extraction import extract_tax_fields

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from gst_invoice_lib import build_pdf, gst_invoice  # noqa: E402

BUYER = "29AAACA1234B1ZE"                       # Acme Corp, Karnataka
KA = {"name": "Kaveri Infotech Pvt Ltd", "gstin": "29AABCD5678E1ZG"}
MH = {"name": "Sahyadri Systems Pvt Ltd", "gstin": "27AABCH4321F1Z0", "city": "Pune"}
LAPTOPS = [{"name": "Latitude 5540 Laptop", "hsn": "8471", "quantity": 2, "unit_price": 80000.0}]
RATES = {"8471": {"rate_pct": 18.0, "category": "hardware"}, "998313": {"rate_pct": 18.0, "category": "services"},
         "998431": {"rate_pct": 18.0, "category": "saas"}}


def _key():
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption()).decode()
    public = k.public_key().public_bytes(serialization.Encoding.PEM,
                                         serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return private, public


PRIVATE, PUBLIC = _key()


@pytest.fixture(autouse=True)
def rules(monkeypatch):
    rules_engine.clear_cache()
    monkeypatch.setattr(rules_engine, "fetch_all_rules", lambda: {})
    yield rules_engine.update_rule_cache
    rules_engine.clear_cache()


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def read(lines):
    text = "\n".join(lines)
    fields, _ = extract_fields(text, "invoice")
    d = fields.to_dict("invoice")
    return text, d, extract_tax_fields(text, d["line_items"])


def checked(lines, qr=None, **ctx):
    text, d, tax = read(lines)
    kw = dict(total=d["total"], total_inr=d["total"], currency=d["currency"], line_items=d["line_items"],
              buyer_gstin=BUYER, rates=RATES)
    kw.update(ctx)
    return tax_check.check(tax, tax_check.TaxContext(**kw), qr)


# ── reading the GST details ─────────────────────────────────────────────────

def test_reads_gstins_split_rates_codes_and_irn():
    lines, total, _ = gst_invoice(KA, BUYER, "INV-1", date(2026, 10, 15), LAPTOPS, sign_with=PRIVATE)
    _, d, tax = read(lines)
    assert (tax.supplier_gstin, tax.buyer_gstin, tax.place_of_supply) == (KA["gstin"], BUYER, "29")
    assert (tax.taxable_value, tax.cgst, tax.sgst, tax.igst, tax.gst_total) == (160000.0, 14400.0, 14400.0, None, 28800.0)
    assert tax.rates == {"cgst": [9.0], "sgst": [9.0]} and tax.hsn_codes == [{"code": "8471", "line_total": 160000.0}]
    assert tax.irn and len(tax.irn) == 64
    assert d["amount_check"]["status"] == "consistent" and d["total"] == total   # existing fields unaffected


def test_buyer_gstin_on_the_line_below_bill_to_and_state_by_name():
    text = ("Vendor Co\nGSTIN: 29AABCD5678E1ZG\nBill To: Acme Corp\nGSTIN: 29AAACA1234B1ZE\n"
            "Place of Supply: Tamil Nadu\nUTGST @ 9%: 900.00\nCGST @ 9%: 900.00\nIGST 18% 0.00\n")
    tax = extract_tax_fields(text)
    assert (tax.supplier_gstin, tax.buyer_gstin, tax.place_of_supply) == ("29AABCD5678E1ZG", BUYER, "33")
    assert tax.sgst == 900.0 and tax.cgst == 900.0


def test_hsn_from_labels_when_not_in_the_item_table():
    tax = extract_tax_fields("SAC: 998313\nIGST @ 18%: 1,800.00")
    assert tax.hsn_codes == [{"code": "998313", "line_total": None}] and tax.igst == 1800.0


# ── the check (plan acceptance: intra-state with IGST flagged, correct passes) ─

def test_correct_intra_state_invoice_passes():
    r = checked(gst_invoice(KA, BUYER, "INV-2", date(2026, 10, 15), LAPTOPS)[0])
    assert r["status"] == "ok" and r["supply_type"] == "intra_state" and r["itc_eligible"]
    assert r["expected_rate_pct"] == r["effective_rate_pct"] == 18.0


def test_intra_state_invoice_charging_igst_is_flagged():
    r = checked(gst_invoice(KA, BUYER, "INV-3", date(2026, 10, 15), LAPTOPS, split="inter")[0])
    assert r["status"] == "flagged" and not r["itc_eligible"]
    assert any("expected CGST + SGST, found IGST" in i for i in r["issues"])


def test_inter_state_needs_igst_and_passes_with_it():
    assert checked(gst_invoice(MH, BUYER, "INV-4", date(2026, 10, 15), LAPTOPS)[0])["status"] == "ok"
    r = checked(gst_invoice(MH, BUYER, "INV-5", date(2026, 10, 15), LAPTOPS, split="intra")[0])
    assert r["status"] == "flagged" and r["supply_type"] == "inter_state"
    assert any("expected IGST" in i for i in r["issues"])


def test_wrong_rate_for_the_hsn_code_is_flagged():
    r = checked(gst_invoice(KA, BUYER, "INV-6", date(2026, 10, 15), LAPTOPS, rate_pct=12)[0])
    assert r["status"] == "flagged" and r["effective_rate_pct"] == 12.0
    assert any("expected 18%" in i for i in r["issues"])


def test_mixed_rates_are_checked_per_line():
    rates = {**RATES, "998313": {"rate_pct": 5.0, "category": "services"}}
    items = LAPTOPS + [{"name": "IT support retainer", "hsn": "998313", "quantity": 1, "unit_price": 40000.0}]
    r = checked(gst_invoice(KA, BUYER, "INV-7", date(2026, 10, 15), items)[0], rates=rates)
    assert r["status"] == "flagged" and r["expected_rate_pct"] == 15.4      # (160000*18% + 40000*5%) / 200000


def test_unknown_code_is_a_note_not_a_flag():
    items = [{"name": "Mystery gadget", "hsn": "9999", "quantity": 1, "unit_price": 1000.0}]
    r = checked(gst_invoice(KA, BUYER, "INV-8", date(2026, 10, 15), items)[0])
    assert r["status"] == "ok" and any("9999 not in the GST rate table" in n for n in r["notes"])


def test_totals_that_dont_add_up_are_flagged():
    lines = gst_invoice(KA, BUYER, "INV-9", date(2026, 10, 15), LAPTOPS)[0]
    lines = [ln.replace("Total: 188,800.00", "Total: 190,800.00") for ln in lines]
    r = checked(lines)
    assert r["status"] == "flagged" and any("invoice total ₹1,90,800.00" in i for i in r["issues"])


def test_invoice_addressed_to_another_gstin_is_flagged():
    r = checked(gst_invoice(KA, "29AABCD5678E2ZF", "INV-10", date(2026, 10, 15), LAPTOPS)[0])
    assert r["status"] == "flagged" and any("input tax credit can't be claimed" in i for i in r["issues"])


def test_invalid_or_foreign_supplier_gstin_is_flagged():
    bad = {**KA, "gstin": "29AABCD5678E1ZH"}                       # wrong check digit
    assert any("check-digit" in i for i in checked(gst_invoice(bad, BUYER, "INV-11", date(2026, 10, 15), LAPTOPS)[0])["issues"])
    r = checked(gst_invoice(KA, BUYER, "INV-12", date(2026, 10, 15), LAPTOPS)[0], vendor_gstin="29AABCD5678E2ZF")
    assert r["status"] == "flagged" and any("vendor master has 29AABCD5678E2ZF" in i for i in r["issues"])


def test_foreign_saas_invoice_is_reverse_charge_with_gst_payable():
    """Plan acceptance: a USD invoice from a supplier with no GSTIN."""
    items = [{"name": "Freshdesk Pro Seat License", "quantity": 20, "unit_price": 49.0}]
    lines, total, _ = gst_invoice({"name": "Freshworks Inc", "city": "San Mateo"}, None, "FW-1", date(2026, 10, 15),
                                  items, foreign=True, currency="USD")
    r = checked(lines, currency="USD", total_inr=total * 84.0)
    assert r["status"] == "reverse_charge" and r["reverse_charge"] and r["supply_type"] == "import"
    assert r["gst_payable_inr"] == round(total * 84.0 * 0.18, 2)


def test_imported_hardware_is_not_reverse_charge():
    items = [{"name": "Rack Server PowerEdge R650", "quantity": 1, "unit_price": 5000.0}]
    lines, _, _ = gst_invoice({"name": "Dell Inc", "city": "Austin"}, None, "D-1", date(2026, 10, 15), items,
                              foreign=True, currency="USD")
    r = checked(lines, currency="USD")
    assert r["status"] == "import_goods" and r["gst_payable_inr"] is None


def test_no_breakdown_is_incomplete_not_flagged():
    r = checked(["Vendor Co", "Invoice Number: INV-13", "Subtotal: 1,000.00", "Tax (18%): 180.00", "Total: 1,180.00"])
    assert r["status"] == "incomplete" and r["issues"] == []


def test_missing_qr_flagged_only_when_the_supplier_must_e_invoice():
    lines = gst_invoice(KA, BUYER, "INV-14", date(2026, 10, 15), LAPTOPS)[0]
    assert checked(lines)["status"] == "ok"                              # turnover unknown
    assert checked(lines, vendor_turnover_inr=10_000_000)["status"] == "ok"
    r = checked(lines, vendor_turnover_inr=80_000_000)
    assert r["status"] == "flagged" and any("must be e-invoices" in i for i in r["issues"])


# ── e-invoice QR (plan acceptance: valid QR verifies, altered total fails) ──

def _qr_check(lines, token, key=PUBLIC):
    _, d, tax = read(lines)
    return einvoice.verify(token, supplier_gstin=tax.supplier_gstin, buyer_gstin=tax.buyer_gstin,
                           invoice_number=d["invoice_number"], total=d["total"], irn=tax.irn, key=key)


def test_valid_qr_verifies_and_matches():
    lines, _, token = gst_invoice(KA, BUYER, "INV-15", date(2026, 10, 15), LAPTOPS, sign_with=PRIVATE)
    qr = _qr_check(lines, token)
    assert qr.verified and qr.mismatches == [] and qr.claims["DocNo"] == "INV-15"
    assert checked(lines, qr)["status"] == "ok"


def test_total_altered_after_signing_fails():
    lines, _, token = gst_invoice(KA, BUYER, "INV-16", date(2026, 10, 15), LAPTOPS, sign_with=PRIVATE)
    altered = [ln.replace("Total: 188,800.00", "Total: 198,800.00") for ln in lines]
    qr = _qr_check(altered, token)
    assert qr.verified and any("total value: the signed QR says ₹1,88,800.00" in m for m in qr.mismatches)
    assert checked(altered, qr)["status"] == "flagged"


def test_qr_signed_with_another_key_or_tampered_fails():
    lines, _, token = gst_invoice(KA, BUYER, "INV-17", date(2026, 10, 15), LAPTOPS, sign_with=_key()[0])
    qr = _qr_check(lines, token)
    assert qr.verified is False and "signature" in qr.error
    head, body, sig = jwt.encode({"data": "{}"}, PRIVATE, algorithm="RS256").split(".")
    assert _qr_check(lines, f"{head}.{body}x.{sig}").verified is False
    assert checked(lines, qr)["status"] == "flagged"


def test_no_key_means_not_verified_and_a_note():
    lines, _, token = gst_invoice(KA, BUYER, "INV-18", date(2026, 10, 15), LAPTOPS, sign_with=PRIVATE)
    qr = _qr_check(lines, token, key="")
    assert qr.verified is None and "no IRP public key" in qr.error
    r = checked(lines, qr)
    assert r["status"] == "ok" and any("not verified" in n for n in r["notes"])


def test_production_never_trusts_the_demo_key(monkeypatch, tmp_path):
    einvoice.public_key.cache_clear()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("EINVOICE_PUBLIC_KEY_FILE", raising=False)
    assert einvoice.public_key() is None
    einvoice.public_key.cache_clear()
    monkeypatch.setenv("EINVOICE_PUBLIC_KEY_FILE", einvoice._demo_key_path())
    assert einvoice.public_key() is None
    einvoice.public_key.cache_clear()
    real = tmp_path / "irp.pem"
    real.write_text(PUBLIC)
    monkeypatch.setenv("EINVOICE_PUBLIC_KEY_FILE", str(real))
    assert einvoice.public_key() == PUBLIC
    einvoice.public_key.cache_clear()
    monkeypatch.delenv("EINVOICE_PUBLIC_KEY_FILE")
    monkeypatch.setenv("EINVOICE_PUBLIC_KEY", PUBLIC.replace("\n", "\\n"))     # one line in .env
    assert einvoice.public_key() == PUBLIC
    einvoice.public_key.cache_clear()
    monkeypatch.setenv("EINVOICE_PUBLIC_KEY", open(einvoice._demo_key_path()).read())
    assert einvoice.public_key() is None
    monkeypatch.delenv("EINVOICE_PUBLIC_KEY")
    einvoice.public_key.cache_clear()
    monkeypatch.setenv("APP_ENV", "development")
    assert "BEGIN PUBLIC KEY" in einvoice.public_key()
    einvoice.public_key.cache_clear()


def test_qr_is_found_on_the_pdf():
    lines, _, token = gst_invoice(KA, BUYER, "INV-19", date(2026, 10, 15), LAPTOPS, sign_with=PRIVATE)
    assert einvoice.find_qr_token(build_pdf(lines, token), "pdf") == token
    assert einvoice.find_qr_token(build_pdf(lines), "pdf") is None
    assert einvoice.find_qr_token(b"not a pdf", "pdf") is None           # never raises


# ── GSTR-2B (plan acceptance: an upload lists a missing invoice) ────────────

TWO_B = {"data": {"gstin": BUYER, "rtnprd": "102026", "docdata": {"b2b": [
    {"ctin": KA["gstin"], "trdnm": "KAVERI INFOTECH", "inv": [
        {"inum": "INV/2026/0042", "dt": "15-10-2026", "val": 188800, "txval": 160000, "cgst": 14400, "sgst": 14400, "igst": 0, "itcavl": "Y"},
        {"inum": "INV-2026-0050", "dt": "20-10-2026", "val": 118000, "items": [{"txval": 100000, "igst": 0, "cgst": 9000, "sgst": 9000}]},
    ]},
    {"ctin": MH["gstin"], "trdnm": "SAHYADRI", "inv": [{"inum": "S-77", "dt": "02-10-2026", "val": 59000, "txval": 50000, "igst": 9000}]},
]}}}


def _book(doc, gstin, number, when, taxable, gst):
    return {"document_id": doc, "supplier_gstin": gstin, "invoice_number": number, "invoice_date": when,
            "taxable_value": taxable, "gst_total": gst, "vendor_name": "v"}


def test_2b_is_parsed_with_invoice_or_item_level_tax():
    period, buyer, entries = gstr2b.parse(TWO_B)
    assert (period, buyer, len(entries)) == ("102026", BUYER, 3)
    assert entries[1].taxable_value == 100000 and entries[1].tax == 18000 and entries[0].invoice_date == "2026-10-15"
    assert gstr2b.parse(TWO_B["data"])[0] == "102026"                     # the "data" part alone is fine too
    for bad in ({}, {"data": {"rtnprd": "132026"}}, {"rtnprd": "102026"}, []):
        with pytest.raises(gstr2b.Gstr2bFormatError):
            gstr2b.parse(bad)


def test_2b_reconciliation_buckets():
    period, _, entries = gstr2b.parse(TWO_B)
    books = [
        _book("d1", KA["gstin"], "INV-2026-0042", "2026-10-15", 160000, 28800),   # same invoice, other punctuation
        _book("d2", KA["gstin"], "INV-2026-0050", "2026-10-20", 100000, 9000),    # tax differs
        _book("d3", KA["gstin"], "INV-2026-0061", "2026-10-25", 50000, 9000),     # supplier hasn't filed it
        _book("d4", KA["gstin"], "INV-2026-0001", "2026-09-05", 10000, 1800),     # another month: not "missing"
    ]
    out = gstr2b.reconcile(entries, books, period)
    by = {r["result"]: r for r in out["rows"]}
    s = out["summary"]
    assert (s["matched"], s["value_mismatch"], s["missing_in_2b"], s["not_in_books"], s["entries_in_2b"]) == (1, 1, 1, 1, 3)
    assert by["matched"]["document_id"] == "d1"
    assert "tax ₹9,000.00 in our books, ₹18,000.00 in the 2B" in by["value_mismatch"]["detail"]
    assert by["missing_in_2b"]["document_id"] == "d3" and by["not_in_books"]["invoice_number"] == "S-77"
    assert out["summary"]["itc_at_risk_inr"] == 18000.0


def test_2b_number_threshold_decides_the_match():
    _, _, entries = gstr2b.parse(TWO_B)
    books = [_book("d1", KA["gstin"], "INV-2026-0042", "2026-10-15", 160000, 28800)]
    assert gstr2b.reconcile(entries[:1], books, "102026")["summary"]["matched"] == 1
    assert gstr2b.reconcile(entries[:1], [{**books[0], "invoice_number": "INV-2025-0911"}], "102026")["summary"]["matched"] == 0


# ── the pipeline stage ──────────────────────────────────────────────────────

def _envelope(lines, document_type="invoice"):
    text = "\n".join(lines)
    fields, _ = extract_fields(text, document_type)
    d = fields.to_dict(document_type)
    return {"document_id": "doc-1", "document_type": document_type, "raw_text": text, "extracted_fields": d,
            "vendor_id": "v-1", "file_type": "pdf", "fx": {"total_inr": d["total"], "rate": 1.0}, "_agent_trail": []}


def stage(envelope, vendor=None, data=b""):
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=vendor)))
    producer = MagicMock(publish_invoice_tax_flagged=AsyncMock())
    with patch.object(pipeline, "load_gst_rates", AsyncMock(return_value=RATES)):
        out = run(pipeline.tax_agent(db, producer, envelope, data))
    return out, producer.publish_invoice_tax_flagged


def test_flagged_invoice_goes_to_review_and_publishes_without_touching_confidence(rules):
    rules("gst.buyer_gstin", BUYER)
    env, published = stage(_envelope(gst_invoice(KA, BUYER, "INV-20", date(2026, 10, 15), LAPTOPS, split="inter")[0]))
    assert env["tax_check"]["status"] == "flagged" and env["needs_review_forced"] is True
    published.assert_awaited_once()
    assert published.await_args.kwargs["supply_type"] == "intra_state" and published.await_args.kwargs["issues"]
    assert "overall_confidence" not in env and env["_agent_trail"][-1].validation_status == "needs_review"


def test_clean_invoice_and_non_invoices_pass_through(rules):
    rules("gst.buyer_gstin", BUYER)
    env, published = stage(_envelope(gst_invoice(KA, BUYER, "INV-21", date(2026, 10, 15), LAPTOPS)[0]))
    assert env["tax_check"]["status"] == "ok" and not env.get("needs_review_forced")
    published.assert_not_awaited()
    quote, published = stage(_envelope(["Quotation", "Quote Number: QT-1", "Total: 100.00"], "quote"))
    assert quote["tax_check"] is None and not published.await_count


def test_stage_reads_the_qr_from_the_file(rules, monkeypatch):
    rules("gst.buyer_gstin", BUYER)
    monkeypatch.setattr(einvoice, "public_key", lambda: PUBLIC)
    lines, _, token = gst_invoice(KA, BUYER, "INV-22", date(2026, 10, 15), LAPTOPS, sign_with=PRIVATE)
    env, _ = stage(_envelope(lines), data=build_pdf(lines, token))
    assert env["tax_check"]["einvoice"]["verified"] is True and env["tax_check"]["status"] == "ok"


def test_ledger_gets_the_taxable_value_in_inr():
    """invoice_matching_agent sends the amount before GST, converted, so
    approval-inventory-agent can work out TDS on it."""
    env = _envelope(gst_invoice(KA, BUYER, "INV-23", date(2026, 10, 15), LAPTOPS)[0])
    env["tax_check"] = {"status": "ok", "taxable_value": 160000.0, "gst_total": 28800.0, "supply_type": "intra_state"}
    sent = {}

    class Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json, headers):
            sent.update(json)
            return MagicMock(status_code=200, json=lambda: {"data": {"status": "no_match", "issues": []}})

    with patch("httpx.AsyncClient", Client):
        run(pipeline.invoice_matching_agent(MagicMock(), None, env))
    assert sent["taxable_value"] == 160000.0 and sent["gst_amount"] == 28800.0
    assert sent["foreign_supplier"] is False and sent["invoice_date"] == "2026-10-15"


def test_qr_search_runs_only_where_an_e_invoice_is_expected(rules):
    """The QR search is the slowest step for ordinary invoices (PERF-1); it
    runs when an IRN / e-invoice wording is printed, or when the supplier's
    turnover makes e-invoicing mandatory (otherwise "QR present" would fail
    without having looked)."""
    rules("gst.buyer_gstin", BUYER)
    rules("gst.einvoice_required_turnover_inr", 50_000_000)
    plain = _envelope(gst_invoice(KA, BUYER, "INV-30", date(2026, 10, 15), LAPTOPS)[0])
    signed_lines, _, token = gst_invoice(KA, BUYER, "INV-31", date(2026, 10, 15), LAPTOPS, sign_with=PRIVATE)
    small = SimpleNamespace(gstin=KA["gstin"], country="IN", annual_turnover_inr=10_000_000)
    large = SimpleNamespace(gstin=KA["gstin"], country="IN", annual_turnover_inr=900_000_000)
    with patch.object(einvoice, "find_qr_token", wraps=einvoice.find_qr_token) as finder:
        stage(plain, vendor=small, data=build_pdf(plain_lines := plain["raw_text"].split("\n")))
        assert finder.call_count == 0
        env, _ = stage(plain, vendor=large, data=build_pdf(plain_lines))
        assert finder.call_count == 1
        assert any(c["check"] == "e-invoice QR present" and not c["ok"] for c in env["tax_check"]["checks"])
        env, _ = stage(_envelope(signed_lines), vendor=small, data=build_pdf(signed_lines, token))
        assert finder.call_count == 2 and env["tax_check"]["einvoice"]["present"] is True
    assert einvoice.looks_like_einvoice("IRN: 3f2a…\nAck No: 1123") and not einvoice.looks_like_einvoice("TAX INVOICE")
