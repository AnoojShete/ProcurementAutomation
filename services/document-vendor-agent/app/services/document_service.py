"""The extraction pipeline: OCR/text extraction -> classification -> field
extraction -> vendor matching/dedup -> duplicate-invoice detection ->
confidence scoring -> persist + publish document.classified/vendor.matched.

Run by the background worker (app/worker.py) in response to a
document.ingested event; also exposed directly for GET/POST endpoints
that read or correct a document's extraction result.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, Vendor
from app.services import storage
from app.services.ocr import extract_text
from app.services.classification import classify_document
from app.services.field_extraction import extract_fields
from app.services.vendor_matching import find_or_create_vendor
from app.services.duplicate_detection import check_duplicate_invoice
from app.services.confidence import build_confidence_scores, overall_confidence, needs_review
from app.services.vendor_payment_service import submit_payment_change, PAYMENT_FIELDS
from app.services.audit import write_audit_log

logger = logging.getLogger(__name__)


async def process_document(db: AsyncSession, kafka_producer, document_id: str) -> Optional[Document]:
    doc = await db.get(Document, document_id)
    if doc is None:
        logger.warning(f"process_document: document {document_id} not found")
        return None

    doc.status = "processing"
    await db.flush()

    try:
        data = await storage.download_bytes(doc.minio_path)
        extraction = extract_text(data, doc.original_filename or "", "")
        classification = classify_document(extraction.text)
        fields, field_conf = extract_fields(extraction.text)

        confidence_scores = build_confidence_scores(
            classification_confidence=classification.confidence,
            field_confidences={
                "vendor_name": field_conf.vendor_name,
                "document_number": field_conf.document_number,
                "document_date": field_conf.document_date,
                "total": field_conf.total,
                "line_items": field_conf.line_items,
            },
            text_quality=extraction.text_quality,
        )
        overall = overall_confidence(confidence_scores)

        vendor_match = await find_or_create_vendor(db, fields.vendor_name_raw or "")
        vendor = vendor_match.vendor

        # BEC-fraud control: a change to an EXISTING vendor's bank/payment
        # details, however it arrives (here: derived from an uploaded
        # document), never updates the live field directly.
        if vendor_match.match_type == "existing" and any(getattr(fields, f) for f in PAYMENT_FIELDS):
            await submit_payment_change(
                db, kafka_producer, vendor,
                new_bank_account=fields.bank_account_number,
                new_routing=fields.routing_code,
                new_beneficiary=fields.payment_beneficiary_name,
                submitted_by=doc.uploaded_by or "document-vendor-agent:worker",
                source="document",
                document_id=doc.id,
            )
        elif vendor_match.match_type == "new":
            # No prior live value to protect for a brand-new vendor.
            vendor.bank_account_number = fields.bank_account_number
            vendor.routing_code = fields.routing_code
            vendor.payment_beneficiary_name = fields.payment_beneficiary_name

        duplicate_result = None
        if classification.document_type == "invoice":
            duplicate_result = await check_duplicate_invoice(
                db, vendor_id=vendor.id, total=fields.total, document_date_str=fields.document_date,
                document_number=fields.document_number, exclude_document_id=doc.id,
            )
            if duplicate_result.is_duplicate:
                overall = min(overall, 0.5)  # always route likely duplicates to a human

        needs_review_flag = needs_review(overall) or bool(duplicate_result and duplicate_result.is_duplicate)

        doc.document_type = classification.document_type
        doc.vendor_id = vendor.id
        doc.vendor_name_raw = fields.vendor_name_raw
        doc.document_number = fields.document_number
        doc.document_date = _safe_date(fields.document_date)
        doc.total = fields.total
        doc.currency = fields.currency
        doc.extracted = {
            "line_items": fields.line_items,
            "total": fields.total,
            "currency": fields.currency,
            "document_number": fields.document_number,
            "document_date": fields.document_date,
        }
        doc.confidence = confidence_scores
        doc.overall_confidence = overall
        doc.needs_review = needs_review_flag
        doc.is_likely_duplicate = bool(duplicate_result and duplicate_result.is_duplicate)
        doc.duplicate_of_document_id = duplicate_result.duplicate_of_document_id if duplicate_result else None
        doc.status = "classified"
        doc.updated_at = datetime.now(timezone.utc)

        await db.commit()

        if kafka_producer is not None:
            await kafka_producer.publish_document_classified(
                document_id=doc.id, document_type=doc.document_type, vendor_name_raw=doc.vendor_name_raw,
                extracted_fields=doc.extracted, confidence_scores=confidence_scores,
                overall_confidence=overall, needs_review=needs_review_flag,
            )
            await kafka_producer.publish_vendor_matched(
                document_id=doc.id, vendor_id=vendor.id, vendor_name_normalized=vendor.normalized_name,
                match_type=vendor_match.match_type, match_confidence=vendor_match.match_confidence,
            )

        return doc

    except Exception as e:
        logger.error(f"process_document failed for {document_id}: {e}", exc_info=True)
        doc.status = "failed"
        doc.error_message = str(e)
        doc.updated_at = datetime.now(timezone.utc)
        await db.commit()
        return doc


def _safe_date(value: Optional[str]):
    if not value:
        return None
    try:
        from datetime import date
        return date.fromisoformat(value)
    except ValueError:
        return None


async def get_document(db: AsyncSession, document_id: str) -> Optional[Document]:
    return await db.get(Document, document_id)


async def list_all_documents(db: AsyncSession, limit: int = 100) -> List[Document]:
    """Every document regardless of status, most recently uploaded first —
    backs the tracking dashboard."""
    result = await db.execute(select(Document).order_by(Document.uploaded_at.desc().nulls_last()).limit(limit))
    return list(result.scalars().all())


async def list_review_queue(db: AsyncSession, limit: int = 50) -> List[Document]:
    result = await db.execute(
        select(Document).where(Document.needs_review == True).order_by(Document.created_at.desc()).limit(limit)  # noqa: E712
    )
    return list(result.scalars().all())


async def submit_review(db: AsyncSession, kafka_producer, document_id: str, correction) -> Optional[Document]:
    """Apply a human correction: overwrite the corrected fields, mark every
    corrected field's confidence at 1.0 (human-verified), flip
    needs_review to false, and re-publish document.classified so
    downstream consumers see the corrected record."""
    doc = await db.get(Document, document_id)
    if doc is None:
        return None

    if correction.document_type:
        doc.document_type = correction.document_type

    extracted = dict(doc.extracted or {})
    confidence = dict(doc.confidence or {})

    if correction.vendor_name:
        doc.vendor_name_raw = correction.vendor_name
        confidence["vendor_name"] = 1.0
        vendor_match = await find_or_create_vendor(db, correction.vendor_name)
        doc.vendor_id = vendor_match.vendor.id

    if correction.extracted_fields:
        for key, value in correction.extracted_fields.items():
            extracted[key] = value
            confidence[key] = 1.0
        if "total" in correction.extracted_fields:
            doc.total = correction.extracted_fields["total"]
        if "currency" in correction.extracted_fields:
            doc.currency = correction.extracted_fields["currency"]
        if "document_number" in correction.extracted_fields:
            doc.document_number = correction.extracted_fields["document_number"]
        if "document_date" in correction.extracted_fields:
            doc.document_date = _safe_date(correction.extracted_fields["document_date"])

    doc.extracted = extracted
    doc.confidence = confidence
    doc.overall_confidence = 1.0
    doc.needs_review = False
    doc.status = "classified"
    doc.reviewed_by = correction.reviewed_by
    doc.reviewed_at = datetime.now(timezone.utc)
    doc.updated_at = datetime.now(timezone.utc)

    await db.commit()

    await write_audit_log(
        db, entity_type="document", entity_id=doc.id, action="human_review_correction",
        payload={"reviewed_by": correction.reviewed_by, "notes": correction.notes, "corrected_fields": list((correction.extracted_fields or {}).keys())},
    )
    await db.commit()

    if kafka_producer is not None:
        await kafka_producer.publish_document_classified(
            document_id=doc.id, document_type=doc.document_type, vendor_name_raw=doc.vendor_name_raw,
            extracted_fields=doc.extracted, confidence_scores=doc.confidence,
            overall_confidence=doc.overall_confidence, needs_review=doc.needs_review,
        )

    return doc
