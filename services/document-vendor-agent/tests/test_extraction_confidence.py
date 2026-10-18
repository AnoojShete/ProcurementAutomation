"""Why OCR'd invoices scored ~0.5 and what lifts a correct read: real OCR
confidence instead of a letters-only heuristic, rows rebuilt from
PaddleOCR's boxes, column-aware labels, and amounts that cross-check."""
from app.services.confidence import overall_confidence
from app.services.field_extraction import _value_below, extract_fields
from app.services.ocr import _ocr_confidence, _rows_to_text, _text_quality


def _ln(text, x0, y0, x1, y1, conf=0.99):
    return {"text": text, "confidence": conf, "box": [x0, y0, x1, y1]}


class TestOcrRows:
    def test_blocks_on_one_row_are_joined_left_to_right(self):
        lines = [_ln("$550.00", 400, 101, 450, 113), _ln("Services", 10, 100, 80, 112),
                 _ln("10", 300, 100, 315, 112), _ln("$55.00", 200, 99, 250, 111),
                 _ln("Consulting", 10, 140, 90, 152)]
        assert _rows_to_text(lines) == "Services  $55.00  10  $550.00\nConsulting"

    def test_confidence_is_paddles_weighted_by_length(self):
        assert _ocr_confidence([_ln("Total", 0, 0, 1, 1, 1.0), _ln("x", 0, 0, 1, 1, 0.5)]) == round(5.5 / 6, 3)

    def test_numbers_count_as_good_text(self):
        assert _text_quality("Total $1,699.48 Date 26/3/2021 Qty 10 INV-10012") == 1.0


SCANNED = """Sample Invoice  YOUR COMPANY
Billed To  Date Issued  Invoice Number  Amount Due
Your Client  26/3/2021  INV-10012  $1,699.48
City, California  Due Date
90210  25/4/2021
DESCRIPTION  RATE  QTY  AMOUNT
Services  $55.00  10  $550.00
Consulting  $75.00  15  $1,125.00
Materials  $123.39  1  $123.39
Subtotal  $1,798.39
Discount  -$179.84
Tax  +$80.93
Total  $1,699.48
"""


class TestColumnLayoutFields:
    def test_values_read_from_the_column_below_the_label(self):
        fields, conf = extract_fields(SCANNED)
        assert fields.vendor_name_raw == "YOUR COMPANY"
        assert fields.document_number == "INV-10012" and conf.document_number == 0.9
        assert fields.document_date == "2021-03-26" and conf.document_date == 0.9
        assert fields.due_date == "2021-04-25"

    def test_rate_before_qty_line_items_with_currency_symbols(self):
        fields, conf = extract_fields(SCANNED)
        assert [(i["description"], i["quantity"], i["unit_price"]) for i in fields.line_items] == [
            ("Services", 10, 55.0), ("Consulting", 15, 75.0), ("Materials", 1, 123.39)]

    def test_value_below_needs_aligned_rows(self):
        import re
        assert _value_below("A  Invoice Number\nB  INV-1", re.compile("invoice number", re.I)) == "INV-1"
        assert _value_below("Invoice Number\n", re.compile("invoice number", re.I)) is None


class TestAmountCrossCheck:
    def test_consistent_amounts_raise_confidence(self):
        fields, conf = extract_fields(SCANNED)
        assert fields.amount_check["status"] == "consistent"
        assert conf.total == 0.98 and conf.line_items == 0.98

    def test_amounts_that_dont_add_up_lower_confidence(self):
        fields, conf = extract_fields(SCANNED.replace("Total  $1,699.48", "Total  $1,999.48"))
        assert fields.amount_check["status"] == "mismatch"
        assert conf.total == 0.5


class TestOverall:
    def test_missing_optional_line_items_dont_drag_the_score(self):
        base = {"total": 0.9, "vendor_name": 0.9, "classification": 0.9, "document_number": 0.9, "document_date": 0.9}
        assert overall_confidence({**base, "line_items": 0.0}) == 0.9

    def test_missing_total_weighs_more_than_missing_date(self):
        full = {"total": 0.9, "vendor_name": 0.9, "classification": 0.9, "document_number": 0.9, "document_date": 0.9}
        assert overall_confidence({**full, "total": 0.0}) < overall_confidence({**full, "document_date": 0.0})
