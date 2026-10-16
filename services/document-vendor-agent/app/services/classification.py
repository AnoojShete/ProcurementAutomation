"""Document classifier: PO vs invoice vs quote vs other.

An ML model (TF-IDF + logistic regression, ml/train_classifier.py, FR-29)
answers when it is at least ML_MIN_CONFIDENCE sure; otherwise the keyword
classifier below does. The keywords are simple to reason about and extend
as new vendor templates show up.
"""
import re
from dataclasses import dataclass
from typing import Dict

# (keyword, weight) — title-ish phrases score higher than incidental words.
_KEYWORDS = {
    "invoice": [
        (r"\btax invoice\b", 3), (r"\binvoice\b", 3), (r"\binvoice number\b", 2),
        (r"\binvoice date\b", 2), (r"\bbill\s*#", 2), (r"\bbill to\b", 1),
        (r"\bamount due\b", 2), (r"\bremit(?:tance)? to\b", 1), (r"\bdue date\b", 1),
    ],
    "po": [
        (r"\bpurchase order\b", 3), (r"\bpo number\b", 2), (r"\bpo date\b", 2),
        (r"\bpo#", 2), (r"\bship to\b", 1), (r"\bdeliver to\b", 1),
        (r"\bauthorized by\b", 1),
    ],
    "quote": [
        (r"\bquotation\b", 3), (r"\bquote number\b", 2), (r"\bqt#", 2),
        (r"\bvalid until\b", 2), (r"\bestimate\b", 2), (r"\bproposal\b", 1),
        (r"\bprice quote\b", 2),
    ],
}


# A document is an invoice / PO / quote only with at least one title-level
# keyword (weight 3) or two strong ones; otherwise it's "other" (BR-3).
MIN_TITLE_SCORE = 3
DOCUMENT_TYPES = ("invoice", "po", "quote", "other")


@dataclass
class ClassificationResult:
    document_type: str
    confidence: float
    scores: Dict[str, float]
    needs_review: bool = False


import logging
import os
import joblib

logger = logging.getLogger(__name__)

_MODEL = None
_MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "ml", "artifacts", "classifier.joblib"
)

def _load_model():
    global _MODEL
    if _MODEL is None and os.path.exists(_MODEL_PATH):
        try:
            _MODEL = joblib.load(_MODEL_PATH)
        except Exception as e:
            logger.warning(f"Document classifier model couldn't be loaded ({e}); using keywords")
    return _MODEL


def _classify_with_keywords(text: str) -> ClassificationResult:
    lowered = text.lower()
    raw_scores = {}
    for doc_type, patterns in _KEYWORDS.items():
        score = sum(weight for pattern, weight in patterns if re.search(pattern, lowered))
        raw_scores[doc_type] = score

    best_type = max(raw_scores, key=raw_scores.get)
    best_score = raw_scores[best_type]
    if best_score < MIN_TITLE_SCORE:
        # Nothing that names the document (no "invoice", "purchase order",
        # "quotation"…): a delivery note, statement, letter, or unreadable
        # scan. "other" goes to review instead of being forced into a type.
        return ClassificationResult(document_type="other", confidence=0.5, scores=raw_scores, needs_review=True)
    # Confidence = how dominant the winner is vs the runner-up, scaled 0-1.
    others = sorted((v for k, v in raw_scores.items() if k != best_type), reverse=True)
    runner_up = others[0] if others else 0
    margin = (best_score - runner_up) / best_score if best_score else 0
    confidence = round(min(1.0, 0.55 + 0.45 * margin), 3)
    return ClassificationResult(document_type=best_type, confidence=confidence, scores=raw_scores, needs_review=True)


# FR-29: the ML model (ml/train_classifier.py, built into the image only if
# it beat the keywords — docs/results/classifier.md) answers when it is at
# least this sure; otherwise the keyword classifier does.
ML_MIN_CONFIDENCE = 0.6


def classify_document(text: str) -> ClassificationResult:
    model = _load_model()
    if model:
        try:
            # Predict probabilities
            probas = model.predict_proba([text])[0]
            classes = model.classes_
            
            best_idx = probas.argmax()
            best_type = classes[best_idx]
            confidence = float(probas[best_idx])
            
            scores = {cls: float(prob) for cls, prob in zip(classes, probas)}
            
            if confidence >= ML_MIN_CONFIDENCE:
                return ClassificationResult(
                    document_type=best_type,
                    confidence=confidence,
                    scores=scores,
                    needs_review=False
                )
        except Exception as e:
            logger.warning(f"Document classifier model failed ({e}); using keywords")
            
    # Fallback
    return _classify_with_keywords(text)
