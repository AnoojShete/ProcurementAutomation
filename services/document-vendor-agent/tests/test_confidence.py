from app.services.confidence import build_confidence_scores, overall_confidence, needs_review


class TestConfidence:
    def test_field_confidence_discounted_by_text_quality(self):
        scores = build_confidence_scores(
            classification_confidence=0.9, field_confidences={"total": 0.9}, text_quality=0.5
        )
        assert scores["classification"] == 0.45
        assert scores["total"] == 0.45

    def test_overall_confidence_is_the_mean(self):
        overall = overall_confidence({"a": 0.8, "b": 0.6, "c": 1.0})
        assert overall == 0.8

    def test_overall_confidence_empty_is_zero(self):
        assert overall_confidence({}) == 0.0

    def test_needs_review_below_threshold(self):
        assert needs_review(0.5) is True

    def test_does_not_need_review_above_threshold(self):
        assert needs_review(0.95) is False


class TestConfidenceAgentEnvelope:
    def test_confidence_agent_sets_overall_confidence(self):
        """document_service reads envelope["overall_confidence"] after the
        pipeline; dropping it made every upload end in status=failed."""
        from app.services.pipeline import confidence_agent

        envelope = {
            "document_id": "doc-1",
            "classification_confidence": 0.9,
            "field_confidences": {
                "vendor_name": 0.9, "document_number": 0.9, "document_date": 0.9,
                "total": 0.9, "line_items": 0.9,
            },
            "text_quality": 1.0,
        }
        out = confidence_agent(envelope)
        assert out["overall_confidence"] == overall_confidence(out["confidence_scores"])
        assert out["needs_review"] is False
