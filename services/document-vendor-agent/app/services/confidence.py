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


# How much each score counts towards the overall one: the amount and who
# it's from matter most for an invoice; line items are a bonus.
WEIGHTS = {
    "total": 0.30, "vendor_name": 0.20, "classification": 0.15,
    "document_number": 0.15, "document_date": 0.10, "line_items": 0.10,
}
# Fields many genuine documents simply don't have; a 0 there means "not on
# the document", not "misread", so it's left out instead of averaged in.
OPTIONAL = {"line_items"}


def overall_confidence(confidence_scores: Dict[str, float]) -> float:
    scores = {k: v for k, v in confidence_scores.items() if not (k in OPTIONAL and not v)}
    if not scores:
        return 0.0
    weights = {k: WEIGHTS.get(k, 0.1) for k in scores}
    return round(sum(scores[k] * w for k, w in weights.items()) / sum(weights.values()), 3)


def load_threshold() -> float:
    from shared.rules_engine import get_rule
    cfg_val = load_extraction_config().get("confidence_threshold", 0.8)
    return float(get_rule("document.confidence_review_threshold", fallback=cfg_val))


def needs_review(overall: float, threshold: float | None = None) -> bool:
    """`threshold` overrides the global one — the per-vendor calibrated
    threshold from app/services/learning.py."""
    return overall < (load_threshold() if threshold is None else threshold)
