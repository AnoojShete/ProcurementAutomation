import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ml"))

from train_risk_model import train, MODEL_PATH  # noqa: E402
import joblib  # noqa: E402


class TestRiskModel:
    @classmethod
    def setup_class(cls):
        train()
        bundle = joblib.load(MODEL_PATH)
        cls.model = bundle["model"]
        cls.features = bundle["features"]

    def _predict(self, **overrides) -> float:
        vector = {
            "vendor_tenure_months": overrides.get("vendor_tenure_months", 24),
            "on_time_delivery_rate": overrides.get("on_time_delivery_rate", 0.8),
            "financial_stability_score": overrides.get("financial_stability_score", 0.8),
            "breach_disclosure_count": overrides.get("breach_disclosure_count", 0),
            "security_cert_flag": overrides.get("security_cert_flag", 1),
            "geo_risk_flag": overrides.get("geo_risk_flag", 0),
        }
        X = [[vector[f] for f in self.features]]
        return float(self.model.predict_proba(X)[0][1])

    def test_low_risk_vendor_scores_lower_than_high_risk_vendor(self):
        low_risk_score = self._predict(
            vendor_tenure_months=96, on_time_delivery_rate=0.98, financial_stability_score=0.95,
            breach_disclosure_count=0, security_cert_flag=1, geo_risk_flag=0,
        )
        high_risk_score = self._predict(
            vendor_tenure_months=2, on_time_delivery_rate=0.35, financial_stability_score=0.2,
            breach_disclosure_count=4, security_cert_flag=0, geo_risk_flag=1,
        )
        assert low_risk_score < high_risk_score

    def test_scores_are_valid_probabilities(self):
        score = self._predict()
        assert 0.0 <= score <= 1.0

    def test_feature_importances_available_for_explainability(self):
        assert len(self.model.feature_importances_) == len(self.features)
        assert all(importance >= 0 for importance in self.model.feature_importances_)
