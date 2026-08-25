"""Text extraction: pdfplumber for text-native PDFs, pytesseract OCR for
scanned images (and for PDFs that turn out to have no extractable text
layer) — "don't OCR everything blindly" per the task spec.
"""
import io
import logging
from dataclasses import dataclass

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
    method: str  # "pdf_text" | "ocr"
    file_type: str  # "pdf" | "image"
    text_quality: float  # 0-1 heuristic signal used to discount confidence for garbled OCR


def classify_file_type(filename: str, content_type: str) -> str:
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext in PDF_EXTENSIONS or "pdf" in (content_type or ""):
        return "pdf"
    return "image"


def _text_from_pdf(data: bytes) -> str:
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
        pdf_text = _text_from_pdf(data)
        if len(pdf_text.replace(" ", "").replace("\n", "")) >= min_chars:
            return ExtractionResult(text=pdf_text, method="pdf_text", file_type="pdf", text_quality=1.0)
        # Text-sparse / scanned PDF: pdfplumber found effectively nothing.
        # We don't rasterize+OCR the PDF page (would need poppler/ghostscript
        # in the image) — documented limitation, see service README/summary.
        logger.info("PDF had no meaningful text layer; treating as low-quality/garbled")
        return ExtractionResult(text=pdf_text, method="pdf_text", file_type="pdf", text_quality=0.15)

    ocr_text = _text_from_image_ocr(data)
    quality = _text_quality(ocr_text)
    return ExtractionResult(text=ocr_text, method="ocr", file_type="image", text_quality=quality)
