"""FR-29: the ML classifier answers only when it is confident enough,
otherwise the keyword classifier does; "other" always goes to review."""
from types import SimpleNamespace

import numpy as np
import pytest

from app.services import classification, pipeline


class FakeModel:
    classes_ = np.array(["invoice", "other", "po", "quote"])

    def __init__(self, probs):
        self.probs = probs

    def predict_proba(self, texts):
        return np.array([self.probs])


@pytest.fixture
def model(monkeypatch):
    def use(probs):
        monkeypatch.setattr(classification, "_load_model", lambda: FakeModel(probs))
    return use


TEXT = "PURCHASE ORDER\nPO Number: PO-7\nShip to: Warehouse 3"


def test_confident_model_answers(model):
    model([0.05, 0.05, 0.1, 0.8])           # quote, 0.8
    r = classification.classify_document(TEXT)
    assert r.document_type == "quote" and r.confidence == 0.8


def test_unsure_model_falls_back_to_keywords(model):
    model([0.3, 0.2, 0.25, 0.25])           # best 0.3 < 0.6
    assert classification.classify_document(TEXT).document_type == "po"   # keywords


def test_no_model_uses_keywords(monkeypatch):
    monkeypatch.setattr(classification, "_load_model", lambda: None)
    assert classification.classify_document(TEXT).document_type == "po"


def test_other_always_goes_to_review(model):
    model([0.02, 0.95, 0.02, 0.01])         # very sure it's "other"
    env = pipeline.classification_agent({"document_id": "d-1", "raw_text": "DELIVERY NOTE\n5 laptops", "_agent_trail": []})
    assert env["document_type"] == "other" and env["needs_review_forced"] is True
    model([0.95, 0.02, 0.02, 0.01])
    env = pipeline.classification_agent({"document_id": "d-2", "raw_text": "TAX INVOICE", "_agent_trail": []})
    assert env["document_type"] == "invoice" and "needs_review_forced" not in env
