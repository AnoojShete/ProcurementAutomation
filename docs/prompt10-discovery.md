# Prompt 10 Discovery Document

As required by **Prompt 10 Section 0.1**, this document maps all existing codebase structures, services, database models, background workflows, and frontend components relevant to the Prompt 10 implementation.

---

## 1. Shared Approval Decision Function & Channel Parameter (Prompt 8 A1 / Prompt 10 0.2)

- **Entry Point**: `ApprovalService.process_decision` in [`services/approval-inventory-agent/app/services/approval_service.py`](file:///d:/ProcurementAutomation/services/approval-inventory-agent/app/services/approval_service.py).
  - Validates request existence and status (`pending_approval`).
  - Calls `check_request_authority` in [`services/approval-inventory-agent/app/services/approval_authority.py`](file:///d:/ProcurementAutomation/services/approval-inventory-agent/app/services/approval_authority.py) to enforce segregation of duties, delegation resolution, level match, and spend limit checks.
  - Signals Temporal workflow handle `approval-{request_id}` with `approval_signal` containing `{decision, decided_by, comments, level_index, channel}`.
  - Fallback handler `_process_decision_direct` handles inline execution if Temporal is unavailable, recording `ApprovalHistory`, writing `AuditLog`, revoking email tokens, and staging `approval.decided` outbox event with `decision_channel`.
  - Revokes single-use email action tokens via `email_action_token_service.revoke_tokens`.
- **Temporal Workflow**: `ApprovalWorkflow` in [`services/approval-inventory-agent/app/workflows/approval_workflow.py`](file:///d:/ProcurementAutomation/services/approval-inventory-agent/app/workflows/approval_workflow.py) receives `ApprovalSignal` dataclass and triggers `record_approval_decision`, `publish_approval_decided_event`, and `update_request_status` activities.
- **Kafka / Outbox Event**: `publish_approval_decided` in [`shared/eventing/outbox.py`](file:///d:/ProcurementAutomation/shared/eventing/outbox.py) emits `approval.decided`.
- **Prompt 10 Extension**: Add `bulk_batch_id: Optional[str] = None` to `process_decision`, `ApprovalSignal`, `record_approval_decision`, `publish_approval_decided`, and Kafka payload.

---

## 2. Email-Action Token Tables & Endpoints

- **Data Models**:
  - `EmailActionToken` in [`services/approval-inventory-agent/app/models.py`](file:///d:/ProcurementAutomation/services/approval-inventory-agent/app/models.py): contains `id`, `token_hash`, `request_id`, `step_index`, `approver_id`, `expires_at`, `used_at`, `revoked_at`, `revoked_reason`.
- **Token Service**:
  - [`services/approval-inventory-agent/app/services/email_action_token_service.py`](file:///d:/ProcurementAutomation/services/approval-inventory-agent/app/services/email_action_token_service.py): provides `mint_email_action_token`, `hash_token`, `evaluate_step_up`, `revoke_tokens`.
- **Endpoints**:
  - Public: [`services/approval-inventory-agent/app/api/email_action.py`](file:///d:/ProcurementAutomation/services/approval-inventory-agent/app/api/email_action.py)
    - `GET /email-action/{token}`: Renders HTML review page without modifying state.
    - `POST /email-action/{token}/decide`: Atomically locks token row, checks validity, verifies step-up rules, calls `ApprovalService.process_decision(channel="email")`.
  - Internal: [`services/approval-inventory-agent/app/api/internal_email_action.py`](file:///d:/ProcurementAutomation/services/approval-inventory-agent/app/api/internal_email_action.py)
    - `POST /internal/email-action/mint`: Mint single-action email tokens (authenticated via `X-Internal-Service-Token`).
- **Templates**:
  - Located in `services/approval-inventory-agent/app/templates/email_action/` (`decision_page.html`, `status_page.html`).
- **Prompt 10 Extension**:
  - Add table `email_batch_tokens` in `approval-inventory-agent`.
  - Add internal endpoint `POST /internal/email-action/mint-batch` (only invoked after notification agent idempotency check).
  - Add public endpoints `GET /email-action/batch/{token}` and `POST /email-action/batch/{token}/decide`.
  - Add Jinja2 template `batch_page.html`.

---

## 3. Approver Inbox, Request Detail, & Contract Detail Pages

- **Approver Inbox**:
  - [`frontend/src/pages/approvals/ApprovalInboxPage.tsx`](file:///d:/ProcurementAutomation/frontend/src/pages/approvals/ApprovalInboxPage.tsx)
  - Displays pending approval requests. Currently incorporates DataTable with row checkboxes. Needs Gmail-style banner, indeterminate header, live threshold checks against `approval.bulk_approve_max_amount`, sticky cap indicator, and confirmation modal with `acknowledged_auto_sign`.
- **Request Detail**:
  - [`frontend/src/pages/requests/RequestDetailPage.tsx`](file:///d:/ProcurementAutomation/frontend/src/pages/requests/RequestDetailPage.tsx)
  - Contains `DocketHeader`, `LedgerStrip`, line items, document viewer, and audit timeline. Needs sticky Next-Action Bar immediately below docket header with server-computed `next_action`.
- **Contract Detail**:
  - [`frontend/src/pages/contracts/ContractDetailPage.tsx`](file:///d:/ProcurementAutomation/frontend/src/pages/contracts/ContractDetailPage.tsx)
  - Shows contract status, terms, signatory block, and digital signature modal. Needs Next-Action Bar and `signing_method` / mandate label below signature block.
- **Certificate Modal**:
  - [`frontend/src/components/contracts/SignatureCertificateModal.tsx`](file:///d:/ProcurementAutomation/frontend/src/components/contracts/SignatureCertificateModal.tsx)
  - Modal displaying certificate metadata, hash, and timestamps. Needs explicit signing method / channel and mandate annotation.

---

## 4. Reorder-Suggestion Code & Inventory Page

- **Reorder Logic**:
  - [`services/approval-inventory-agent/app/services/reorder.py`](file:///d:/ProcurementAutomation/services/approval-inventory-agent/app/services/reorder.py): Functions `suggest` and `reorder_status`. Reads rules `inventory.reorder_point_pct` (default 20%) and `inventory.reorder_quantity_pct` (default 25%).
- **Inventory API**:
  - [`services/approval-inventory-agent/app/api/inventory.py`](file:///d:/ProcurementAutomation/services/approval-inventory-agent/app/api/inventory.py): `list_inventory` enriches hardware inventory with `reorder` status.
- **Inventory Page**:
  - [`frontend/src/pages/inventory/InventoryPage.tsx`](file:///d:/ProcurementAutomation/frontend/src/pages/inventory/InventoryPage.tsx): Renders Reorder Suggestions table.
- **Reorder to Purchase Request**:
  - [`frontend/src/components/inventory/PlaceReorderModal.tsx`](file:///d:/ProcurementAutomation/frontend/src/components/inventory/PlaceReorderModal.tsx): To be expanded into a comprehensive drawer with last order unit price/vendor lookup, duplicate open request guard (`Request already open - view`), remaining budget calculation, vendor clearance badge, and `source: "reorder_suggestion"`.

---

## 5. Contract Generation, Internal Signing, & Certificate Code

- **Generation**:
  - [`services/contract-risk-agent/app/services/contract_service.py`](file:///d:/ProcurementAutomation/services/contract-risk-agent/app/services/contract_service.py): `generate_contract_for_request` generates draft contracts based on standardized markdown templates. Triggered by Kafka consumer in [`services/contract-risk-agent/app/kafka/consumer.py`](file:///d:/ProcurementAutomation/services/contract-risk-agent/app/kafka/consumer.py) on `approval.decided` when fully approved.
- **Digital Signing**:
  - `sign_contract_digitally` in `contract_service.py`: Computes SHA-256 seal over contract text and signatory info, transitions contract to `signed`, and records certificate in `AuditLog`.
- **PDF Generation**:
  - [`services/contract-risk-agent/app/services/contract_pdf.py`](file:///d:/ProcurementAutomation/services/contract-risk-agent/app/services/contract_pdf.py): `render_contract_pdf` and `render_signed_contract_pdf`. Generates ReportLab PDF with signature block and completion certificate.
- **Signing Mandates**:
  - New table `signing_mandates` in `contract-risk-agent`.
  - Temporal auto-sign activity and consumer handler: when `approval.decided` is fully approved, finance step was in bulk/email, mandate is active, and constraints hold, automatically sign without external provider.

---

## 6. Sidebar Config (`roleNav`) & System Hub

- **Sidebar Config**:
  - [`frontend/src/lib/roleNav.ts`](file:///d:/ProcurementAutomation/frontend/src/lib/roleNav.ts): Defines `ROLE_NAV` for each role and `SYSTEM_SECTIONS`.
- **System Hub**:
  - Accessible at `/app/system`, links to `System Health`, `Users`, `Controls`, `Control Panel`, `Business Rules`, `Audit & Activity`, and `Email & SMTP`.
- **Sidebar Clean-up**:
  - Verified: `Control Panel` and `Email Settings` removed from direct `ROLE_NAV.admin` sidebar. Deep links preserved and `match` array handles active highlighting.

---

## 7. Theme Tokens & Tailwind Configuration

- **Tokens CSS**:
  - [`frontend/src/styles/tokens.css`](file:///d:/ProcurementAutomation/frontend/src/styles/tokens.css): Defines `:root` variables in bare RGB format for Tailwind opacity support:
    - `--paper`: App background
    - `--sheet`: Card / sheet background
    - `--sheet-sunk`: Secondary background / table headers
    - `--rule`, `--rule-mid`, `--rule-strong`: Borders and hairlines
    - `--ink`, `--ink-2`, `--ink-3`: Text hierarchy
- **Tailwind Mapping**:
  - [`frontend/tailwind.config.js`](file:///d:/ProcurementAutomation/frontend/tailwind.config.js): Maps `paper`, `sheet`, `rule`, `ink`, `brand`, `slate` to CSS variables.
- **Prompt 10 Section 5.1 Ivory Palette Requirement**:
  - Background: `#FAF7F0` (`250 247 240`)
  - Surface: `#FFFEFA` (`255 254 250`)
  - Surface-alt: `#F4F0E6` (`244 240 230`)
  - Border: `#E6E0D2` (`230 224 210`)
  - Text: `#1F2430` (`31 36 48`)
  - Muted text: `#5E6472` (`94 100 114`)

---

## 8. Business Rules Registry & Seeding Migrations

- **Registry API**:
  - [`services/auth-service/app/api/business_rules.py`](file:///d:/ProcurementAutomation/services/auth-service/app/api/business_rules.py): Admin CRUD for rules, read access for approvers/finance.
- **Rule Evaluation**:
  - [`shared/rules_engine.py`](file:///d:/ProcurementAutomation/shared/rules_engine.py): `get_rule(key, fallback)` queries the cache/database at execution time.
- **Seeding Pattern**:
  - Alembic migrations in [`services/auth-service/migrations/versions/`](file:///d:/ProcurementAutomation/services/auth-service/migrations/versions/) insert-only with default keys, categories, and validation bounds.
- **New Prompt 10 Rules**:
  - `approval.bulk_approve_enabled` (bool, default true)
  - `approval.bulk_approve_max_amount` (decimal, default 25000, must be <= `approval.email_action_max_amount`)
  - `approval.bulk_approve_max_items` (int, default 25, 1-100)
  - `approval.bulk_approve_max_batch_total` (decimal, default 250000, >= max_amount)
  - `approval.bulk_email_enabled` (bool, default true)
  - `approval.bulk_email_token_ttl_hours` (int, default 48, 1-168)
  - `approval.bulk_actions_per_hour` (int, default 20)
  - `approval.bulk_excluded_request_types` (json, default `[]`)
  - `approval.bulk_digest_enabled` (bool, default true)
  - `approval.bulk_digest_time_ist` (string, default "09:00")
  - `approval.bulk_digest_min_items` (int, default 2)
  - `contract.auto_sign_enabled` (bool, default false)
  - `contract.auto_sign_max_amount` (decimal, default 25000)
  - `contract.auto_sign_allow_email_channel` (bool, default true)
  - `contract.mandate_max_days` (int, default 90)
  - `vendor.petty_tier_max_amount` (decimal, default 5000)
