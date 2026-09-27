from datetime import datetime, timedelta, timezone

from app.services.order_monitor import OrderRow, build_summary

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
SINCE = NOW - timedelta(hours=1)
CFG = {"interval_minutes": 60, "delivery_followup_days": 14, "signature_followup_days": 3}


def order(n, status, **kw):
    base = dict(
        id=f"{n:08d}-0000-0000-0000-000000000000", status=status, requested_by="r@acme.test",
        department="IT", amount=10000.0, currency="INR", vendor_name="Dell", is_backordered=False,
        sla_deadline=None, created_at=NOW - timedelta(days=30), updated_at=NOW - timedelta(days=2),
        contract_status=None,
    )
    base.update(kw)
    return OrderRow(**base)


def test_buckets_and_attention():
    orders = [
        order(1, "pending_approval", sla_deadline=NOW - timedelta(hours=5)),
        order(2, "pending_approval", sla_deadline=NOW + timedelta(hours=20), created_at=NOW - timedelta(minutes=10)),
        order(3, "approved", updated_at=NOW - timedelta(days=5), contract_status="pending_signature"),
        order(4, "fulfilled", updated_at=NOW - timedelta(days=20)),
        order(5, "fulfilled", updated_at=NOW - timedelta(days=1)),
        order(6, "approved", is_backordered=True, updated_at=NOW - timedelta(hours=1)),
        order(7, "invoice_received", updated_at=NOW - timedelta(minutes=30)),
        order(8, "rejected", updated_at=NOW - timedelta(minutes=5)),
    ]
    s = build_summary(orders, NOW, SINCE, CFG)

    assert s["counts"] == {
        "pending_approval": 2, "approval_overdue": 1, "awaiting_signature": 2,
        "awaiting_delivery": 2, "delivery_overdue": 1, "backordered": 1,
    }
    assert s["changes"] == {"new_requests": 1, "approved": 1, "invoices_received": 1, "rejected": 1}
    kinds = [a["kind"] for a in s["attention"]]
    # Most urgent first.
    assert kinds == ["approval_overdue", "signature_stalled", "delivery_overdue", "backordered"]
    assert "5h past its approval SLA" in s["attention"][0]["message"]
    assert "contract still awaiting signature" in s["attention"][1]["message"]
    assert s["open_order_value"] == 60000.0
    assert s["summary_text"].startswith("Order status as of 26 Sep 2026, 12:00 UTC.")
    assert "2 requests awaiting approval (1 past SLA)" in s["summary_text"]
    assert "Needs attention:" in s["summary_text"]


def test_quiet_period():
    s = build_summary([order(1, "fulfilled", updated_at=NOW - timedelta(days=3))], NOW, SINCE, CFG)
    assert s["attention"] == []
    assert s["summary_text"].endswith("Nothing needs attention.")
    assert "0 new requests" in s["summary_text"]
    assert "1 awaiting vendor delivery/invoice." in s["summary_text"]


def test_signed_contract_on_approved_request_is_flagged_not_counted_as_awaiting_signature():
    orders = [order(1, "approved", contract_status="signed", updated_at=NOW - timedelta(days=10))]
    s = build_summary(orders, NOW, SINCE, CFG)
    assert s["counts"]["awaiting_signature"] == 0
    assert s["counts"]["awaiting_delivery"] == 1
    assert [a["kind"] for a in s["attention"]] == ["status_mismatch"]
