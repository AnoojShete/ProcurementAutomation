"""LayoutLMv3 cross-check against Docling's primary extraction.

Model: ngvozdenovic/invoice_extraction (LayoutLMv3 fine-tuned for invoice fields)

IMPORTANT — apply_ocr=False:
  The default LayoutLMv3Processor uses pytesseract INTERNALLY to generate
  word/box inputs if you don't supply them. Calling it on a raw image
  without pre-supplying OCR output will silently install and invoke
  Tesseract, defeating the Docling/PaddleOCR pipeline entirely. We
  ALWAYS pass apply_ocr=False and supply our own words + bounding boxes
  from Docling's output (converted to the 0-1000 normalized scale
  LayoutLMv3 expects).

Lazy loading:
  The model is ~1 GB. Import and loading are deferred to first use and
  wrapped in a try/except — if the model fails to load (OOM, HF quota,
  container without enough RAM, etc.), the cross-check is skipped and a
  WARNING is logged. The pipeline continues without it; the main
  Docling/PaddleOCR extraction is unaffected.

Agreement metric:
  A Prometheus counter tracks how many documents agreed / disagreed
  between the two pipelines. Available on /metrics.
"""
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

# Prometheus metrics (optional — skip if prometheus_client not installed)
try:
    from prometheus_client import Counter
    _AGREE_COUNTER = Counter(
        "layoutlm_pipeline_agreement_total",
        "LayoutLMv3 vs Docling extraction agreement",
        ["result"],  # 'agree' | 'disagree' | 'skipped'
    )
except ImportError:
    _AGREE_COUNTER = None


def _inc(label: str):
    if _AGREE_COUNTER:
        _AGREE_COUNTER.labels(result=label).inc()


# ---------------------------------------------------------------------------
# Model loading — lazy, singleton, fail-soft
# ---------------------------------------------------------------------------

_MODEL_LOAD_ATTEMPTED = False
_PROCESSOR = None
_MODEL = None
_LABEL_MAP: dict = {}


def _load_model() -> bool:
    """Try to load the LayoutLMv3 model. Returns True on success, False on
    any failure (logged as WARNING so the pipeline can continue)."""
    global _MODEL_LOAD_ATTEMPTED, _PROCESSOR, _MODEL, _LABEL_MAP
    if _MODEL_LOAD_ATTEMPTED:
        return _MODEL is not None

    _MODEL_LOAD_ATTEMPTED = True
    model_name = "ngvozdenovic/invoice_extraction"

    try:
        from transformers import LayoutLMv3Processor, LayoutLMv3ForTokenClassification
        import torch  # noqa — needed for inference

        logger.info(f"Loading LayoutLMv3 model '{model_name}' (this may take a moment)...")

        # apply_ocr=False is CRITICAL — see module docstring.
        _PROCESSOR = LayoutLMv3Processor.from_pretrained(model_name, apply_ocr=False)
        _MODEL = LayoutLMv3ForTokenClassification.from_pretrained(model_name)
        _MODEL.eval()

        # Build label map from model config
        if hasattr(_MODEL.config, "id2label"):
            _LABEL_MAP = _MODEL.config.id2label
        else:
            # Minimal fallback for known invoice-extraction labels
            _LABEL_MAP = {0: "O", 1: "B-VENDOR", 2: "I-VENDOR",
                          3: "B-TOTAL", 4: "I-TOTAL",
                          5: "B-INVOICE_NUM", 6: "I-INVOICE_NUM"}

        logger.info(f"LayoutLMv3 model loaded. Labels: {list(_LABEL_MAP.values())}")
        return True

    except Exception as e:
        logger.warning(
            f"LayoutLMv3 model failed to load — cross-check disabled for this session. "
            f"Reason: {e}. The primary Docling extraction pipeline is unaffected."
        )
        _MODEL = None
        _PROCESSOR = None
        return False


# ---------------------------------------------------------------------------
# Cross-check result
# ---------------------------------------------------------------------------

@dataclass
class CrossCheckResult:
    available: bool                  # False if model failed to load
    disagrees: bool                  # True if primary and secondary differ on any key field
    docling_fields: dict             # primary extraction fields
    layoutlm_fields: dict            # secondary extraction fields (empty if unavailable)
    disagreement_details: dict       # which fields differ and both values
    agreement_rate_note: str         # logged to metrics


# ---------------------------------------------------------------------------
# Token classification helpers
# ---------------------------------------------------------------------------

def _tokens_to_field(tokens: list[str], labels: list[str], target_prefix: str) -> Optional[str]:
    """Collect consecutive tokens whose label starts with target_prefix."""
    parts = []
    in_entity = False
    for tok, lab in zip(tokens, labels):
        if lab.startswith(f"B-{target_prefix}"):
            parts = [tok]
            in_entity = True
        elif lab.startswith(f"I-{target_prefix}") and in_entity:
            parts.append(tok)
        else:
            if in_entity and parts:
                break  # first entity only
            in_entity = False
    return " ".join(parts) if parts else None


def _normalize_bboxes(raw_boxes: list, page_width: int, page_height: int) -> list:
    """Scale bounding boxes to the 0-1000 range LayoutLMv3 expects.

    Each box should be [x0, y0, x1, y1] in pixel coordinates.
    Missing / malformed boxes are replaced with [0, 0, 0, 0].
    """
    normed = []
    for box in raw_boxes:
        try:
            x0, y0, x1, y1 = box[:4]
            nx0 = max(0, min(1000, int(x0 * 1000 / max(page_width, 1))))
            ny0 = max(0, min(1000, int(y0 * 1000 / max(page_height, 1))))
            nx1 = max(0, min(1000, int(x1 * 1000 / max(page_width, 1))))
            ny1 = max(0, min(1000, int(y1 * 1000 / max(page_height, 1))))
            normed.append([nx0, ny0, nx1, ny1])
        except (TypeError, IndexError, ValueError):
            normed.append([0, 0, 0, 0])
    return normed


# ---------------------------------------------------------------------------
# Main cross-check function
# ---------------------------------------------------------------------------

def run_crosscheck(
    image_bytes: Optional[bytes],
    docling_words: list[str],
    docling_boxes: list,          # pixel-space [x0, y0, x1, y1] per word
    page_width: int,
    page_height: int,
    docling_vendor_name: Optional[str],
    docling_total: Optional[float],
    docling_invoice_num: Optional[str],
) -> CrossCheckResult:
    """Run the LayoutLMv3 model as a second extraction pass.

    Compares vendor_name, total, and invoice_number between the two pipelines.
    Any disagreement → needs_review = True + both values shown side-by-side.

    Returns CrossCheckResult with available=False if the model isn't loaded.
    """
    docling_fields = {
        "vendor_name": docling_vendor_name,
        "total": docling_total,
        "invoice_number": docling_invoice_num,
    }

    if not _load_model():
        _inc("skipped")
        return CrossCheckResult(
            available=False, disagrees=False,
            docling_fields=docling_fields, layoutlm_fields={},
            disagreement_details={},
            agreement_rate_note="model_unavailable",
        )

    try:
        import torch
        from PIL import Image
        import io as _io

        # Build PIL image for the processor
        if image_bytes:
            pil_image = Image.open(_io.BytesIO(image_bytes)).convert("RGB")
        else:
            # For PDF pages we don't have a ready image — create a blank placeholder.
            # The processor still runs on the words+boxes only; the image is needed
            # for the visual embedding but a blank image is safe here.
            pil_image = Image.new("RGB", (max(page_width, 1), max(page_height, 1)), "white")

        normed_boxes = _normalize_bboxes(docling_boxes, page_width, page_height)
        words = docling_words if docling_words else ["(empty)"]
        if not normed_boxes:
            normed_boxes = [[0, 0, 0, 0]] * len(words)

        # Pad/truncate to match — LayoutLMv3 requires words and boxes same length
        min_len = min(len(words), len(normed_boxes), 512)
        words = words[:min_len]
        normed_boxes = normed_boxes[:min_len]

        # apply_ocr=False: we supply our own words and boxes
        encoding = _PROCESSOR(
            pil_image, words, boxes=normed_boxes,
            return_tensors="pt", truncation=True, max_length=512,
        )

        with torch.no_grad():
            outputs = _MODEL(**encoding)

        logits = outputs.logits  # (1, seq_len, num_labels)
        predictions = logits.argmax(-1).squeeze().tolist()
        if isinstance(predictions, int):
            predictions = [predictions]

        # Map predictions back to word-level labels
        token_ids = encoding["input_ids"].squeeze().tolist()
        word_ids = encoding.word_ids(batch_index=0) if hasattr(encoding, "word_ids") else list(range(len(predictions)))

        word_labels = ["O"] * len(words)
        for token_idx, word_idx in enumerate(word_ids or []):
            if word_idx is not None and token_idx < len(predictions):
                label_id = predictions[token_idx]
                label_str = _LABEL_MAP.get(label_id, "O")
                if label_str != "O":
                    word_labels[word_idx] = label_str

        # Extract fields from labeled tokens
        lm_vendor = _tokens_to_field(words, word_labels, "VENDOR")
        lm_invoice_num = _tokens_to_field(words, word_labels, "INVOICE_NUM")
        lm_total_str = _tokens_to_field(words, word_labels, "TOTAL")
        lm_total: Optional[float] = None
        if lm_total_str:
            try:
                lm_total = float(lm_total_str.replace(",", "").replace("₹", "").replace("$", "").strip())
            except ValueError:
                lm_total = None

        layoutlm_fields = {
            "vendor_name": lm_vendor,
            "total": lm_total,
            "invoice_number": lm_invoice_num,
        }

        # Compare
        disagreement_details = {}
        total_tolerance = 1.0  # allow ₹1 rounding diff on totals

        if _names_differ(docling_vendor_name, lm_vendor):
            disagreement_details["vendor_name"] = {
                "docling": docling_vendor_name,
                "layoutlm": lm_vendor,
            }

        if _totals_differ(docling_total, lm_total, total_tolerance):
            disagreement_details["total"] = {
                "docling": docling_total,
                "layoutlm": lm_total,
            }

        if _strs_differ(docling_invoice_num, lm_invoice_num):
            disagreement_details["invoice_number"] = {
                "docling": docling_invoice_num,
                "layoutlm": lm_invoice_num,
            }

        disagrees = bool(disagreement_details)
        _inc("disagree" if disagrees else "agree")

        return CrossCheckResult(
            available=True,
            disagrees=disagrees,
            docling_fields=docling_fields,
            layoutlm_fields=layoutlm_fields,
            disagreement_details=disagreement_details,
            agreement_rate_note="disagree" if disagrees else "agree",
        )

    except Exception as e:
        logger.warning(f"LayoutLMv3 cross-check failed (non-fatal): {e}", exc_info=True)
        _inc("skipped")
        return CrossCheckResult(
            available=False, disagrees=False,
            docling_fields=docling_fields, layoutlm_fields={},
            disagreement_details={},
            agreement_rate_note="error",
        )


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------

def _names_differ(a: Optional[str], b: Optional[str]) -> bool:
    """Both present and different (case-insensitive, stripped)."""
    if a is None or b is None:
        return False  # can't call it a disagreement if one side didn't extract anything
    return a.strip().lower() != b.strip().lower()


def _totals_differ(a: Optional[float], b: Optional[float], tolerance: float) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) > tolerance


def _strs_differ(a: Optional[str], b: Optional[str]) -> bool:
    if a is None or b is None:
        return False
    return a.strip().upper() != b.strip().upper()
