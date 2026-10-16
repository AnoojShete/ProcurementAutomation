from app.services.field_extraction import extract_fields

SAMPLE_INVOICE = """Acme IT Supplies Inc
TAX INVOICE
Invoice Number: INV-10432
Invoice Date: 2026-03-12
Bill To: Engineering Dept

Description             Qty    Unit Price    Line Total
Dell Laptop 14in         5         900.00       4500.00
USB-C Dock                5          45.00        225.00

Grand Total: INR 4725.00

Bank Account Number: 000123456789
Routing Code: HDFC0001234
Account Name: Acme IT Supplies Inc
"""


class TestFieldExtraction:
    def test_extracts_vendor_name_from_first_line(self):
        fields, conf = extract_fields(SAMPLE_INVOICE)
        assert fields.vendor_name_raw == "Acme IT Supplies Inc"
        assert conf.vendor_name > 0.5

    def test_extracts_document_number(self):
        fields, _ = extract_fields(SAMPLE_INVOICE)
        assert fields.document_number == "INV-10432"

    def test_extracts_document_date_as_iso(self):
        fields, _ = extract_fields(SAMPLE_INVOICE)
        assert fields.document_date == "2026-03-12"

    def test_extracts_total_and_currency(self):
        fields, conf = extract_fields(SAMPLE_INVOICE)
        assert fields.total == 4725.00
        assert fields.currency == "INR"
        assert conf.total > 0.5

    def test_extracts_line_items(self):
        fields, conf = extract_fields(SAMPLE_INVOICE)
        assert len(fields.line_items) == 2
        assert fields.line_items[0]["description"] == "Dell Laptop 14in"
        assert fields.line_items[0]["quantity"] == 5
        assert fields.line_items[0]["unit_price"] == 900.00
        assert conf.line_items > 0.5

    def test_extracts_vendor_bank_details(self):
        fields, _ = extract_fields(SAMPLE_INVOICE)
        assert fields.bank_account_number == "000123456789"
        assert fields.routing_code == "HDFC0001234"
        assert fields.payment_beneficiary_name == "Acme IT Supplies Inc"

    def test_missing_fields_yield_none_and_zero_confidence(self):
        fields, conf = extract_fields("garbled nonsense with no structure at all")
        assert fields.document_number is None
        assert fields.total is None
        assert conf.document_number == 0.0
        assert conf.total == 0.0


# OCR of a column layout: a row of labels, then a row of values.
COLUMN_LAYOUT_INVOICE = """Sample Invoice
YOUR COMPANY
Billed To
Date Issued
Invoice Number
Amount Due
Your Client
26/3/2021
INV-10012
$1,699.48
Due Date
25/4/2021
Total
$1,699.48
"""


class TestColumnLayout:
    def test_document_number_is_the_value_not_the_next_label(self):
        fields, conf = extract_fields(COLUMN_LAYOUT_INVOICE)
        assert fields.document_number == "INV-10012"
        assert 0 < conf.document_number < 0.95  # fallback: lower confidence

    def test_document_date_is_the_first_date_value(self):
        fields, conf = extract_fields(COLUMN_LAYOUT_INVOICE)
        assert fields.document_date == "2021-03-26"
        assert conf.document_date == 0.5

    def test_labelled_number_still_preferred(self):
        fields, conf = extract_fields(SAMPLE_INVOICE + "\nRef PO-12345\n")
        assert fields.document_number == "INV-10432"
        assert conf.document_number == 0.95


class TestPoBackedInvoices:
    def test_invoice_citing_a_purchase_order_is_po_backed(self):
        fields, _ = extract_fields(SAMPLE_INVOICE + "\nPO Number: PO-2026-00042\n", document_type="invoice")
        d = fields.to_dict("invoice")
        assert d["po_reference"] == "PO-2026-00042" and d["po_backed"] is True

    def test_invoice_without_a_purchase_order_is_non_po(self):
        fields, _ = extract_fields(SAMPLE_INVOICE, document_type="invoice")
        d = fields.to_dict("invoice")
        assert d["po_reference"] is None and d["po_backed"] is False

    def test_other_phrasings(self):
        for line, ref in (("Purchase Order No. 4500012345", "4500012345"), ("P.O. #: PO/77/2026", "PO/77/2026")):
            fields, _ = extract_fields(SAMPLE_INVOICE + "\n" + line + "\n", document_type="invoice")
            assert fields.po_reference == ref, line
