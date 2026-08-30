from prometheus_client import generate_latest

import app.metrics  # noqa: F401 — importing registers the metrics below


class TestMetrics:
    def test_custom_metrics_are_registered(self):
        exposition = generate_latest().decode("utf-8")
        for name in ("approval_pending_total", "approval_escalated_total", "inventory_reservation_total"):
            assert name in exposition, f"{name} missing from /metrics exposition"

    def test_inventory_reservation_total_labels(self):
        from app.metrics import inventory_reservation_total

        inventory_reservation_total.labels(status="reserved").inc()
        exposition = generate_latest().decode("utf-8")
        assert 'inventory_reservation_total{status="reserved"}' in exposition
