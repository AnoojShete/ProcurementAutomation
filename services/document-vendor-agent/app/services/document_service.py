"""Orchestrates the extraction pipeline (see app/services/pipeline.py for
the actual agent chain: parsing -> classification -> field extraction ->
vendor matching -> duplicate detection -> confidence scoring) and persists
+ publishes the result.

Run by the background worker (app/worker.py) in response to a
document.ingested event; also exposed directly for GET/POST endpoints
that read or correct a document's extraction result.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, Vendor
from app.services import storage
from app.services import pipeline
from app.services import checkpoints as checkpoint_service
from app.services.audit import write_audit_log
from app.metrics import (
    document_processing_total,
    document_pipeline_stage_duration_seconds,
    extraction_confidence,
    vendor_matching_total,
)

logger = logging.getLogger(__name__)


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


async def process_document(db: AsyncSession, kafka_producer, document_id: str) -> Optional[Document]:
    doc = await db.get(Document, document_id)
    if doc is None:
        logger.warning(f"process_document: document {document_id} not found")
        return None

    doc.status = "processing"
    await db.flush()

    try:
        data = await storage.download_bytes(doc.minio_path)

        # The agent chain — see app/services/pipeline.py. Each stage reads
        # from and writes back to the same envelope dict, so the full
        # trace of what happened to this document is right there in one
        # object (and in the [agent_name] log lines each stage emits, plus
        # the typed AgentResult trail in envelope["_agent_trail"] — see
        # app/services/agent_contracts.py). Per-stage durations feed both
        # the Prometheus histogram below and the pipeline_checkpoints rows
        # persisted after the pipeline finishes.
        stage_durations_ms: dict = {}
        envelope = pipeline.new_envelope(doc.id, doc.original_filename or "")

        t0 = time.perf_counter()
        envelope = await pipeline.parsing_agent(envelope, data)
        stage_durations_ms["parsing_agent"] = _elapsed_ms(t0)

        t0 = time.perf_counter()
        envelope = pipeline.classification_agent(envelope)
        stage_durations_ms["classification_agent"] = _elapsed_ms(t0)

        t0 = time.perf_counter()
        envelope = pipeline.field_extraction_agent(envelope)
        stage_durations_ms["field_extraction_agent"] = _elapsed_ms(t0)

        # LayoutLMv3 cross-check: lazy, non-blocking — if the model isn't
        # loaded or fails, the pipeline continues and the field stays unset.
        t0 = time.perf_counter()
        envelope = pipeline.layoutlm_crosscheck_agent(envelope)
        stage_durations_ms["layoutlm_crosscheck_agent"] = _elapsed_ms(t0)

        t0 = time.perf_counter()
        envelope = await pipeline.vendor_matching_agent(db, kafka_producer, envelope, doc.uploaded_by)
        stage_durations_ms["vendor_matching_agent"] = _elapsed_ms(t0)

        t0 = time.perf_counter()
        envelope = await pipeline.duplicate_detection_agent(db, envelope)
        stage_durations_ms["duplicate_detection_agent"] = _elapsed_ms(t0)

        t0 = time.perf_counter()
        envelope = pipeline.confidence_agent(envelope)
        stage_durations_ms["confidence_agent"] = _elapsed_ms(t0)

        for stage, duration_ms in stage_durations_ms.items():
            document_pipeline_stage_duration_seconds.labels(stage=stage).observe(duration_ms / 1000)

        fields = envelope["extracted_fields"]
        vendor = await db.get(Vendor, envelope["vendor_id"])

        doc.document_type = envelope["document_type"]
        doc.vendor_id = envelope["vendor_id"]
        doc.vendor_name_raw = fields.get("vendor_name_raw")
        doc.document_number = fields.get("document_number")
        doc.document_date = _safe_date(fields.get("document_date"))
        doc.total = fields.get("total")
        doc.currency = fields.get("currency")
        doc.extracted = {
            "line_items": fields.get("line_items"),
            "total": fields.get("total"),
            "currency": fields.get("currency"),
            "document_number": fields.get("document_number"),
            "document_date": fields.get("document_date"),
            # Include cross-check result if available — surfaces both pipelines
            # side-by-side for the human reviewer when they disagree.
            "crosscheck": envelope.get("crosscheck_result"),
        }
        doc.confidence = envelope["confidence_scores"]
        doc.overall_confidence = envelope["overall_confidence"]
        doc.needs_review = envelope["needs_review"]
        doc.is_likely_duplicate = bool(envelope.get("is_duplicate"))
        doc.duplicate_of_document_id = envelope.get("duplicate_of_document_id")
        doc.status = "classified"
        doc.updated_at = datetime.now(timezone.utc)

        await db.commit()

        await checkpoint_service.write_checkpoints(
            db, doc.id, envelope.get("_agent_trail", []), stage_durations_ms
        )
        await db.commit()

        document_processing_total.labels(status="classified").inc()
        extraction_confidence.observe(envelope["overall_confidence"])
        vendor_matching_total.labels(match_type=envelope["vendor_match_type"]).inc()

        if kafka_producer is not None:
            await kafka_producer.publish_document_classified(
                document_id=doc.id, document_type=doc.document_type, vendor_name_raw=doc.vendor_name_raw,
                extracted_fields=doc.extracted, confidence_scores=doc.confidence,
                overall_confidence=doc.overall_confidence, needs_review=doc.needs_review,
            )
            await kafka_producer.publish_vendor_matched(
                document_id=doc.id, vendor_id=vendor.id, vendor_name_normalized=vendor.normalized_name,
                match_type=envelope["vendor_match_type"], match_confidence=envelope["vendor_match_confidence"],
            )

        return doc

    except Exception as e:
        logger.error(f"process_document failed for {document_id}: {e}", exc_info=True)
        doc.status = "failed"
        doc.error_message = str(e)
        doc.updated_at = datetime.now(timezone.utc)
        await db.commit()
        document_processing_total.labels(status="failed").inc()
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
