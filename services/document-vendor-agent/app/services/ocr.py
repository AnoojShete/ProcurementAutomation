"""Text extraction pipeline:

  PDFs  → Docling (layout analysis, reading order, table structure recovery)
           Docling handles both text-native PDFs (no OCR needed) and scanned
           PDFs (routes scanned regions to its bundled OCR backend).
           Falls back to pdfplumber if Docling errors on a specific file.

  Images → PaddleOCR (PP-OCR pipeline, strong on invoice/table layouts)
           Images: Handled by PaddleOCR via a completely isolated subprocess
           (_paddle_worker.py) because PaddleOCR's C++ backend is prone to
           process-level segfaults/aborts that cannot be caught in Python.
           Both PaddleOCR runs fully local/offline — no external API calls.

Why subprocess for PaddleOCR:
  PaddleOCR's native inference engine can SIGABRT/SIGSEGV the process on
  certain platform/version pairs (tested on arm64 and emulated amd64).
  These are C-level OS signals, not Python exceptions — try/except cannot
  catch them. Subprocess isolation means a crash kills the child process
  only; the worker process (and Kafka consumer heartbeats) keep running.

Docling vs plain pdfplumber:
  Docling provides layout/table structure that a flat pdfplumber text dump
  doesn't — this is what actually moves the needle on field/line-item
  extraction accuracy downstream of the text layer.

Privacy/data-residency:
  All OCR (Docling, PaddleOCR) runs entirely in-container.
  No document content is sent to any external service.
"""
import io
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

import pdfplumber
from PIL import Image

from app.config import load_extraction_config

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "tiff", "bmp"}
PDF_EXTENSIONS = {"pdf"}

# Path to the subprocess worker script
_WORKER_SCRIPT = os.path.join(os.path.dirname(__file__), "_paddle_worker.py")


@dataclass
class ExtractionResult:
    text: str
    method: str   # "docling" | "paddleocr" | "pdf_text"
    file_type: str  # "pdf" | "image"
    text_quality: float  # 0-1 heuristic
    # Structured word/box output for LayoutLMv3 cross-check.
    # Each entry: {"word": str, "box": [x0,y0,x1,y1] in pixel coords}
    words_with_boxes: list = None

    def __post_init__(self):
        if self.words_with_boxes is None:
            self.words_with_boxes = []


def classify_file_type(filename: str, content_type: str) -> str:
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext in PDF_EXTENSIONS or "pdf" in (content_type or ""):
        return "pdf"
    return "image"


# ---------------------------------------------------------------------------
# Docling — PDF path
# ---------------------------------------------------------------------------

@lru_cache
def _docling_converter():
    """Built once per worker process — Docling loads layout/table models on
    first use; re-creating the converter per document would re-pay that cost
    every time (~15-75s in testing)."""
    from docling.document_converter import DocumentConverter
    return DocumentConverter()


def _text_from_pdf_docling(data: bytes, filename: str) -> tuple[str, list]:
    """Returns (markdown_text, words_with_boxes).

    Docling's export_to_markdown() gives clean reading-order text.
    Word/box pairs are extracted from the document's text cells for the
    LayoutLMv3 cross-check — Docling's cell bounding boxes are already
    in page-pixel coordinates.
    """
    from docling.datamodel.base_models import DocumentStream
    converter = _docling_converter()
    result = converter.convert(
        DocumentStream(name=filename or "document.pdf", stream=io.BytesIO(data))
    )
    doc = result.document
    text = doc.export_to_markdown().strip()

    # Extract word-level boxes for LayoutLMv3
    words_with_boxes = []
    try:
        for page in doc.pages.values():
            page_w = page.size.width if page.size else 1
            page_h = page.size.height if page.size else 1
            for cell in (page.cells or []):
                word = (cell.text or "").strip()
                if not word:
                    continue
                b = cell.bbox
                if b:
                    words_with_boxes.append({
                        "word": word,
                        "box": [b.l, b.t, b.r, b.b],
                        "page_w": page_w,
                        "page_h": page_h,
                    })
    except Exception as e:
        logger.debug(f"Docling word/box extraction failed (non-fatal): {e}")

    return text, words_with_boxes


def _text_from_pdf_legacy(data: bytes) -> str:
    """Fallback: plain text layer only, no layout/table awareness."""
    text_parts = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
    return "\n".join(text_parts).strip()


# ---------------------------------------------------------------------------
# PaddleOCR — image path (subprocess-isolated)
# ---------------------------------------------------------------------------

def _text_from_image_paddleocr(data: bytes) -> str:
    """Run PaddleOCR in a subprocess. Raises RuntimeError if it fails."""
    try:
        proc = subprocess.run(
            [sys.executable, _WORKER_SCRIPT],
            input=data,
            capture_output=True,
            timeout=120,
        )
        if proc.returncode == 0:
            return proc.stdout.decode("utf-8", errors="replace").strip()
        else:
            stderr = proc.stderr.decode("utf-8", errors="replace")[:300] if proc.stderr else ""
            raise RuntimeError(f"PaddleOCR failed with exit {proc.returncode}: {stderr}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("PaddleOCR timed out")
    except Exception as e:
        raise RuntimeError(f"PaddleOCR execution error: {e}")


# ---------------------------------------------------------------------------
# Text quality heuristic
# ---------------------------------------------------------------------------

def _text_quality(text: str) -> float:
    """Fraction of whitespace-separated tokens that look like real words
    (contain 2+ consecutive letters). Clean text ≈ 1.0; OCR noise ≈ 0."""
    import re
    tokens = text.split()
    if not tokens:
        return 0.0
    word_like = sum(1 for t in tokens if re.search(r"[A-Za-z]{2,}", t))
    return round(word_like / len(tokens), 3)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def extract_text(data: bytes, filename: str, content_type: str = "") -> ExtractionResult:
    """Route to the correct extraction path based on file type.

    PDFs:   Docling primary → pdfplumber fallback
    Images: PaddleOCR (subprocess)
    """
    file_type = classify_file_type(filename, content_type)
    cfg = load_extraction_config()
    min_chars = cfg.get("min_text_native_chars", 40)

    if file_type == "pdf":
        try:
            docling_text, words_with_boxes = _text_from_pdf_docling(data, filename)
            if len(docling_text.replace(" ", "").replace("\n", "")) >= min_chars:
                return ExtractionResult(
                    text=docling_text, method="docling", file_type="pdf",
                    text_quality=1.0, words_with_boxes=words_with_boxes,
                )
            logger.info("Docling found no meaningful text/table content; treating as low-quality/garbled")
            return ExtractionResult(
                text=docling_text, method="docling", file_type="pdf",
                text_quality=0.15, words_with_boxes=words_with_boxes,
            )
        except Exception as e:
            logger.warning(f"Docling extraction failed ({e}); falling back to pdfplumber", exc_info=True)
            pdf_text = _text_from_pdf_legacy(data)
            quality = 1.0 if len(pdf_text.replace(" ", "").replace("\n", "")) >= min_chars else 0.15
            return ExtractionResult(
                text=pdf_text, method="pdf_text", file_type="pdf", text_quality=quality,
            )

    # Image path — use PaddleOCR
    paddle_text = _text_from_image_paddleocr(data)
    quality = _text_quality(paddle_text)
    return ExtractionResult(
        text=paddle_text, method="paddleocr", file_type="image", text_quality=quality,
    )
