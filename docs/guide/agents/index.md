# Agents

Each agent page follows the same four parts (the standard agent template):
**1. Introduction** · **2. Technical implementation** · **3. Functional
implementation** · **4. Results and evaluation**.

| Agent | Port | Owner (original) | Page |
|---|---|---|---|
| Document & Vendor | 8001 (+ worker) | Vaidehi | [document-vendor](document-vendor.md) |
| Approval & Inventory | 8002 (+ Temporal worker) | Niraj | [approval-inventory](approval-inventory.md) |
| Contract & Risk | 8003 (+ Temporal worker) | Anjali | [contract-risk](contract-risk.md) |
| Notification | 8004 | Anooj | [notification](notification.md) |
| Auth & business rules | 8005 | Anooj | [auth](auth.md) |
| Assistant (chatbot) | 8006 | Anooj | [assistant](assistant.md) |

How they talk to each other:

| Event | From | To |
|---|---|---|
| `document.ingested` | Document & Vendor (API) | Document & Vendor (worker) |
| `document.classified`, `vendor.matched` | Document & Vendor | Approval & Inventory, Contract & Risk, Notification |
| `approval.requested`, `approval.decided` | Approval & Inventory | Contract & Risk, Notification, Document & Vendor |
| `contract.generated`, `contract.signed` | Contract & Risk | Approval & Inventory, Notification |
| `risk.score.updated`, `vendor.offboarded` | Contract & Risk | Notification |
| `reminder.due`, `notification.send` | all three agents | Notification |
| `business_rule.updated` | Auth | all agents |

The full event catalogue with payloads is `shared/schemas/events.md`.
