from prometheus_client import generate_latest

import app.metrics  # noqa: F401 — importing registers the metrics below


class TestMetrics:
    def test_custom_metrics_are_registered(self):
        exposition = generate_latest().decode("utf-8")
        for name in ("contract_generation_total", "risk_assessment_total"):
            assert name in exposition, f"{name} missing from /metrics exposition"

    def test_risk_assessment_total_labels(self):
        from app.metrics import risk_assessment_total

        risk_assessment_total.labels(risk_band="High").inc()
        exposition = generate_latest().decode("utf-8")
        assert 'risk_assessment_total{risk_band="High"}' in exposition
