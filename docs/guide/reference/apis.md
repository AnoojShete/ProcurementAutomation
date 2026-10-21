# APIs

Everything goes through the gateway at `http://localhost:8080/api/…`.
Each service also serves interactive OpenAPI docs on its own port in
development (`http://localhost:8001/docs` … `8005/docs`).

## Conventions

- **Auth**: `Authorization: Bearer <access token>` from `POST /api/auth/login`.
  The refresh token is an httpOnly cookie. Identity always comes from the token.
- **Responses**: `{"data": …, "meta": …}`; errors are
  `{"error": {"code": "…", "message": "…"}}`.
- **Idempotency**: create endpoints accept an `Idempotency-Key` header.
- **Correlation**: every response carries `X-Correlation-ID`; search it in the
  Control Panel's Kafka log or Grafana.

```bash
TOKEN=$(curl -s -X POST localhost:8080/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@demo.example.com","password":"DemoPass123!"}' | jq -r .data.access_token)
curl -s localhost:8080/api/contracts/esign/documents -H "Authorization: Bearer $TOKEN"
```

## Routes by service

| Gateway prefix | Service | Main endpoints |
|---|---|---|
| `/api/documents/` | document-vendor | `POST upload`, `POST upload/batch`, `GET /`, `GET /{id}`, `GET /{id}/file`, `GET /{id}/validation`, `POST /{id}/review` |
| `/api/vendors/` | document-vendor (risk: contract-risk) | onboarding, payment-change verification; `/{id}/risk`, `/{id}/clearance` |
| `/api/gst/` | document-vendor | GST checks, GSTR-2B reconciliation |
| `/api/admin/control-panel/` | document-vendor | `GET inbox`, `GET events`, `GET failed-events`, `GET storage` |
| `/api/requests/`, `/api/inbox/` | approval-inventory | create, list, `POST /{id}/approve`, `/{id}/reject`, `/{id}/receive`; `GET /inbox/{level}` |
| `/api/authority/` | approval-inventory | approver assignments, delegations |
| `/api/budgets/`, `/api/catalog/`, `/api/rfqs/` | approval-inventory | budgets, IT catalog, requests for quotation |
| `/api/inventory/`, `/api/licenses/`, `/api/invoices/`, `/api/tds/`, `/api/orders/`, `/api/ops/` | approval-inventory | stock, licences, invoice ledger, TDS/MSME, order summary, outbox/DLQ operations |
| `/email-action/` | approval-inventory | single-use approve / reject links from emails |
| `/api/contracts/` | contract-risk | list, `/{id}`, `POST generate`, `POST /{id}/send-for-signature`, `POST /{id}/sign`, `GET /{id}/document`, `GET /{id}/signed-document`, `GET /{id}/signature-certificate`, `GET esign/documents`, obligations |
| `/api/webhooks/` | contract-risk | `POST esign` (HMAC-signed provider callback) |
| `/api/notifications/` | notification | `log`, `feed`, `unread-count`, `read-all`; `templates` (GET, POST, PUT, DELETE, `/{name}/preview`) |
| `/api/auth/` | auth | register, verify, login, refresh, logout, forgot/reset password, users |
| `/api/admin/business-rules` | auth | list, update (with reason), history |
| `/api/chat/` | chatbot | sessions and messages |

## Events (Kafka)

The event catalogue, with each topic's producer, consumers and payload, is
`shared/schemas/events.md`; topics are listed in `shared/kafka-topics.yaml` and
permissions in `infra/redpanda/acls.conf`.
