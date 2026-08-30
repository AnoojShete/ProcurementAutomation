from prometheus_client import generate_latest

import app.metrics  # noqa: F401 — importing registers the metrics below


class TestMetrics:
    def test_custom_metrics_are_registered(self):
        exposition = generate_latest().decode("utf-8")
        assert "notification_sent_total" in exposition

    def test_notification_sent_total_labels(self):
        from app.metrics import notification_sent_total

        notification_sent_total.labels(channel="email", status="sent").inc()
        exposition = generate_latest().decode("utf-8")
        assert 'notification_sent_total{channel="email",status="sent"}' in exposition
