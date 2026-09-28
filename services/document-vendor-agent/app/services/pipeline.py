"""The document-processing pipeline, structured as a chain of small
"agents" that each take a plain, JSON-serializable **envelope** (dict) —
everything known about one document so far — and hand back an updated
envelope for the next agent. This is the same envelope-passing shape used
between *services* on the Kafka bus (see shared/schemas/events.md:
event_id/event_type/timestamp/source_service/payload) applied one level
down, inside a single service's own worker: parsing -> classification ->
field extraction -> LayoutLMv3 cross-check -> vendor matching ->
duplicate detection -> confidence scoring, each stage logged.

Nothing here changes behavior versus a plain sequence of function calls —
it's the same logic, just named and shaped so each step's inputs/outputs
are explicit and independently testable, and so a new stage (e.g.
swapping the parsing agent's backend) only ever touches its own function.
"""
import asyncio
import re
import logging
from shared.rules_engine import get_rule
from app.services.audit import write_audit_log
import uuid
from datetime import datetime, timezone
from dataclasses import asdict
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Vendor
from app.services.classification import classify_document
from app.services.field_extraction import extract_fields
from app.services.vendor_matching import find_or_create_vendor
from app.services.duplicate_detection import check_duplicate_invoice
from app.services.confidence import build_confidence_scores, overall_confidence, needs_review
from app.services.vendor_payment_service import submit_payment_change, PAYMENT_FIELDS
from app.services.agent_contracts import record_agent_result

logger = logging.getLogger(__name__)


def new_envelope(document_id: str, filename: str) -> dict:
    """The envelope every agent below reads from and writes back to.
    Deliberately a plain dict (not a dataclass/pydantic model) — the point
    is that it's the same shape a Kafka payload would be, so it could be
    logged, persisted, or literally published as an event with no
    conversion step."""
    return {"document_id": document_id, "filename": filename}


async def parsing_agent(db: AsyncSession, envelope: dict, data: bytes) -> dict:
    from app.services.extraction_router import route_extraction
    
    route_result = await route_extraction(db, envelope["document_id"], data, envelope["filename"], envelope.get("content_type", ""))
    extraction = route_result.extraction_result
    
    envelope["raw_text"] = extraction.text
    envelope["extraction_method"] = extraction.method
    envelope["file_type"] = extraction.file_type
    envelope["text_quality"] = extraction.text_quality
    envelope["words_with_boxes"] = extraction.words_with_boxes or []
    envelope["raw_image_bytes"] = data if extraction.file_type == "image" else None
    
    envelope["model_used"] = route_result.model_used
    envelope["fallback_triggered"] = route_result.fallback_triggered
    envelope["route_name"] = route_result.route_name

    logger.info(
        f"[parsing_agent] document_id={envelope['document_id']} "
        f"route={route_result.route_name} model_used={route_result.model_used} "
        f"fallback={route_result.fallback_triggered} "
        f"text_quality={extraction.text_quality} words={len(extraction.words_with_boxes or [])}"
    )
    is_empty = not (extraction.text or "").strip()
    record_agent_result(
        envelope, "parsing_agent",
        confidence=extraction.text_quality,
        validation_status="invalid" if is_empty else "valid",
        errors=["empty extraction: no text recovered from document"] if is_empty else [],
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
    record_agent_result(envelope, "classification_agent", confidence=result.confidence)
    return envelope


def field_extraction_agent(envelope: dict) -> dict:
    """Pulls vendor name, line items, totals, dates, document numbers, and
    (when present) vendor bank/payment details out of the text.

    Does not blindly trust parsing_agent's output: if the upstream stage
    already flagged an empty extraction, field extraction still runs but
    is recorded as needs_review rather than valid."""
    upstream = envelope.get("_agent_trail", [])
    upstream_invalid = bool(upstream) and upstream[-1].validation_status == "invalid"

    doc_type = envelope.get("document_type", "invoice")
    fields, field_conf = extract_fields(envelope["raw_text"], document_type=doc_type)
    envelope["extracted_fields"] = fields.to_dict(document_type=doc_type)
    envelope["field_confidences"] = asdict(field_conf)
    logger.info(
        f"[field_extraction_agent] document_id={envelope['document_id']} "
        f"vendor_name_raw={fields.vendor_name_raw!r} total={fields.total} doc_number={fields.document_number}"
    )
    record_agent_result(
        envelope, "field_extraction_agent",
        validation_status="needs_review" if upstream_invalid else "valid",
        warnings=["upstream parsing_agent output was invalid (empty text)"] if upstream_invalid else [],
    )
    return envelope


def layoutlm_crosscheck_agent(envelope: dict) -> dict:
    """Second, independent extraction pass using LayoutLMv3
    (ngvozdenovic/invoice_extraction). Loaded lazily — if the model isn't
    available or fails to load, this agent skips and logs a WARNING but
    never blocks the pipeline.

    If vendor_name, total, or invoice_number disagree between Docling and
    LayoutLMv3, sets needs_review_forced=True and stores both results
    side-by-side in envelope["crosscheck_result"] so the reviewer sees
    exactly what each pipeline found.
    """
    try:
        from app.services.layoutlm_crosscheck import run_crosscheck

        words_with_boxes = envelope.get("words_with_boxes", [])
        words = [w["word"] for w in words_with_boxes]
        boxes = [w.get("box", [0, 0, 0, 0]) for w in words_with_boxes]
        page_w = words_with_boxes[0].get("page_w", 1000) if words_with_boxes else 1000
        page_h = words_with_boxes[0].get("page_h", 1000) if words_with_boxes else 1000

        fields = envelope.get("extracted_fields", {})
        result = run_crosscheck(
            image_bytes=envelope.get("raw_image_bytes"),
            docling_words=words,
            docling_boxes=boxes,
            page_width=page_w,
            page_height=page_h,
            docling_vendor_name=fields.get("vendor_name_raw"),
            docling_total=fields.get("total"),
            docling_invoice_num=fields.get("document_number"),
        )

        envelope["crosscheck_result"] = {
            "available": result.available,
            "disagrees": result.disagrees,
            "docling_fields": result.docling_fields,
            "layoutlm_fields": result.layoutlm_fields,
            "disagreement_details": result.disagreement_details,
        }

        if result.disagrees:
            envelope["needs_review_forced"] = True
            logger.info(
                f"[layoutlm_crosscheck_agent] document_id={envelope['document_id']} "
                f"DISAGREES on: {list(result.disagreement_details.keys())}"
            )
            record_agent_result(
                envelope, "layoutlm_crosscheck_agent",
                validation_status="needs_review",
                warnings=[f"pipeline disagreement on: {list(result.disagreement_details.keys())}"],
            )
        else:
            status = "skipped_model_unavailable" if not result.available else "valid"
            logger.info(
                f"[layoutlm_crosscheck_agent] document_id={envelope['document_id']} "
                f"result={result.agreement_rate_note}"
            )
            record_agent_result(envelope, "layoutlm_crosscheck_agent",
                                validation_status=status,
                                next_action="skipped_model_unavailable" if not result.available else "continue")

    except Exception as e:
        logger.warning(f"[layoutlm_crosscheck_agent] failed (non-fatal): {e}", exc_info=True)
        envelope["crosscheck_result"] = {"available": False, "disagrees": False, "error": str(e)}
        try:
            record_agent_result(envelope, "layoutlm_crosscheck_agent",
                                validation_status="skipped_error",
                                next_action="skipped_error",
                                warnings=[f"crosscheck error: {e}"])
        except Exception:
            pass

    return envelope


async def vendor_matching_agent(db: AsyncSession, kafka_producer, envelope: dict, uploaded_by: Optional[str]) -> dict:
    """Fuzzy-matches the extracted vendor name against the shared vendors
    table (or creates a new vendor), and — the BEC-fraud governance
    control — routes any bank/payment-detail change on an EXISTING vendor
    into the dual-control pending-verification queue instead of updating
    the live record directly."""
    fields = envelope["extracted_fields"]
    if not (fields.get("vendor_name_raw") or "").strip():
        # No vendor name to go on: leave the document without a vendor for
        # a reviewer to set, rather than filing it under a catch-all
        # "Unknown Vendor" that then gets risk-scored and matched against.
        envelope.update(vendor_id=None, vendor_name_normalized=None, vendor_match_type="none",
                        vendor_match_confidence=0.0, payment_change_flagged=False,
                        payment_hold=False, payment_hold_reason=None, needs_review_forced=True)
        logger.info(f"[vendor_matching_agent] document_id={envelope['document_id']} no vendor name extracted")
        record_agent_result(envelope, "vendor_matching_agent", confidence=0.0, validation_status="needs_review",
                            warnings=["no vendor name found in the document"])
        return envelope
    match = await find_or_create_vendor(db, fields.get("vendor_name_raw") or "")
    vendor = match.vendor

    is_quote = envelope.get("document_type") == "quote"
    payment_fields_present = any(fields.get(f) for f in PAYMENT_FIELDS)
    envelope["payment_change_flagged"] = False
    if payment_fields_present and not is_quote:
        # Bank details from a document are never trusted directly — not for
        # an existing vendor (a change) and not for a vendor seen for the
        # first time either. Both go to the dual-control verification queue;
        # a first-seen vendor has no live details until someone verifies.
        change = await submit_payment_change(
            db, kafka_producer, vendor,
            new_bank_account=fields.get("bank_account_number"),
            new_routing=fields.get("routing_code"),
            new_beneficiary=fields.get("payment_beneficiary_name"),
            submitted_by=uploaded_by or "document-vendor-agent:worker",
            source="document" if match.match_type == "existing" else "document_first_seen",
            document_id=envelope["document_id"],
        )
        envelope["payment_change_flagged"] = change is not None

    # Lookalike vendor: a new vendor whose name is close to — but not close
    # enough to match — an existing one ("Del1 Technologies" vs "Dell
    # Technologies"). Combined with bank details, that's the classic
    # invoice-redirection setup.
    lookalike = None
    lookalike_min = float(get_rule("vendor.lookalike_min_similarity", fallback=70))
    if match.match_type == "new" and match.closest_existing is not None and match.closest_score >= lookalike_min:
        lookalike = {
            "vendor_id": str(match.closest_existing.id),
            "vendor_name": match.closest_existing.name,
            "similarity": round(match.closest_score / 100, 3),
            "bank_details_differ": bool(payment_fields_present and (
                fields.get("bank_account_number") != match.closest_existing.bank_account_number
            )),
        }
        envelope["lookalike_vendor"] = lookalike
        envelope["needs_review_forced"] = True
        await write_audit_log(
            db, entity_type="vendor", entity_id=vendor.id, action="lookalike_vendor_detected",
            payload={"document_id": envelope["document_id"], "new_vendor_name": vendor.name, **lookalike},
        )

    # Payment hold: an invoice isn't payable while its vendor's bank
    # details are unverified, or while the vendor looks like an impostor.
    hold_reasons = []
    if envelope.get("document_type") == "invoice":
        if vendor.payment_details_pending_verification:
            hold_reasons.append("vendor bank details awaiting verification")
        if lookalike:
            hold_reasons.append(f"vendor name resembles existing vendor '{lookalike['vendor_name']}'")
    envelope["payment_hold"] = bool(hold_reasons)
    envelope["payment_hold_reason"] = "; ".join(hold_reasons) or None

    if is_quote:
        from app.models import VendorQuote
        from dateutil import parser as d_parser
        valid_until_str = fields.get("valid_until")
        v_date = None
        if valid_until_str:
            try:
                v_date = d_parser.parse(valid_until_str).date()
            except Exception:
                pass
        quote = VendorQuote(
            id=str(uuid.uuid4()),
            document_id=envelope["document_id"],
            vendor_id=vendor.id,
            quote_number=fields.get("quote_number") or fields.get("document_number"),
            valid_until=v_date,
            total=fields.get("total"),
            currency=fields.get("currency") or "INR",
            line_items=fields.get("line_items") or [],
            is_binding=False,
            raw_text=envelope.get("raw_text"),
            created_at=datetime.now(timezone.utc),
        )
        db.add(quote)
        await db.flush()
        logger.info(f"[vendor_matching_agent] Saved quote {quote.quote_number} to vendor_quotes table")

    envelope["vendor_id"] = vendor.id
    envelope["vendor_name_normalized"] = vendor.normalized_name
    envelope["vendor_match_type"] = match.match_type
    envelope["vendor_match_confidence"] = match.match_confidence
    logger.info(
        f"[vendor_matching_agent] document_id={envelope['document_id']} "
        f"vendor_id={vendor.id} match_type={match.match_type} confidence={match.match_confidence}"
    )
    vendor_name_missing = not (fields.get("vendor_name_raw") or "").strip()
    if vendor_name_missing:
        envelope["needs_review_forced"] = True
    warnings = ["no vendor name extracted upstream; matched against an empty name"] if vendor_name_missing else []
    if lookalike:
        warnings.append(f"lookalike of existing vendor {lookalike['vendor_name']} ({lookalike['similarity']:.0%})")
    record_agent_result(
        envelope, "vendor_matching_agent",
        confidence=match.match_confidence,
        validation_status="needs_review" if (vendor_name_missing or lookalike) else "valid",
        warnings=warnings,
    )
    return envelope


class LedgerUnavailableError(Exception):
    """The invoice ledger couldn't be reached (or failed on its side).
    Not caught here: process_document puts the whole document back in the
    queue (its partial results rolled back) instead of filing the invoice
    as "unmatched" and never looking at it again once the ledger is back."""


_PO_REF = re.compile(r"\b(?:PO|Purchase\s+Order)\s*(?:Ref(?:erence)?|No\.?|Number|#)?\s*[:#]?\s*(PO-[0-9A-F]{8})\b", re.IGNORECASE)


def find_po_reference(text: str) -> Optional[str]:
    """The platform's own PO number ("PO-9E085E38") if the invoice quotes it."""
    m = _PO_REF.search(text or "")
    return m.group(1).upper() if m else None


async def invoice_matching_agent(db: AsyncSession, kafka_producer, envelope: dict) -> dict:
    """Three-way match through approval-inventory-agent's invoice ledger
    (POST /invoices/match): line quantities and unit prices against what is
    still left to invoice on the vendor's approved/fulfilled requests, with
    overbilling always flagged. The ledger books the match and moves the
    request in its own transaction; invoice.matched is then emitted for
    downstream consumers."""
    if envelope.get("document_type") != "invoice":
        envelope["unmatched_invoice"] = False
        record_agent_result(envelope, "invoice_matching_agent", next_action="skipped_non_invoice")
        return envelope

    fields = envelope.get("extracted_fields", {})
    invoice_total = fields.get("total")
    vendor_id = envelope.get("vendor_id")

    if invoice_total is None or not vendor_id:
        envelope["unmatched_invoice"] = True
        envelope["needs_review_forced"] = True
        record_agent_result(
            envelope, "invoice_matching_agent",
            validation_status="needs_review",
            warnings=["cannot match PO: missing invoice total or vendor_id"],
        )
        return envelope

    import os
    import httpx
    from shared.auth.jwt_tokens import create_access_token

    approval_svc_url = os.environ.get("APPROVAL_INVENTORY_URL", "http://approval-inventory-agent:8002").rstrip("/")
    service_token = create_access_token(
        "document-vendor-agent", "document-vendor-agent@service.internal", "service",
    )
    invoice_num = fields.get("invoice_number") or fields.get("document_number")
    body = {
        "document_id": str(envelope["document_id"]),
        "vendor_id": str(vendor_id),
        "invoice_number": invoice_num,
        "total": float(invoice_total),
        "lines": [
            {"description": li.get("description") or "", "quantity": li["quantity"], "unit_price": li["unit_price"]}
            for li in (fields.get("line_items") or [])
            if li.get("quantity") and li.get("unit_price") is not None
        ],
        "payment_hold": bool(envelope.get("payment_hold")),
        "hold_reason": envelope.get("payment_hold_reason"),
        "po_reference": find_po_reference(envelope.get("raw_text") or ""),
    }
    result = None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{approval_svc_url}/invoices/match", json=body,
                headers={"Authorization": f"Bearer {service_token}"},
            )
    except httpx.HTTPError as e:
        # Couldn't reach it (down, restarting, timed out): retry later.
        raise LedgerUnavailableError(f"invoice ledger unreachable: {e}") from e
    if resp.status_code >= 500:
        raise LedgerUnavailableError(f"invoice ledger returned HTTP {resp.status_code}")
    if resp.status_code == 200:
        result = resp.json().get("data")
    else:
        # A 4xx won't change on retry: send the invoice to review.
        logger.warning(f"[invoice_matching_agent] ledger rejected the request: HTTP {resp.status_code}: {resp.text[:200]}")

    envelope["matched_po_number"] = None
    envelope["matched_po_id"] = None
    fields["matched_po_number"] = None
    if result is None:
        envelope["unmatched_invoice"] = True
        envelope["needs_review_forced"] = True
        record_agent_result(envelope, "invoice_matching_agent", validation_status="needs_review",
                            warnings=["invoice ledger rejected the match request"])
        return envelope

    status = result.get("status")
    envelope["invoice_match"] = {
        "status": status, "purchase_request_id": result.get("request_id"), "issues": result.get("issues", []),
        "remaining_before": result.get("remaining_before"), "remaining_after": result.get("remaining_after"),
        "allocations": result.get("allocations", []),
    }
    if status in ("matched", "partial"):
        po_id = result["request_id"]
        po_num = f"PO-{po_id[:8].upper()}"
        envelope.update(matched_po_number=po_num, matched_po_id=po_id, unmatched_invoice=False)
        fields["matched_po_number"] = po_num
        fields["matched_po_id"] = po_id
        if kafka_producer is not None:
            await kafka_producer.publish_invoice_matched(
                document_id=envelope["document_id"], invoice_number=invoice_num or "UNKNOWN",
                purchase_request_id=po_id, po_number=po_num, vendor_id=vendor_id,
                invoice_total=invoice_total, po_total=result.get("remaining_before") or invoice_total,
            )
        logger.info(f"[invoice_matching_agent] {status}: {po_num} ({po_id}), remaining {result.get('remaining_after')}")
        record_agent_result(envelope, "invoice_matching_agent", validation_status="valid")
    elif status == "ambiguous":
        envelope["unmatched_invoice"] = False
        envelope["needs_review_forced"] = True
        envelope["candidate_pos"] = result.get("candidates", [])
        record_agent_result(envelope, "invoice_matching_agent", validation_status="needs_review",
                            warnings=result.get("issues", []))
    elif status == "variance":
        # Looks like a known PO but doesn't fit it: overbilled price or
        # quantity, or more than is left to invoice. Never auto-accepted.
        envelope["unmatched_invoice"] = False
        envelope["needs_review_forced"] = True
        envelope["invoice_variance"] = result.get("issues", [])
        record_agent_result(envelope, "invoice_matching_agent", validation_status="needs_review",
                            warnings=result.get("issues", []))
    else:
        envelope["unmatched_invoice"] = True
        envelope["needs_review_forced"] = True
        record_agent_result(envelope, "invoice_matching_agent", validation_status="needs_review",
                            warnings=result.get("issues", []) or ["no purchase request matched"])
    return envelope


async def duplicate_detection_agent(db: AsyncSession, envelope: dict) -> dict:
    """Fuzzy-matches a new invoice against existing ones for the same
    vendor on (amount tolerance, date window, document-number similarity)
    instead of silently accepting a possible duplicate."""
    if envelope["document_type"] != "invoice":
        envelope["is_duplicate"] = False
        envelope["duplicate_of_document_id"] = None
        record_agent_result(envelope, "duplicate_detection_agent", next_action="skipped_non_invoice")
        return envelope

    fields = envelope["extracted_fields"]
    if envelope.get("vendor_id"):
        # Several documents are processed at once. Without this, two copies
        # of the same invoice processed side by side each look for a
        # duplicate before the other is saved, and neither is flagged. The
        # lock is per vendor and held until this document's results commit,
        # so the second copy checks after the first is visible.
        from sqlalchemy import text as _sql
        await db.execute(_sql("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                         {"k": f"duplicate-check:{envelope['vendor_id']}"})
    result = await check_duplicate_invoice(
        db, vendor_id=envelope["vendor_id"], total=fields.get("total"),
        document_date_str=fields.get("document_date"), document_number=fields.get("document_number"),
        exclude_document_id=envelope["document_id"],
    )
    envelope["is_duplicate"] = result.is_duplicate
    envelope["duplicate_of_document_id"] = result.duplicate_of_document_id
    if result.is_duplicate:
        logger.info(f"[duplicate_detection_agent] document_id={envelope['document_id']} likely duplicate of {result.duplicate_of_document_id}")
    record_agent_result(
        envelope, "duplicate_detection_agent",
        validation_status="needs_review" if result.is_duplicate else "valid",
        warnings=[f"likely duplicate of {result.duplicate_of_document_id}"] if result.is_duplicate else [],
    )
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
    calibrated = (envelope.get("review_threshold") or {}).get("threshold")
    envelope["needs_review"] = (
        needs_review(overall, calibrated)
        or bool(envelope.get("is_duplicate"))
        or bool(envelope.get("needs_review_forced"))
        or bool(envelope.get("unmatched_invoice"))
    )
    logger.info(
        f"[confidence_agent] document_id={envelope['document_id']} "
        f"overall_confidence={overall} needs_review={envelope['needs_review']}"
    )
    record_agent_result(
        envelope, "confidence_agent",
        confidence=overall,
        validation_status="needs_review" if envelope["needs_review"] else "valid",
    )
    return envelope
