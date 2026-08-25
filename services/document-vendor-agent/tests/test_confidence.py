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
