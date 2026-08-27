"""The document-processing pipeline, structured as a chain of small
"agents" that each take a plain, JSON-serializable **envelope** (dict) —
everything known about one document so far — and hand back an updated
envelope for the next agent. This is the same envelope-passing shape used
between *services* on the Kafka bus (see shared/schemas/events.md:
event_id/event_type/timestamp/source_service/payload) applied one level
down, inside a single service's own worker: parsing -> classification ->
field extraction -> vendor matching -> duplicate detection -> confidence
scoring, each stage logged so the flow is traceable, not a black box.

Nothing here changes behavior versus a plain sequence of function calls —
it's the same logic, just named and shaped so each step's inputs/outputs
are explicit and independently testable, and so a new stage (e.g.
swapping the parsing agent's backend) only ever touches its own function.
"""
import asyncio
import logging
from dataclasses import asdict
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Vendor
from app.services.ocr import extract_text
from app.services.classification import classify_document
from app.services.field_extraction import extract_fields
from app.services.vendor_matching import find_or_create_vendor
from app.services.duplicate_detection import check_duplicate_invoice
from app.services.confidence import build_confidence_scores, overall_confidence, needs_review
from app.services.vendor_payment_service import submit_payment_change, PAYMENT_FIELDS

logger = logging.getLogger(__name__)


def new_envelope(document_id: str, filename: str) -> dict:
    """The envelope every agent below reads from and writes back to.
    Deliberately a plain dict (not a dataclass/pydantic model) — the point
    is that it's the same shape a Kafka payload would be, so it could be
    logged, persisted, or literally published as an event with no
    conversion step."""
    return {"document_id": document_id, "filename": filename}


async def parsing_agent(envelope: dict, data: bytes) -> dict:
    """Turns raw file bytes into text. See app/services/ocr.py for the
    actual backend (Docling for PDFs, pytesseract for images).

    extract_text() is CPU-bound and synchronous — Docling's layout/table
    inference on a real PDF took 15-75s in testing. Run directly in this
    coroutine, that blocks the whole worker's event loop for the duration,
    starving the Kafka consumer's heartbeat and forcing a rebalance on
    every single document. asyncio.to_thread hands it to a worker thread
    instead, so heartbeats (and any other pipeline concurrency) keep
    flowing while the conversion runs."""
    extraction = await asyncio.to_thread(
        extract_text, data, envelope["filename"], envelope.get("content_type", "")
    )
    envelope["raw_text"] = extraction.text
    envelope["extraction_method"] = extraction.method
    envelope["file_type"] = extraction.file_type
    envelope["text_quality"] = extraction.text_quality
    logger.info(
        f"[parsing_agent] document_id={envelope['document_id']} "
        f"method={extraction.method} file_type={extraction.file_type} text_quality={extraction.text_quality}"
    )
    return envelope


def classification_agent(envelope: dict) -> dict:
    """Labels the document PO / invoice / quote from its text."""
    result = classify_document(envelope["raw_text"])
    envelope["document_type"] = result.document_type
    envelope["classification_confidence"] = result.confidence
    envelope["classification_scores"] = result.scores
    logger.info(
        f"[classification_agent] document_id={envelope['document_id']} "
        f"type={result.document_type} confidence={result.confidence}"
    )
    return envelope


def field_extraction_agent(envelope: dict) -> dict:
    """Pulls vendor name, line items, totals, dates, document numbers, and
    (when present) vendor bank/payment details out of the text."""
    fields, field_conf = extract_fields(envelope["raw_text"])
    envelope["extracted_fields"] = asdict(fields)
    envelope["field_confidences"] = asdict(field_conf)
    logger.info(
        f"[field_extraction_agent] document_id={envelope['document_id']} "
        f"vendor_name_raw={fields.vendor_name_raw!r} total={fields.total} doc_number={fields.document_number}"
    )
    return envelope


async def vendor_matching_agent(db: AsyncSession, kafka_producer, envelope: dict, uploaded_by: Optional[str]) -> dict:
    """Fuzzy-matches the extracted vendor name against the shared vendors
    table (or creates a new vendor), and — the BEC-fraud governance
    control — routes any bank/payment-detail change on an EXISTING vendor
    into the dual-control pending-verification queue instead of updating
    the live record directly."""
    fields = envelope["extracted_fields"]
    match = await find_or_create_vendor(db, fields.get("vendor_name_raw") or "")
    vendor = match.vendor

    payment_fields_present = any(fields.get(f) for f in PAYMENT_FIELDS)
    if match.match_type == "existing" and payment_fields_present:
        await submit_payment_change(
            db, kafka_producer, vendor,
            new_bank_account=fields.get("bank_account_number"),
            new_routing=fields.get("routing_code"),
            new_beneficiary=fields.get("payment_beneficiary_name"),
            submitted_by=uploaded_by or "document-vendor-agent:worker",
            source="document",
            document_id=envelope["document_id"],
        )
        envelope["payment_change_flagged"] = True
    elif match.match_type == "new":
        vendor.bank_account_number = fields.get("bank_account_number")
        vendor.routing_code = fields.get("routing_code")
        vendor.payment_beneficiary_name = fields.get("payment_beneficiary_name")
        envelope["payment_change_flagged"] = False
    else:
        envelope["payment_change_flagged"] = False

    envelope["vendor_id"] = vendor.id
    envelope["vendor_name_normalized"] = vendor.normalized_name
    envelope["vendor_match_type"] = match.match_type
    envelope["vendor_match_confidence"] = match.match_confidence
    logger.info(
        f"[vendor_matching_agent] document_id={envelope['document_id']} "
        f"vendor_id={vendor.id} match_type={match.match_type} confidence={match.match_confidence}"
    )
    return envelope


async def duplicate_detection_agent(db: AsyncSession, envelope: dict) -> dict:
    """Fuzzy-matches a new invoice against existing ones for the same
    vendor on (amount tolerance, date window, document-number similarity)
    instead of silently accepting a possible duplicate."""
    if envelope["document_type"] != "invoice":
        envelope["is_duplicate"] = False
        envelope["duplicate_of_document_id"] = None
        return envelope

    fields = envelope["extracted_fields"]
    result = await check_duplicate_invoice(
        db, vendor_id=envelope["vendor_id"], total=fields.get("total"),
        document_date_str=fields.get("document_date"), document_number=fields.get("document_number"),
        exclude_document_id=envelope["document_id"],
    )
    envelope["is_duplicate"] = result.is_duplicate
    envelope["duplicate_of_document_id"] = result.duplicate_of_document_id
    if result.is_duplicate:
        logger.info(f"[duplicate_detection_agent] document_id={envelope['document_id']} likely duplicate of {result.duplicate_of_document_id}")
    return envelope


def confidence_agent(envelope: dict) -> dict:
    """Combines classification + per-field + text-quality confidence into
    one overall score and the needs_review decision. A likely duplicate
    is always capped below the review threshold — a human always sees it,
    confidence score notwithstanding."""
    field_conf = envelope["field_confidences"]
    confidence_scores = build_confidence_scores(
        classification_confidence=envelope["classification_confidence"],
        field_confidences={
            "vendor_name": field_conf["vendor_name"],
            "document_number": field_conf["document_number"],
            "document_date": field_conf["document_date"],
            "total": field_conf["total"],
            "line_items": field_conf["line_items"],
        },
        text_quality=envelope["text_quality"],
    )
    overall = overall_confidence(confidence_scores)
    if envelope.get("is_duplicate"):
        overall = min(overall, 0.5)

    envelope["confidence_scores"] = confidence_scores
    envelope["overall_confidence"] = overall
    envelope["needs_review"] = needs_review(overall) or bool(envelope.get("is_duplicate"))
    logger.info(
        f"[confidence_agent] document_id={envelope['document_id']} "
        f"overall_confidence={overall} needs_review={envelope['needs_review']}"
    )
    return envelope
