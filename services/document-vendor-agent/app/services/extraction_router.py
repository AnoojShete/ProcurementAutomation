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
from app.services.ocr import extract_text, ExtractionResult
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


async def route_extraction(db: AsyncSession, document_id: str, data: bytes, filename: str, content_type: str = "") -> ExtractionRoutingResult:
    """Routes document extraction with fallback logic."""
    start_time = time.perf_counter()
    
    extraction = None
    fallback_triggered = False
    fallback_reason = None
    
    try:
        extraction = await asyncio.wait_for(
            asyncio.to_thread(extract_text, data, filename, content_type),
            timeout=30.0
        )
        fallback_threshold = float(get_rule("document.extraction_fallback_confidence_threshold", 0.5))
        if extraction.text_quality < fallback_threshold:
            fallback_triggered = True
            fallback_reason = "low_confidence"
    except asyncio.TimeoutError:
        logger.warning(f"[extraction_router] extract_text timed out for doc {document_id}")
        fallback_triggered = True
        fallback_reason = "timeout"
    except Exception as e:
        logger.warning(f"[extraction_router] extract_text failed for doc {document_id}: {e}", exc_info=True)
        fallback_triggered = True
        fallback_reason = "exception"

    duration_ms = (time.perf_counter() - start_time) * 1000

    if not fallback_triggered:
        if extraction.method == "pdf_text":
            route_name = "docling_text"
            model_used = "pdfplumber"
        elif extraction.file_type == "image":
            route_name = "docling_paddleocr"
            model_used = "paddleocr"
        else:
            route_name = "docling_text"
            model_used = "docling"
        
        result = ExtractionRoutingResult(
            route_name=route_name,
            model_used=model_used,
            fallback_triggered=False,
            fallback_reason=None,
            confidence=extraction.text_quality,
            extraction_result=extraction,
            duration_ms=duration_ms
        )
        _log_to_db(db, document_id, result)
        return result

    # Fallback to LayoutLMv3
    from app.services.layoutlm_crosscheck import _load_model, _PROCESSOR, _MODEL, _LABEL_MAP, _tokens_to_field
    from PIL import Image
    import io as _io
    import torch
    
    start_time = time.perf_counter()
    fallback_text = ""
    fallback_confidence = 0.0
    
    if _load_model():
        try:
            pil_image = Image.open(_io.BytesIO(data)).convert("RGB")
            
            words = extraction.words_with_boxes if extraction else []
            word_strings = [w["word"] for w in words] if words else ["placeholder"]
            word_boxes = [w.get("box", [0, 0, 0, 0]) for w in words] if words else [[0, 0, 1000, 1000]]
            page_w = words[0].get("page_w", 1000) if words else 1000
            page_h = words[0].get("page_h", 1000) if words else 1000
            
            from app.services.layoutlm_crosscheck import _normalize_bboxes
            normed_boxes = _normalize_bboxes(word_boxes, page_w, page_h)
            if not normed_boxes:
                normed_boxes = [[0, 0, 0, 0]]
                word_strings = [""]
            
            min_len = min(len(word_strings), len(normed_boxes), 512)
            word_strings = word_strings[:min_len]
            normed_boxes = normed_boxes[:min_len]
            
            encoding = _PROCESSOR(
                pil_image, word_strings, boxes=normed_boxes,
                return_tensors="pt", truncation=True, max_length=512,
            )
            with torch.no_grad():
                outputs = _MODEL(**encoding)
            
            logits = outputs.logits
            predictions = logits.argmax(-1).squeeze().tolist()
            if isinstance(predictions, int):
                predictions = [predictions]
                
            token_ids = encoding["input_ids"].squeeze().tolist()
            word_ids = encoding.word_ids(batch_index=0) if hasattr(encoding, "word_ids") else list(range(len(predictions)))

            word_labels = ["O"] * len(word_strings)
            for token_idx, word_idx in enumerate(word_ids or []):
                if word_idx is not None and token_idx < len(predictions):
                    label_id = predictions[token_idx]
                    label_str = _LABEL_MAP.get(label_id, "O")
                    if label_str != "O":
                        word_labels[word_idx] = label_str

            lm_vendor = _tokens_to_field(word_strings, word_labels, "VENDOR")
            lm_invoice_num = _tokens_to_field(word_strings, word_labels, "INVOICE_NUM")
            lm_total_str = _tokens_to_field(word_strings, word_labels, "TOTAL")
            
            fallback_text = f"Vendor: {lm_vendor or ''}\nInvoice: {lm_invoice_num or ''}\nTotal: {lm_total_str or ''}"
            fallback_confidence = 0.4
        except Exception as e:
            logger.warning(f"LayoutLMv3 fallback failed: {e}")
            fallback_text = extraction.text if extraction else ""
            fallback_confidence = 0.0

    if not fallback_text and (filename.lower().endswith(".pdf") or (extraction and extraction.file_type == "pdf")):
        try:
            from app.services.ocr import _text_from_pdf_legacy, _text_quality
            recovered_text, recovered_boxes = _text_from_pdf_legacy(data)
            if recovered_text:
                fallback_text = recovered_text
                fallback_confidence = _text_quality(fallback_text)
                if extraction:
                    extraction.words_with_boxes = recovered_boxes
        except Exception:
            pass

    duration_ms += (time.perf_counter() - start_time) * 1000
    
    fallback_extraction = ExtractionResult(
        text=fallback_text,
        method="layoutlmv3_fallback",
        file_type=extraction.file_type if extraction else "unknown",
        text_quality=fallback_confidence,
        words_with_boxes=extraction.words_with_boxes if extraction else None
    )

    result = ExtractionRoutingResult(
        route_name="layoutlmv3_fallback",
        model_used="layoutlmv3",
        fallback_triggered=True,
        fallback_reason=fallback_reason,
        confidence=fallback_confidence,
        extraction_result=fallback_extraction,
        duration_ms=duration_ms
    )
    _log_to_db(db, document_id, result)
    return result
