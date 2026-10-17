"""FR-11: extraction output matches shared/schemas/extraction-output.schema.json,
and GST-style tax lines ("Tax (18%): …") are read so the amounts add up."""
import json
import os
import random

import jsonschema
import pytest

from app.services.field_extraction import extract_fields

_HERE = os.path.dirname(os.path.abspath(__file__))
_CANDIDATES = [os.path.join(_HERE, "..", "shared", "schemas"),             # inside the image (/app/shared)
               os.path.join(_HERE, "..", "..", "..", "shared", "schemas")]  # repo checkout
SCHEMA_PATH = next(os.path.join(d, "extraction-output.schema.json") for d in _CANDIDATES
                   if os.path.exists(os.path.join(d, "extraction-output.schema.json")))
SCHEMA = json.load(open(SCHEMA_PATH))
validator = jsonschema.Draft202012Validator(SCHEMA)


def _corpus():
    import sys
    sys.path.insert(0, os.path.join(_HERE, "..", "scripts"))
    from synthetic_invoice_lib import generate_manifest
    _, docs = generate_manifest(seed=7, n_documents=24)
    return docs


def test_schema_itself_is_valid():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("doc", _corpus(), ids=lambda d: f"{d.doc_type}-{d.layout}-{d.document_number}")
def test_generated_documents_match_the_schema(doc):
    fields, _ = extract_fields("\n".join(doc.lines), document_type=doc.doc_type)
    out = fields.to_dict(doc.doc_type)
    errors = sorted(validator.iter_errors(out), key=lambda e: list(e.path))
    assert not errors, [f"{list(e.path)}: {e.message}" for e in errors]


@pytest.mark.parametrize("doc_type", ["invoice", "po", "quote", "other"])
def test_empty_text_still_matches(doc_type):
    fields, _ = extract_fields("", document_type=doc_type)
    validator.validate(fields.to_dict(doc_type))


def test_unknown_field_is_rejected():
    fields, _ = extract_fields("", document_type="invoice")
    out = fields.to_dict("invoice") | {"surprise": 1}
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(out)


@pytest.mark.parametrize("line,amount", [("Tax (18%): 47,117.75", 47117.75), ("GST @ 18%: 1,800.00", 1800.00),
                                         ("IGST: 900.00", 900.00), ("Total Tax: INR 12.50", 12.50)])
def test_tax_lines_with_a_rate_are_read(line, amount):
    fields, _ = extract_fields(f"TAX INVOICE\nInvoice Number: INV-9\nSubtotal: 100.00\n{line}\n", document_type="invoice")
    assert fields.tax_amount == amount


def test_generated_invoices_add_up():
    invoices = [d for d in _corpus() if d.doc_type == "invoice"]
    for doc in invoices:
        fields, _ = extract_fields("\n".join(doc.lines), document_type="invoice")
        if fields.amount_check:
            assert fields.amount_check["status"] == "consistent", (doc.document_number, fields.amount_check)
