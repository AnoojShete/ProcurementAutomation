"""Rule-based / keyword document classifier: PO vs invoice vs quote.

Deliberately simple (keyword scoring, not ML) — the task calls for a
rule-based classifier, and it's easy to reason about / extend as new
vendor templates show up.
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


@dataclass
class ClassificationResult:
    document_type: str
    confidence: float
    scores: Dict[str, float]


def classify_document(text: str) -> ClassificationResult:
    lowered = text.lower()
    raw_scores = {}
    for doc_type, patterns in _KEYWORDS.items():
        score = sum(weight for pattern, weight in patterns if re.search(pattern, lowered))
        raw_scores[doc_type] = score

    total = sum(raw_scores.values())
    if total == 0:
        # No keyword signal at all (e.g. badly garbled OCR) — default to
        # invoice (the most common document this pipeline sees) but with
        # low confidence so it lands in the review queue.
        return ClassificationResult(document_type="invoice", confidence=0.3, scores=raw_scores)

    best_type = max(raw_scores, key=raw_scores.get)
    best_score = raw_scores[best_type]
    # Confidence = how dominant the winner is vs the runner-up, scaled 0-1.
    others = sorted((v for k, v in raw_scores.items() if k != best_type), reverse=True)
    runner_up = others[0] if others else 0
    margin = (best_score - runner_up) / best_score if best_score else 0
    confidence = round(min(1.0, 0.55 + 0.45 * margin), 3)
    return ClassificationResult(document_type=best_type, confidence=confidence, scores=raw_scores)
