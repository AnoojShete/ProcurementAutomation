from datetime import datetime, timezone
import pytest
from app.services.contract_pdf import ContractPdfInput, render_contract_pdf


def test_render_contract_pdf_with_mandate_and_channel():
    now = datetime.now(timezone.utc)
    pdf_input = ContractPdfInput(
        contract_id="c-test-12345678",
        contract_text="SOFTWARE LICENSE AGREEMENT\nThis agreement is made between Company and Vendor.",
        status="signed",
        version=1,
        template="standard_saas",
        vendor_name="Acme Corp",
        generated_at=now,
        signed_at=now,
        signed_by="Finance Approver <finance@company.com>",
        esign_provider_ref="builtin-123",
        signature_method="auto_mandate",
        approval_channel="portal",
        bulk_batch_id="batch-abcdef123456",
        mandate_id="mandate-9876543210",
        mandate_text_hash="abc123def456",
    )

    pdf_bytes = render_contract_pdf(pdf_input, include_certificate=True)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF-")


def test_render_contract_pdf_with_email_channel():
    now = datetime.now(timezone.utc)
    pdf_input = ContractPdfInput(
        contract_id="c-test-email-123",
        contract_text="SERVICE LEVEL AGREEMENT\nTerms and conditions apply.",
        status="signed",
        version=1,
        template="sla",
        vendor_name="Global Vendor",
        generated_at=now,
        signed_at=now,
        signed_by="Approver One",
        approval_channel="email",
    )

    pdf_bytes = render_contract_pdf(pdf_input, include_certificate=True)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF-")
