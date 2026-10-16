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
import re
import subprocess
import sys
import threading
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
    text_quality: float  # 0-1: OCR recognition confidence (images) or text heuristic (PDFs)
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


# Docling's converter isn't documented as thread-safe, and several
# documents now run through extraction concurrently — only one uses the
# shared converter at a time. The fast pdfplumber path and PaddleOCR (its
# own subprocess) aren't affected.
_DOCLING_LOCK = threading.Lock()


def _text_from_pdf_docling(data: bytes, filename: str) -> tuple[str, list]:
    """Returns (markdown_text, words_with_boxes).

    Docling's export_to_markdown() gives clean reading-order text.
    Word/box pairs are extracted from the document's text cells for the
    LayoutLMv3 cross-check — Docling's cell bounding boxes are already
    in page-pixel coordinates.
    """
    from docling.datamodel.base_models import DocumentStream
    with _DOCLING_LOCK:
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


def _text_from_pdf_legacy(data: bytes) -> tuple[str, list]:
    """Fast plain text extraction using pdfplumber with word boxes."""
    text_parts = []
    words_with_boxes = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
            page_w = page.width or 1000
            page_h = page.height or 1000
            try:
                for w in (page.extract_words() or []):
                    word_str = w.get("text", "").strip()
                    if word_str:
                        words_with_boxes.append({
                            "word": word_str,
                            "box": [w.get("x0", 0), w.get("top", 0), w.get("x1", 0), w.get("bottom", 0)],
                            "page_w": page_w,
                            "page_h": page_h,
                        })
            except Exception:
                pass
    return "\n".join(text_parts).strip(), words_with_boxes


# ---------------------------------------------------------------------------
# PaddleOCR — image path (subprocess-isolated)
# ---------------------------------------------------------------------------

def _text_from_image_paddleocr(data: bytes) -> tuple[str, float, list]:
    """Run PaddleOCR in a subprocess. Returns (text, mean recognition
    confidence, words_with_boxes). Raises RuntimeError if it fails."""
    import json
    try:
        proc = subprocess.run(
            [sys.executable, _WORKER_SCRIPT],
            input=data,
            capture_output=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("PaddleOCR timed out")
    except Exception as e:
        raise RuntimeError(f"PaddleOCR execution error: {e}")
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace")[-300:] if proc.stderr else ""
        raise RuntimeError(f"PaddleOCR failed with exit {proc.returncode}: {stderr}")
    out = json.loads(proc.stdout.decode("utf-8") or "{}")
    lines = out.get("lines", [])
    return _rows_to_text(lines), _ocr_confidence(lines), _words_with_boxes(
        lines, out.get("width") or 1000, out.get("height") or 1000,
    )


def _words_with_boxes(lines: list, page_w: int, page_h: int) -> list:
    """Per-word boxes for the LayoutLMv3 cross-check. PaddleOCR boxes whole
    lines, so each word gets the slice of its line's box proportional to
    its position in the text."""
    words = []
    for ln in lines:
        x0, y0, x1, y1 = ln["box"]
        text = ln["text"]
        per_char = (x1 - x0) / max(len(text), 1)
        pos = 0
        for word in text.split():
            start = text.index(word, pos)
            pos = start + len(word)
            words.append({
                "word": word,
                "box": [int(x0 + start * per_char), int(y0), int(x0 + pos * per_char), int(y1)],
                "page_w": page_w, "page_h": page_h,
            })
    return words


def _rows_to_text(lines: list) -> str:
    """PaddleOCR returns one entry per text block, roughly top to bottom,
    so a table row ("Services  $55.00  10  $550.00") comes out as four
    separate lines. Put blocks whose vertical centres line up back on one
    line, left to right, so the field patterns see the row as printed."""
    if not lines:
        return ""

    def centre(ln):
        return (ln["box"][1] + ln["box"][3]) / 2

    def height(ln):
        return max(ln["box"][3] - ln["box"][1], 1.0)

    rows: list[list] = []
    for ln in sorted(lines, key=centre):
        row = rows[-1] if rows else None
        if row is not None:
            row_centre = sum(centre(x) for x in row) / len(row)
            if abs(centre(ln) - row_centre) <= 0.5 * min(height(ln), min(height(x) for x in row)):
                row.append(ln)
                continue
        rows.append([ln])
    return "\n".join("  ".join(x["text"] for x in sorted(row, key=lambda x: x["box"][0])) for row in rows)


def _ocr_confidence(lines: list) -> float:
    """PaddleOCR's own recognition score, averaged over the characters it
    read (a long line counts more than a stray mark)."""
    chars = sum(len(ln["text"]) for ln in lines)
    if not chars:
        return 0.0
    return round(sum(ln["confidence"] * len(ln["text"]) for ln in lines) / chars, 3)


# ---------------------------------------------------------------------------
# Text quality heuristic
# ---------------------------------------------------------------------------

_WORD_LIKE = re.compile(r"[A-Za-z]{2,}")
# Amounts, dates, quantities, IDs: "$1,699.48", "26/3/2021", "10", "INV-10012".
_NUMBER_LIKE = re.compile(r"^[\$₹€£(+\-]?[\d][\d,./:\-]*%?\)?$")


def _text_quality(text: str) -> float:
    """Fraction of whitespace-separated tokens that look like real words or
    numbers. Clean text ≈ 1.0; OCR noise ≈ 0. Numbers count: an invoice is
    mostly amounts and dates, which used to drag a clean read down to ~0.7."""
    tokens = text.split()
    if not tokens:
        return 0.0
    good = sum(1 for t in tokens if _WORD_LIKE.search(t) or _NUMBER_LIKE.match(t))
    return round(good / len(tokens), 3)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def extract_text(data: bytes, filename: str, content_type: str = "") -> ExtractionResult:
    """Route to the correct extraction path based on file type.

    PDFs:   Fast text-native check (pdfplumber, ~20ms) → Docling layout analysis fallback for scanned PDFs
    Images: PaddleOCR (subprocess)
    """
    file_type = classify_file_type(filename, content_type)
    cfg = load_extraction_config()
    min_chars = cfg.get("min_text_native_chars", 40)

    if file_type == "pdf":
        # Fast path: instant native digital text extraction via pdfplumber
        try:
            pdf_text, words_with_boxes = _text_from_pdf_legacy(data)
            clean_len = len(pdf_text.replace(" ", "").replace("\n", ""))
            quality = _text_quality(pdf_text)
            if clean_len >= min_chars and quality >= 0.5:
                logger.info(f"PDF has clean native text ({clean_len} chars, quality={quality}); using instant pdfplumber extraction")
                return ExtractionResult(
                    text=pdf_text, method="pdf_text", file_type="pdf",
                    text_quality=quality, words_with_boxes=words_with_boxes,
                )
        except Exception as e:
            logger.debug(f"Fast pdfplumber check failed: {e}")

        # No text layer and no images either (e.g. a blank page): there is
        # nothing for OCR to read, so skip Docling's model load (~60 s cold).
        try:
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                has_images = any(page.images for page in pdf.pages)
            if not has_images:
                logger.info("PDF has no text layer and no images; nothing to OCR")
                return ExtractionResult(text="", method="pdf_text", file_type="pdf", text_quality=0.0)
        except Exception as e:
            logger.debug(f"PDF image check failed ({e}); trying Docling")

        # Fallback for scanned/layout-heavy PDFs without native text
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
            pdf_text, words_with_boxes = _text_from_pdf_legacy(data)
            quality = 1.0 if len(pdf_text.replace(" ", "").replace("\n", "")) >= min_chars else 0.15
            return ExtractionResult(
                text=pdf_text, method="pdf_text", file_type="pdf", text_quality=quality,
                words_with_boxes=words_with_boxes,
            )

    # Image path — preprocess (BR-2), then PaddleOCR
    if os.environ.get("APP_IMAGE_PREPROCESSING", "0") == "1":
        from app.services.preprocess import preprocess_image
        data, steps = preprocess_image(data)
        logger.info(f"image preprocessing: {steps}")
    try:
        paddle_text, quality, words_with_boxes = _text_from_image_paddleocr(data)
    except Exception as e:
        logger.warning(f"PaddleOCR image extraction unavailable ({e}); returning low-quality fallback result")
        paddle_text, quality, words_with_boxes = "", 0.0, []
    return ExtractionResult(
        text=paddle_text, method="paddleocr", file_type="image", text_quality=quality,
        words_with_boxes=words_with_boxes,
    )


# ---------------------------------------------------------------------------
# Isolated extraction with a hard time limit (used by the pipeline)
# ---------------------------------------------------------------------------

class DocumentUnreadableError(Exception):
    """The document can't be read. The message is shown to the uploader."""


_APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def extract_text_isolated(data: bytes, filename: str, content_type: str, timeout_seconds: int,
                          preprocess_images: bool = False) -> ExtractionResult:
    """extract_text() in a child process that is killed after
    `timeout_seconds`. Blocking — call it from a thread."""
    import json
    env = {**os.environ, "APP_IMAGE_PREPROCESSING": "1" if preprocess_images else "0"}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.services._extract_worker", filename or "document", content_type or ""],
            input=data, capture_output=True, timeout=timeout_seconds, cwd=_APP_ROOT, env=env,
        )
    except subprocess.TimeoutExpired:
        raise DocumentUnreadableError(
            f"Couldn't read this document within {timeout_seconds} seconds — it may be damaged or unusually "
            f"complex (for example very large embedded images). Try re-exporting or re-scanning it."
        )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip().splitlines()
        logger.warning(f"extraction subprocess failed for {filename!r}: {detail[-1] if detail else proc.returncode}")
        raise DocumentUnreadableError(
            "This file couldn't be read as a PDF or image — it looks damaged or incomplete. "
            "Try re-exporting or re-scanning it."
        )
    out = json.loads(proc.stdout.decode("utf-8"))
    return ExtractionResult(
        text=out["text"], method=out["method"], file_type=out["file_type"],
        text_quality=out["text_quality"], words_with_boxes=out.get("words_with_boxes") or [],
    )
