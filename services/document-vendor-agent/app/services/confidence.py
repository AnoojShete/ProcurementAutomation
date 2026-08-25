"""Combines per-field extraction confidence, OCR/text-quality, and
classification confidence into the per-field confidence_scores map and
overall_confidence published in document.classified, and decides
needs_review against the configurable threshold (default 0.8).
"""
from typing import Dict

from app.config import load_extraction_config


def build_confidence_scores(
    classification_confidence: float,
    field_confidences: Dict[str, float],
    text_quality: float,
) -> Dict[str, float]:
    """Every field confidence is discounted by how trustworthy the
    underlying OCR/text extraction was — a perfectly-matched regex on
    garbled OCR text is still not something to trust blindly."""
    scores = {"classification": round(classification_confidence * text_quality, 3)}
    for field_name, conf in field_confidences.items():
        scores[field_name] = round(conf * text_quality, 3)
    return scores


def overall_confidence(confidence_scores: Dict[str, float]) -> float:
    if not confidence_scores:
        return 0.0
    return round(sum(confidence_scores.values()) / len(confidence_scores), 3)


def needs_review(overall: float) -> bool:
    threshold = load_extraction_config().get("confidence_threshold", 0.8)
    return overall < threshold
