"""BR-1: documents emailed to the intake address enter the pipeline like an
upload, with the sender recorded; other attachments are rejected with a
reason; each email is handled once; other mail is ignored."""
import asyncio
from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services import email_intake as ei

PDF = b"%PDF-1.4\n1 0 obj << /Type /Page >> endobj\n%%EOF"


def _mail(to="invoices@procurement.local", attachments=(("invoice.pdf", "application/pdf", PDF),)):
    m = EmailMessage()
    m["From"] = "Billing <billing@vendor.example>"
    m["To"] = to
    m["Subject"] = "Invoice INV-1"
    m["Message-ID"] = "<abc123@vendor.example>"
    m["Date"] = "Thu, 15 Oct 2026 10:00:00 +0000"
    m.set_content("Please find the invoice attached.")
    for name, ctype, data in attachments:
        maintype, subtype = ctype.split("/")
        m.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return ei.parse(m.as_bytes())


def test_parse_reads_sender_recipients_and_attachments():
    mail = _mail()
    assert mail.sender == "billing@vendor.example"
    assert "invoices@procurement.local" in mail.recipients
    assert [(a.filename, a.data[:5]) for a in mail.attachments] == [("invoice.pdf", b"%PDF-")]


def test_only_mail_to_the_intake_address_counts():
    assert ei.is_for_intake(_mail(), "invoices@procurement.local")
    assert not ei.is_for_intake(_mail(to="approver@demo.example.com"), "invoices@procurement.local")


def test_rejection_reasons():
    ok = ei.Attachment("a.PDF", "application/pdf", PDF)
    assert ei.rejection_reason(ok) is None
    assert "not a PDF, PNG or JPEG" in ei.rejection_reason(ei.Attachment("notes.docx", "application/msword", b"x"))
    assert "empty" in ei.rejection_reason(ei.Attachment("a.pdf", "application/pdf", b""))


def _factory(already=False):
    session = AsyncMock()
    res = MagicMock()
    res.first.return_value = (1,) if already else None
    session.execute.return_value = res
    f = MagicMock()
    f.return_value.__aenter__.return_value = session
    return f, session


def _patch_upload(monkeypatch, doc_id="d-1"):
    monkeypatch.setattr(ei, "scan_upload", AsyncMock())
    store = AsyncMock(return_value=SimpleNamespace(id=doc_id))
    monkeypatch.setattr(ei, "store_and_record_upload", store)
    return store


def test_pdf_becomes_a_document_with_the_sender(monkeypatch):
    store = _patch_upload(monkeypatch)
    factory, session = _factory()
    record = asyncio.run(ei.process_email(factory, object(), _mail()))
    assert record["status"] == "processed" and record["document_ids"] == ["d-1"]
    kwargs = store.await_args.kwargs
    assert kwargs["source"] == "email" and kwargs["source_sender"] == "billing@vendor.example"
    assert store.await_args.args[5] == ei.EMAIL_INTAKE_UPLOADER
    assert "INSERT INTO email_intake" in str(session.execute.await_args_list[-1].args[0])


def test_non_document_attachment_is_rejected_with_a_reason(monkeypatch):
    _patch_upload(monkeypatch)
    factory, _ = _factory()
    mail = _mail(attachments=(("invoice.pdf", "application/pdf", PDF), ("terms.docx", "application/msword", b"PK..")))
    record = asyncio.run(ei.process_email(factory, object(), mail))
    assert record["status"] == "partial"
    assert record["rejections"] == [{"filename": "terms.docx", "reason": "not a PDF, PNG or JPEG (terms.docx)"}]


def test_email_without_attachments_is_recorded_as_rejected(monkeypatch):
    _patch_upload(monkeypatch)
    factory, _ = _factory()
    record = asyncio.run(ei.process_email(factory, object(), _mail(attachments=())))
    assert record["status"] == "rejected" and record["rejections"][0]["reason"] == "no attachments"


def test_each_email_is_handled_once(monkeypatch):
    store = _patch_upload(monkeypatch)
    factory, _ = _factory(already=True)
    assert asyncio.run(ei.process_email(factory, object(), _mail())) is None
    store.assert_not_awaited()


def test_other_mail_is_ignored_and_not_recorded(monkeypatch):
    store = _patch_upload(monkeypatch)
    factory, session = _factory()
    assert asyncio.run(ei.process_email(factory, object(), _mail(to="finance@demo.example.com"))) is None
    store.assert_not_awaited()
    session.execute.assert_not_awaited()


def test_message_without_id_gets_a_stable_one():
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = "a@b.example", "invoices@procurement.local", "no id"
    m.set_content("x")
    raw = m.as_bytes()
    first = ei.parse(raw).message_id
    assert first.startswith("<sha256-") and first == ei.parse(raw).message_id
    # stable across processes too (hash() would not be)
    import hashlib
    assert first == f"<sha256-{hashlib.sha256(raw).hexdigest()}>"
