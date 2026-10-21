# Approval & Inventory agent

## 1. Introduction

**Business problem.** Approvals happen over email with no record of who may
approve what; stock and licences are tracked in spreadsheets; invoices are
matched to orders by eye.

**Objectives.** Route each purchase request to the right approvers by spend
and budget, enforce approval authority and separation of duties, keep
approvals moving with SLAs, and manage inventory, licences, sourcing and
invoice matching.

| Input | Output |
|---|---|
| A request from the app, or a quote from `document.classified` | An approved or rejected request (`approval.decided` per level), reserved stock, reorder suggestions, matched invoices |

## 2. Technical implementation

| Part | Detail |
|---|---|
| Components | FastAPI API, Temporal `ApprovalWorkflow` (one per request), Kafka consumers, order monitor, reorder service, invoice ledger |
| AI models | IsolationForest + SHAP for licence-usage anomalies |
| Tables | `purchase_requests`, `approval_history`, `approver_assignments`, `approval_delegations`, `budgets`, `inventory`, `licenses`, `license_usage`, `catalog_items`, `rfq_*`, `goods_receipts`, `invoice_matches` |
| API | `/api/requests`, `/api/inbox/{level}`, `/api/authority`, `/api/budgets`, `/api/inventory`, `/api/licenses`, `/api/catalog`, `/api/rfqs`, `/api/invoices`, `/api/tds`, `/api/orders`, `/api/ops`, `/email-action/*` |
| Communication | Consumes `document.classified`, `contract.signed`, `business_rule.updated`; publishes `approval.requested`, `approval.decided`, `budget.threshold_crossed`, `rfq.*`, `goods.received`, `reminder.due` (through the outbox) |
| Deployment | API + Temporal worker from one image; Temporal and Redis required |

## 3. Functional implementation

1. **Spend tier** from business rules: ≤ ₹500 auto-approved, ≤ ₹5,000 manager,
   above that manager + finance; over-budget requests get a finance step.
2. **Workflow**: for each level, wait for a decision. Only someone assigned to
   that level, within their limit, and not the requester may decide
   (separation of duties). Decisions come from the app or a single-use email link.
3. **SLA**: reminders at 50 % and 80 %; on breach, escalate to the next level,
   or reject at the last level.
4. **After approval**: `approval.decided` for the final level triggers the
   contract; hardware stock is reserved, or backordered with a reorder suggestion.
5. **Invoices**: line-level three-way match (order, receipt, invoice) with 1 %
   tolerances; a mismatch holds payment.

## 4. Results and evaluation

| Measure | Result | Source |
|---|---|---|
| Licence anomaly model | ROC-AUC 0.954, AP 0.873 on test (vs 0.687 for utilisation alone) | `docs/results/licence-anomaly.md` |
| Tests | 275 unit/integration tests; `budget_flow.py`, `sourcing_flow.py`, `invoice_lifecycle.py` (71/71) | `scripts/test-service.sh` |

![Approval queue](../showcase/approval/01-approval-queue.png)

**Limitations.** Synthetic licence data; a real company's login logs would
need re-tuning of the thresholds (business rules `license.anomaly_*`).
