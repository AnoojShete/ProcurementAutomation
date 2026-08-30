from prometheus_client import generate_latest

import app.metrics  # noqa: F401 — importing registers the metrics below


class TestMetrics:
    def test_custom_metrics_are_registered(self):
        exposition = generate_latest().decode("utf-8")
        for name in (
            "document_processing_total",
            "document_pipeline_stage_duration_seconds",
            "extraction_confidence",
            "vendor_matching_total",
        ):
            assert name in exposition, f"{name} missing from /metrics exposition"

    def test_document_processing_total_labels(self):
        from app.metrics import document_processing_total

        document_processing_total.labels(status="classified").inc()
        exposition = generate_latest().decode("utf-8")
        assert 'document_processing_total{status="classified"}' in exposition
