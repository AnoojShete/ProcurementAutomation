"""Document extraction router handling explicit primary and fallback models."""
import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from app.models import ModelRoutingLog
from app.services.ocr import DocumentUnreadableError, ExtractionResult, extract_text_isolated
from app.metrics import model_routing_total
from shared.rules_engine import get_rule

logger = logging.getLogger(__name__)


@dataclass
class ExtractionRoutingResult:
    route_name: str          # "docling_text" | "docling_paddleocr" | "layoutlmv3_fallback"
    model_used: str          # "docling" | "paddleocr" | "layoutlmv3"
    fallback_triggered: bool
    fallback_reason: Optional[str]  # "exception" | "timeout" | "low_confidence"
    confidence: float        # text_quality from extraction
    extraction_result: ExtractionResult
    duration_ms: float


def _log_to_db(db: AsyncSession, document_id: str, result: ExtractionRoutingResult):
    try:
        log_entry = ModelRoutingLog(
            id=str(uuid.uuid4()),
            document_id=document_id,
            route_name=result.route_name,
            model_used=result.model_used,
            fallback_triggered=result.fallback_triggered,
            fallback_reason=result.fallback_reason,
            confidence=result.confidence,
            duration_ms=result.duration_ms,
            created_at=datetime.now(timezone.utc),
        )
        db.add(log_entry)
    except Exception as e:
        logger.warning(f"Could not persist ModelRoutingLog: {e}")

    try:
        model_routing_total.labels(
            service="document-vendor-agent",
            route_name=result.route_name,
            model_used=result.model_used,
            fallback_triggered=str(result.fallback_triggered).lower()
        ).inc()
    except Exception:
        pass


def _extraction_timeout() -> int:
    from app.config import load_extraction_config
    return int(load_extraction_config().get("timeout_seconds", 120))


def _layoutlm_image_fallback(data: bytes, extraction: ExtractionResult) -> tuple[str, float]:
    """Second opinion for a poorly-OCR'd *image*: LayoutLMv3 reads vendor,
    invoice number and total straight off the picture. Blocking (model
    inference) — run it in a thread. Returns ("", 0.0) if unavailable."""
    from app.services.layoutlm_crosscheck import _load_model, _normalize_bboxes, _tokens_to_field
    from app.services import layoutlm_crosscheck as lm
    from PIL import Image
    import io as _io
    import torch

    if not _load_model():
        return "", 0.0
    pil_image = Image.open(_io.BytesIO(data)).convert("RGB")
    words = extraction.words_with_boxes or []
    word_strings = [w["word"] for w in words] or ["placeholder"]
    word_boxes = [w.get("box", [0, 0, 0, 0]) for w in words] or [[0, 0, 1000, 1000]]
    page_w = words[0].get("page_w", 1000) if words else 1000
    page_h = words[0].get("page_h", 1000) if words else 1000
    normed_boxes = _normalize_bboxes(word_boxes, page_w, page_h) or [[0, 0, 0, 0]]
    n = min(len(word_strings), len(normed_boxes), 512)
    word_strings, normed_boxes = word_strings[:n], normed_boxes[:n]
    encoding = lm._PROCESSOR(pil_image, word_strings, boxes=normed_boxes, return_tensors="pt",
                             truncation=True, max_length=512)
    with torch.no_grad():
        predictions = lm._MODEL(**encoding).logits.argmax(-1).squeeze().tolist()
    if isinstance(predictions, int):
        predictions = [predictions]
    word_ids = encoding.word_ids(batch_index=0)
    labels = ["O"] * len(word_strings)
    for token_idx, word_idx in enumerate(word_ids or []):
        if word_idx is not None and token_idx < len(predictions):
            label = lm._LABEL_MAP.get(predictions[token_idx], "O")
            if label != "O":
                labels[word_idx] = label
    vendor = _tokens_to_field(word_strings, labels, "VENDOR")
    number = _tokens_to_field(word_strings, labels, "INVOICE_NUM")
    total = _tokens_to_field(word_strings, labels, "TOTAL")
    return f"Vendor: {vendor or ''}\nInvoice: {number or ''}\nTotal: {total or ''}", 0.4


async def route_extraction(db: AsyncSession, document_id: str, data: bytes, filename: str, content_type: str = "") -> ExtractionRoutingResult:
    """Extract text in an isolated, time-limited process
    (ocr.extract_text_isolated). If the file can't be read in time, or at
    all, raises DocumentUnreadableError with a message for the uploader —
    the document fails cleanly instead of hanging the worker. For a
    low-quality *image* OCR result, asks LayoutLMv3 for a second reading.

    Nothing here runs parsing work on the event loop: other documents
    and the Kafka heartbeat keep going while a slow file is read."""
    start_time = time.perf_counter()
    extraction = await asyncio.to_thread(extract_text_isolated, data, filename, content_type, _extraction_timeout())
    duration_ms = (time.perf_counter() - start_time) * 1000
    if not any(ch.isalnum() for ch in extraction.text or "") and extraction.file_type != "image":
        # A PDF with no text at all (blank, or a scan with no text layer the
        # OCR could read): nothing downstream can work with it.
        raise DocumentUnreadableError(
            "We couldn't find any text in this document — it may be blank, or a scan too faint to read. "
            "Upload a clearer copy."
        )

    fallback_threshold = float(get_rule("document.extraction_fallback_confidence_threshold", 0.5))
    if extraction.text_quality >= fallback_threshold or extraction.file_type != "image":
        if extraction.method == "pdf_text":
            route_name, model_used = "docling_text", "pdfplumber"
        elif extraction.file_type == "image":
            route_name, model_used = "docling_paddleocr", "paddleocr"
        else:
            route_name, model_used = "docling_text", "docling"
        result = ExtractionRoutingResult(
            route_name=route_name, model_used=model_used, fallback_triggered=False, fallback_reason=None,
            confidence=extraction.text_quality, extraction_result=extraction, duration_ms=duration_ms,
        )
        _log_to_db(db, document_id, result)
        return result

    # Low-quality OCR of an image: second reading with LayoutLMv3.
    start_time = time.perf_counter()
    try:
        fallback_text, fallback_confidence = await asyncio.to_thread(_layoutlm_image_fallback, data, extraction)
    except Exception as e:
        logger.warning(f"LayoutLMv3 fallback failed for {document_id}: {e}")
        fallback_text, fallback_confidence = "", 0.0
    if not fallback_text:
        fallback_text, fallback_confidence = extraction.text, extraction.text_quality
    if not any(ch.isalnum() for ch in fallback_text or ""):
        raise DocumentUnreadableError(
            "We couldn't read any text in this image — it may be blank or too blurry. Upload a clearer scan."
        )
    duration_ms += (time.perf_counter() - start_time) * 1000
    result = ExtractionRoutingResult(
        route_name="layoutlmv3_fallback", model_used="layoutlmv3", fallback_triggered=True,
        fallback_reason="low_confidence", confidence=fallback_confidence,
        extraction_result=ExtractionResult(
            text=fallback_text, method="layoutlmv3_fallback", file_type=extraction.file_type,
            text_quality=fallback_confidence, words_with_boxes=extraction.words_with_boxes,
        ),
        duration_ms=duration_ms,
    )
    _log_to_db(db, document_id, result)
    return result
