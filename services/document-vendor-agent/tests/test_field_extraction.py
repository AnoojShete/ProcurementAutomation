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
