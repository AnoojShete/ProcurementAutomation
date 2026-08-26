# Approval & Inventory Intelligence Agent

This service handles purchase approvals, inventory locking, and license utilisation tracking as part of the IT procurement platform.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check endpoint |
| POST | `/requests` | Create a new purchase/reclaim request |
| GET | `/requests/{request_id}` | Get request details and approval history |
| POST | `/requests/{request_id}/approve` | Approver approves a request |
| POST | `/requests/{request_id}/reject` | Approver rejects a request |
| GET | `/inventory` | Hardware + license inventory with utilisation |
| GET | `/inbox/{approver_id}` | Pending approvals routed to this approver |
| GET | `/metrics` | Prometheus metrics |

## Kafka Events Published

| Topic | When |
|-------|------|
| `approval.requested` | Every new purchase/reclaim request |
| `approval.decided` | Every approve/reject/escalation decision |
| `license.usage.updated` | Every scan cycle (once per hour by default) |

## Kafka Events Consumed

| Topic | Source | Action |
|-------|--------|--------|
| `document.classified` | document-vendor-agent | Logged for audit |
| `contract.signed` | contract-risk-agent | Mark purchase_request `fulfilled`; activate license row for `license`/`saas` requests |

**Note:** `license.usage.updated` is **published** by this service, not consumed.
Consuming your own output would be an infinite loop. The input to the usage pipeline
is raw SSO login data (see **License Utilisation** below), not the Kafka event.

## License Utilisation Pipeline

```
scripts/generate_sso_logs.py
      ↓  writes
data/synthetic-sso-logs/sso_login_events.json
      ↓  read by (every hour)
app/usage_scanner.py  →  license_usage table  →  license.usage.updated (Kafka)
                                               →  reclaim PurchaseRequest (if < 30%)
```

Run the SSO log generator once to produce test data:

```bash
python scripts/generate_sso_logs.py
# Output: data/synthetic-sso-logs/sso_login_events.json
# Seeded with random.seed(42) — fully reproducible
```

## How to Run in Isolation

```bash
cd d:\ProcurementAutomation
docker compose -f docker-compose.yml -f docker-compose.override.yml up approval-inventory-agent --build
```

## How to Run Tests

```bash
cd services/approval-inventory-agent
python -m pytest tests/ -v
```

| Test file | Coverage |
|-----------|----------|
| `test_spend_tier.py` | 8 boundary tests for tier routing |
| `test_redis_lock.py` | 5 tests including race-condition simulation |
| `test_usage_reclaim.py` | 6 tests for reclaim threshold logic |
| `test_event_schemas.py` | 6 tests validating Kafka event shapes |
| `test_contract_signed.py` | 5 tests for contract.signed handler |

## Temporal Workflows

When a request requires approval, a Temporal workflow is started. It handles timeouts, SLA deadlines, and escalations, communicating with the service via activities.

You can inspect running and completed workflows via the Temporal UI at [http://localhost:8088](http://localhost:8088).

## Configuration

Spend tiers and approval chains are configurable via `config.yaml`. The current logic defines:
- Auto-approve: <= ₹500
- Manager approval: > ₹500 and <= ₹5000
- Manager + Finance approval: > ₹5000
