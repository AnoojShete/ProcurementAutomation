"""Text extraction: Docling for every PDF (text-native or scanned —
Docling's own pipeline detects which and OCRs scanned pages internally),
pytesseract for standalone scanned images. Falls back to the lighter
pdfplumber/pytesseract-only path if Docling errors on a given file or
fails to initialize at all, so a parsing-engine problem degrades gracefully
rather than failing every upload.

Why Docling: layout analysis, reading order, and table-structure recovery
that a flat pdfplumber text dump doesn't give you — this is what actually
moves the needle on field/line-item extraction accuracy, not the OCR step
itself (Docling's bundled OCR, like pytesseract, is pretrained; the real
engineering here is what happens downstream of the extracted text/tables).
Runs fully local/offline — no document content leaves the machine.

Standalone PaddleOCR was evaluated for the image path and dropped: its
native inference engine crashes the process (SIGABRT/SIGSEGV, not a
catchable Python exception) on every version pair tried, on both native
arm64 and emulated amd64 — see the requirements.txt note for the three
distinct crash signatures found.
"""
import io
import logging
from dataclasses import dataclass
from functools import lru_cache

import pdfplumber
import pytesseract
from PIL import Image

from app.config import load_extraction_config

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "tiff", "bmp"}
PDF_EXTENSIONS = {"pdf"}


@dataclass
class ExtractionResult:
    text: str
    method: str  # "docling" | "pdf_text" | "ocr"
    file_type: str  # "pdf" | "image"
    text_quality: float  # 0-1 heuristic signal used to discount confidence for garbled OCR


def classify_file_type(filename: str, content_type: str) -> str:
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext in PDF_EXTENSIONS or "pdf" in (content_type or ""):
        return "pdf"
    return "image"


@lru_cache
def _docling_converter():
    """Built once per worker process — Docling loads its layout/table
    models on first use, so a fresh converter per document would re-pay
    that cost every single time."""
    from docling.document_converter import DocumentConverter
    return DocumentConverter()


def _text_from_pdf_docling(data: bytes, filename: str) -> str:
    from docling.datamodel.base_models import DocumentStream
    converter = _docling_converter()
    result = converter.convert(DocumentStream(name=filename or "document.pdf", stream=io.BytesIO(data)))
    return result.document.export_to_markdown().strip()


def _text_from_pdf_legacy(data: bytes) -> str:
    """Fallback path if Docling isn't available/fails: plain text layer
    only, no layout/table awareness."""
    text_parts = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
    return "\n".join(text_parts).strip()


def _text_from_image_ocr(data: bytes) -> str:
    image = Image.open(io.BytesIO(data))
    return pytesseract.image_to_string(image).strip()


def _text_quality(text: str) -> float:
    """Cheap, dependency-free heuristic for how trustworthy extracted text
    looks: the fraction of "word-shaped" tokens (2+ letters in a row) out
    of all whitespace-separated tokens. Clean text scores near 1.0;
    OCR noise from a heavily degraded scan scores low."""
    tokens = text.split()
    if not tokens:
        return 0.0
    import re
    word_like = sum(1 for t in tokens if re.search(r"[A-Za-z]{2,}", t))
    return round(word_like / len(tokens), 3)


def extract_text(data: bytes, filename: str, content_type: str = "") -> ExtractionResult:
    file_type = classify_file_type(filename, content_type)
    cfg = load_extraction_config()
    min_chars = cfg.get("min_text_native_chars", 40)

    if file_type == "pdf":
        try:
            docling_text = _text_from_pdf_docling(data, filename)
            if len(docling_text.replace(" ", "").replace("\n", "")) >= min_chars:
                return ExtractionResult(text=docling_text, method="docling", file_type="pdf", text_quality=1.0)
            logger.info("Docling found no meaningful text/table content; treating as low-quality/garbled")
            return ExtractionResult(text=docling_text, method="docling", file_type="pdf", text_quality=0.15)
        except Exception as e:
            logger.warning(f"Docling extraction failed ({e}); falling back to pdfplumber", exc_info=True)
            pdf_text = _text_from_pdf_legacy(data)
            quality = 1.0 if len(pdf_text.replace(" ", "").replace("\n", "")) >= min_chars else 0.15
            return ExtractionResult(text=pdf_text, method="pdf_text", file_type="pdf", text_quality=quality)

    ocr_text = _text_from_image_ocr(data)
    quality = _text_quality(ocr_text)
    return ExtractionResult(text=ocr_text, method="ocr", file_type="image", text_quality=quality)
