"""Custom business metrics, registered to prometheus_client's default
registry alongside prometheus-fastapi-instrumentator's generic HTTP
metrics (see app/main.py).

approval_pending_total is maintained by a periodic DB-count background
task in app/main.py's lifespan (not incrementally via inc()/dec() calls
scattered across code paths) because request creation runs in THIS API
process while the terminal state transition (record_approval_decision /
update_request_status) runs inside the Temporal workflow's activities, in
the separate approval-inventory-agent-worker container — an incrementally
maintained Gauge split across two processes' independent prometheus_client
registries would never converge on the true count. See app/worker.py's
start_http_server(9100) for the metrics (approval_escalated_total) that
DO need to be recorded from inside that worker process.
"""
from prometheus_client import Counter, Gauge

approval_pending_total = Gauge(
    "approval_pending_total",
    "Purchase requests currently awaiting approval (recomputed periodically from the DB)",
)

approval_escalated_total = Counter(
    "approval_escalated_total",
    "Approval decisions auto-escalated on SLA breach",
)

inventory_reservation_total = Counter(
    "inventory_reservation_total",
    "Inventory reservation outcomes at purchase-request creation",
    ["status"],
)
