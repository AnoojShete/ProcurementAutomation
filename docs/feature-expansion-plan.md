# Feature expansion plan: closing the gaps with commercial suites

Status (20 October 2026): **Phases 1, 2 and 3 built** (see their sections); Phases 4–8 are proposals.
Inputs: [competitive-analysis.md](competitive-analysis.md) (Coupa, Zapro, SAP
Ariba, Ivalua, TYASuite) and Zoho's buyer's guide
(https://www.zoho.com/procurement/academy/procurement-software.html), which
adds sourcing depth (multi-round events, weighted scoring, sealed bids,
supplier scorecards), approval routing by cost centre / category / risk,
verified bank-detail capture, partial goods receipts, and four evaluation
"break points": catalogs, non-PO invoices, partial receipts and tax
treatment.

## 0. Ground rules

Every feature below is designed **for IT procurement** (hardware, software
licences, SaaS subscriptions, IT services) and must **not undo anything
already built**:

| Existing decision (TODO A.4, CLAUDE.md) | How this plan respects it |
|---|---|
| Five services + workers, one Postgres, Kafka with outbox | New tables go into the owning service's migrations; new events go through `staged()` + `deliver()`; every new topic is added to `shared/kafka-topics.yaml`, `infra/redpanda/acls.conf` and `shared/schemas/events.md` |
| Business rules are data | Every threshold is a rule seeded by an auth-service Alembic migration, listed in `docs/business-rules.md`, with a `test_<key>` behaviour test |
| Identity only from the JWT | Supplier users get their own role and a `vendor_id` claim; no endpoint trusts a body field for identity |
| Bank-detail changes need a second person; invoices are held until bank details are verified | The supplier portal and payment runs feed the **existing** dual-control queue and `payment_hold`; nothing bypasses them |
| Built-in e-sign only; risk shown before signing | Untouched; obligations are read from the signed contract |
| Review gate stays heuristic until the research supports switching (RS-11) | No feature changes `confidence.py`; agents read its output only |
| Currency stored in original + INR | Budgets, RFQ comparison and payments use `total_inr` |
| Email automation and the chatbot are **Anooj's** | New notifications are new event types; their templates and any assistant tools are listed as hand-offs to Anooj, not built here |
| Decision-support system; **payment execution and ERP integration are out of scope** (report §3.2) | Phases 6 and 8 are designed so that money still moves only at the bank and the ERP stays the book of record. **Both need a scope decision before they start** |
| One home page per item; each agent's actions in one component; Ledger design system | Each feature names the page it lives on and the component that owns its actions |

Impact test: a feature is in only if it saves money, prevents a loss, or
removes manual work **that is specific to buying IT**. Explicitly left out:
reverse auctions (destroy reseller relationships for small IT volumes, need a
live bidding room), corporate cards and expenses (not procurement of IT), and
generic marketplace browsing.

## 1. Feasibility ranking

| Rank | Feature | Data already in the system | External dependency | Main risk | Feasibility |
|---|---|---|---|---|---|
| 1 | Budget control before approval | requests, departments, request types, invoice ledger, 3 budget rules seeded | none | budget data entry | **High** |
| 2 | Contract obligation tracking | signed contract text, Legal-BERT (CUAD), renewal workflow | none | model accuracy per clause type | **High** |
| 3 | Sourcing: IT catalog, RFQ events, quote comparison, scorecards, partial receipts | quotes already read by the pipeline, vendor risk scores, delivery signals | none (vendors reply by e-mail) | lifecycle change for partial receipts | **High–medium** |
| 4 | Indian GST and TDS compliance | GSTIN validation, currency agent, extracted totals and tax | GST portal files uploaded by hand (no paid GSP API) | tax rules must be confirmed by a CA | **Medium** |
| 5 | Proposal agents (AI) | outputs of phases 1–4, licence model, risk model | optional local LLM (Ollama) | over-claiming autonomy | **Medium** |
| 6 | ERP integration | everything above, as events | a test ERP (Tally Prime trial, Zoho Books sandbox) | mapping per customer; **scope decision** | **Medium–low** |
| 7 | Supplier portal and punch-out | vendors, quotes, invoices, bank-change queue, `vendors.portal_access_revoked` already exists | internet-facing login; resellers supporting cXML | new external attack surface | **Low** |
| 8 | Payment runs | matched invoices, holds, bank verification, TDS (phase 4) | bank bulk-upload formats | moving money; **scope decision** | **Lowest** |

"Large sets of AI agents" is deliberately **not** a chat-driven autonomy
layer. It becomes Phase 5: a small number of measurable *proposal agents* that
watch the data produced by phases 1–4 and put recommendations into the
existing approval inbox.

## 2. Phases at a glance

| Phase | Contents | Services touched | New topics | Effort* | Exit criterion |
|---|---|---|---|---|---|
| 1 | Budget control; routing by category and vendor risk | approval-inventory, auth (rules), frontend | `budget.threshold_crossed` | 2–3 wk | An over-budget request gets a finance step; the request page shows remaining budget |
| 2 | Contract obligations (SLA, licence limits, price caps, audit rights, warranties) | contract-risk, approval-inventory (seat check), frontend | `contract.obligation.due` | 3 wk | Obligations extracted from a signed contract, each with an owner and reminders; per-clause model kept only if it beats rules on CUAD |
| 3 | IT catalog; RFQ events with weighted scoring, sealed bids, rounds; supplier scorecards; partial goods receipts | approval-inventory, document-vendor, contract-risk (read), frontend | `rfq.issued`, `rfq.awarded`, `goods.received` | 4–5 wk | A laptop refresh runs RFQ → award → request → partial receipt → invoice matched against received quantity |
| 4 | GST validation, reverse charge on imported SaaS, e-invoice QR check, TDS, GSTR-2B reconciliation, MSME 45-day tracking | document-vendor, approval-inventory, frontend | `invoice.tax_flagged` | 3–4 wk | Every invoice shows tax treatment, TDS and ITC status; 2B mismatches listed |
| 5 | Proposal agents: SaaS right-sizing, duplicate SaaS, quote evaluation, invoice exception, budget forecast | approval-inventory, contract-risk workers, frontend | `agent.proposal.created` | 3–4 wk | Each agent has a measured acceptance rate; no agent acts without approval |
| 6 | ERP connectors (generic CSV/JSON, Tally Prime, Zoho Books), outbound webhooks, published API | new `erp-connector` service (decision) | none (consumes existing) | 4 wk | A matched invoice appears as a purchase voucher in Tally; masters imported back |
| 7 | Supplier portal (profile, compliance docs, bank change, RFQ response, invoice upload, PO acknowledgement, payment status); punch-out | auth, document-vendor, approval-inventory, nginx, frontend | `supplier.invoice.submitted` | 5–6 wk | A supplier answers an RFQ and submits an invoice that lands in the existing pipeline |
| 8 | Payment proposals, dual approval, bank bulk file, UTR reconciliation | approval-inventory, frontend | `payment.run.approved`, `payment.completed` | 3 wk | Approved run exports a bank file; uploaded bank response marks invoices paid |

\* Effort in person-weeks for one developer who knows the service, including
tests; parallel work across owners shortens calendar time.

---

## Phase 1 — Budget control before approval

> **Built 20 Oct 2026.** `services/approval-inventory-agent/app/services/budget_service.py`,
> `app/api/budgets.py` (`/api/budgets`), `GET /api/requests/{id}/budget`,
> frontend `/app/budgets`, `/app/budgets/:id` and the request page's *Budget*
> line; rules seeded by auth-service `0015`; topic `budget.threshold_crossed`.
> Verified: 23 new unit tests, `tests/e2e/budget_flow.py` 30/30 (including two
> concurrent requests that can't both fit, and a rule change applied live),
> gateway e2e 17/17 and invoice lifecycle 71/71 unchanged.
>
> Two deliberate changes from the design below:
> 1. **No `budget_commitments` table.** Usage is computed from the requests
>    that point at a budget and the invoice allocations booked against them
>    (pending → committed → consumed), so it follows every status change
>    (Temporal workflow, direct fallback, cancellation, split) without hooks
>    that could be missed. A request counts from creation, which is what
>    makes the concurrency guarantee possible.
> 2. **`approval.high_risk_vendor_requires_finance` defaults to `false`**, so
>    turning Phase 1 on changes no existing flow or demo; admins switch it on.

### What it is
A budget per **department × IT category × fiscal period** (hardware,
software licences, SaaS, IT services). Every request is checked against what
is left; approval *commits* the money, the invoice *consumes* it, and
rejection or cancellation *releases* it. Over-budget requests are not
blocked by default: they get an extra finance approval step, as the seeded
rule already says.

### Why it matters in IT procurement
IT spend leaks through many small, recurring commitments: SaaS seats added
mid-year, renewals that auto-renew at a higher price, laptops ordered outside
the refresh plan. Coupa, Zapro, TYASuite and Procurify show budget impact
**before** approval; today our request page literally shows *Budget status:
Not available*.

### What exists today
- Rules seeded but inert: `budget.fiscal_period_type` = `"quarterly"`,
  `budget.over_budget_requires_finance_approval` = `true`,
  `approval.email_action_allowed_over_budget` = `false`.
- `purchase_requests.department`, `request_type`
  (`hardware|license|saas|reclaim|reinstate`), `amount`, `currency`; the
  invoice ledger books invoices against requests.
- Approval chains are built from spend tiers; delegation exists
  (`approval_delegations`).

### Design
**Owner:** approval-inventory-agent (requests and the ledger live there).

Data (append to `migrations/0001_schema_extensions.sql`, idempotent):

| Table | Columns | Notes |
|---|---|---|
| `budgets` | `id`, `fiscal_year` (e.g. `2026-27`), `period` (`Q1..Q4` or `FY`), `department`, `category` (`hardware|software|saas|services`), `amount_inr`, `owner_email`, `created_by`, `updated_at` | unique (fiscal_year, period, department, category) |
| `budget_commitments` | `id`, `budget_id`, `request_id`, `amount_inr`, `state` (`committed|consumed|released`), `document_id` (when consumed), `created_at`, `updated_at` | one row per request; consumed per invoice allocation |
| `purchase_requests` + columns | `budget_id`, `budget_status` (`within|warning|over|no_budget`), `budget_checked_at` | CHECK on `budget_status` |

Category mapping: `hardware → hardware`, `license → software`,
`saas → saas`, IT services come from the catalog (Phase 3) or the
requester's choice. `reclaim`/`reinstate` never touch budgets.

New business rules (auth-service Alembic migration):

| Key | Default | Effect |
|---|---|---|
| `budget.fiscal_year_start_month` | `4` | Indian fiscal year April–March |
| `budget.warning_threshold_pct` | `0.8` | Request turns *warning* when it takes the budget past 80 % |
| `budget.block_when_over` | `false` | If true, over-budget requests are refused at creation (default keeps approval flow) |
| `budget.no_budget_policy` | `"allow"` | `allow | finance_approval | block` when no budget row exists |
| `approval.high_risk_vendor_requires_finance` | `true` | From Zoho's "route by risk level": High-band vendor adds a finance step |

Existing rules become enforced: `budget.fiscal_period_type`,
`budget.over_budget_requires_finance_approval`,
`approval.email_action_allowed_over_budget`.

Flow:
1. **Create request**: compute `available = amount − committed − consumed`
   for the matching budget row (`SELECT … FOR UPDATE`, same pattern as the
   invoice ledger); store `budget_status`. If *over* and the rule is on,
   append a finance level to `approval_chain` before the workflow starts. If
   the vendor's risk band is High, same.
2. **Approved**: create the commitment in the same transaction as the status
   change (outbox event staged together).
3. **Invoice booked** (`invoice_ledger.book_invoice`): move the allocated
   amount from committed to consumed; any overrun is recorded, not hidden.
4. **Rejected / cancelled / split**: release.
5. Crossing `warning_threshold_pct` publishes `budget.threshold_crossed`
   (budget owner + finance are notified; template is a hand-off to Anooj).

APIs (finance/admin write, everyone with access to a request reads its
budget line): `GET/POST/PATCH /budgets`, `GET /budgets/{id}/ledger`,
`GET /requests/{id}/budget`, `POST /budgets/import` (CSV: department,
category, period, amount).

Frontend:
- Request page: replace *Budget status — Not available* with a
  `LedgerStrip` figure "Budget left after this request" and a `Badge`; the
  finance step shows *"added: over budget"*.
- New `/app/budgets` (finance, admin): table by department × category with
  committed / consumed / left; CSV import. Actions in
  `components/approvals/BudgetActions`.
- Approval inbox: over-budget badge; e-mail approval link refused when the
  rule says so (already wired).

### Tests and acceptance
- Behaviour tests for each new rule (`test_budget_warning_threshold_pct`, …).
- Concurrency: two requests that together exceed a budget, created in
  parallel, can't both be *within*.
- Ledger: invoice above the committed amount shows as overrun.
- e2e: request over budget → finance step → approve → invoice → consumed.

---

## Phase 2 — Contract obligation tracking

> **Built 20 Oct 2026.** contract-risk-agent `app/services/obligation_extraction.py`
> (11 types, value parsers, service-credit maths), `obligation_service.py`
> (lifecycle, sweep), `app/api/obligations.py` (`/api/contracts/{id}/obligations`,
> `/api/contracts/obligations/…`, `/api/contracts/sla-credits/…`), Alembic
> `0008` (`contract_obligations`, `obligation_events`, `sla_credits`), topic
> `contract.obligation.due`, rules seeded by auth-service `0016`; the three
> templates now carry the clauses (SaaS: service credits, licence scope with
> the request's seat count, price protection, audit, data protection,
> liability and insurance; hardware: 36-month warranty; services: termination
> for convenience, exit, liability and insurance). Frontend: the contract
> page's *Obligations* card (`components/contracts/ObligationActions.tsx`) and
> the licence page's "Contract limit: N seats · M assigned" line. Evaluation
> script `ml/evaluate_obligation_model.py`; results in
> `docs/results/obligations.{json,md}`.
>
> Deliberate changes from the design below:
> 1. **A sweep, not a Temporal workflow per obligation.** One loop in the
>    contract-risk API (every 60 s) reads newly signed contracts, sends due
>    reminders (deduplicated by an `obligation_events` row) and compares
>    licence seats. Hundreds of mostly idle workflows would add nothing a
>    query over `due_date` doesn't already give, and a confirmed date can be
>    edited without signalling a workflow.
> 2. **Extraction after signature, in the background**, not during
>    generation: nine more Legal-BERT questions add about a minute per
>    contract. The contract page shows "reading…" until it is done.
> 3. **The seat check runs in that same sweep** (contract-risk reads
>    `licenses`), so a breach shows within a minute rather than a day.
> 4. **The ledger warns whenever a credit is still `expected`** for the
>    request (a note on the match, shown on the document page and listed by
>    `GET /api/invoices/ledger/{id}`), rather than guessing from the invoice
>    total whether it was deducted; finance marks the credit *applied*.
>    The note never changes the match status.
> 5. **Actions in their own component** (`ObligationActions`), not inside
>    `ContractActions`, which is the header's signing panel; and a `Card`,
>    since the list has actions.
> 6. `recurrence` is `none | monthly | annual` (no type is quarterly), and
>    there is no `owner_role` / `evidence` column yet (the owner is an e-mail).

### What it is
Every signed contract is read for the commitments that matter after
signature, each stored as an **obligation** with a type, a value, a due date
or recurrence, an owner and a status (*open, met, breached, waived*).
Today we extract only renewal type, notice period and end date.

### IT-specific obligations

| Obligation | Example | What the system does |
|---|---|---|
| SLA uptime and service credits | "99.9 % monthly uptime; 10 % credit per 0.1 % below" | Owner records downtime; the system computes the credit and expects it on the next invoice (ledger warns if the invoice ignores it) |
| Licence grant limits | named users, seat caps, non-transferable, no use outside India | Compared with `licenses.assigned_seats`; over-deployment flagged before a vendor software audit does |
| Renewal price cap | "increase limited to 5 % per year" | At renewal, a quote or invoice above the cap is flagged |
| Audit rights | vendor may audit usage on 30 days' notice | Reminder to export usage evidence; links to licence usage history |
| Warranty duration | 3-year on-site warranty for laptops | Warranty end per asset; reminder before expiry; refresh planning |
| Minimum commitment / volume | minimum 50 seats for 12 months | Reclaim proposals (licence model) respect the floor |
| Termination for convenience, post-termination data return | 90 days' notice; data export within 30 days | Reminder at offboarding (existing `vendor.offboarded`) |
| Data protection / security | DPA, breach notification within 72 h | Checklist item on the contract page |
| Insurance, liability cap | cyber insurance ≥ ₹1 cr; cap = 12 months fees | Shown with the vendor risk factors |

### What exists today
- `clause_model.py`: `alex-apostolo/legal-bert-base-cuad` answers CUAD
  questions; three are asked today. CUAD (41 categories) also covers *Cap on
  Liability, Audit Rights, Warranty Duration, Termination for Convenience,
  Price Restrictions, Minimum Commitment, Volume Restriction, License Grant,
  Non-Transferable License, Post-Termination Services, Insurance*.
- `clause_router.py` (model first, regex fallback, routing logged),
  `renewal_schedule.py` (Temporal reminders 60/30/15 days),
  `reminder_sweep.py`.
- Our own templates already contain an uptime clause ("99.9% uptime,
  measured monthly").

### Design
**Owner:** contract-risk-agent (Alembic migration).

Data:

| Table | Columns |
|---|---|
| `contract_obligations` | `id`, `contract_id`, `type` (enum above), `clause_text`, `value` (jsonb: e.g. `{"uptime_pct": 99.9, "credit_pct_per_step": 10}`), `due_date`, `recurrence` (`none|monthly|quarterly|annual`), `owner_role`, `owner_email`, `status`, `evidence` (jsonb), `extracted_by` (`legal-bert-cuad|regex|manual`), `confidence`, `created_at`, `updated_at` |
| `obligation_events` | `id`, `obligation_id`, `kind` (`met|breach|waived|downtime_recorded|reminder_sent`), `details`, `performed_by`, `created_at` |

Extraction: add the CUAD questions above to `clause_model.py`; SLA uptime
and data-protection clauses (not in CUAD) use regex rules first. **Adoption
rule, as for FR-13:** a clause type uses the model only if it beats the
regex rules on CUAD's test split for that type; results go to
`docs/results/obligations.{json,md}`. Values are parsed into `value` and
**a person confirms each obligation** on the contract page before reminders
start (low confidence → shown as *to confirm*).

Workflow: one Temporal `ObligationWorkflow` per dated or recurring
obligation (same pattern as the renewal workflow), publishing
`contract.obligation.due`. SLA: on *downtime_recorded*, compute the credit
from `value`; store the expected credit; the invoice ledger (approval agent)
receives it with `invoice.matched` handling and warns when the next invoice
total doesn't reflect it.

Licence limits: a daily check in the approval worker compares
`assigned_seats` with the confirmed seat cap and publishes a breach event.

Rules: `contract.obligation_reminder_days` (`[30, 7]`),
`contract.obligation_model_min_confidence` (`0.5`),
`contract.sla_credit_auto_expect` (`true`).

Frontend: Contract page gets an **Obligations** `Section` (read-only list) and
actions *confirm, record downtime, mark met, waive* in
`components/contracts/ContractActions`. Licence page shows "Contract limit:
60 seats · 49 assigned".

### Tests and acceptance
- Per-clause evaluation file exists; model kept only where it beats rules.
- Downtime of 0.3 % below SLA produces the right credit; an invoice ignoring
  it is flagged.
- Seat cap breach flagged within a day.

---

## Phase 3 — Sourcing: IT catalog, RFQ events, scorecards, partial receipts

> **Built 20 Oct 2026.** approval-inventory-agent: `catalog_service.py` +
> `api/catalog.py` (`/api/catalog`), `sourcing_service.py` + `api/rfqs.py`
> (`/api/rfqs`), `receipt_service.py` (`/api/requests/{id}/receipts`), the
> received-quantity check in `invoice_ledger.py`; tables `catalog_items`,
> `rfq_events`, `rfq_invitations`, `rfq_responses`, `goods_receipts`, columns
> `purchase_requests.sourcing_flags` / `rfq_id`, status `partially_received`.
> contract-risk-agent: `scorecard.py`, `GET /api/vendors/{id}/scorecard`,
> Alembic `0009` (`vendor_scorecards`). Rules seeded by auth-service `0017`;
> topics `rfq.issued`, `rfq.awarded`, `goods.received`. Frontend:
> `/app/catalog`, `/app/sourcing`, `/app/sourcing/:id`, the request page's
> delivery panel and *Sourcing* line, the vendor page's scorecard. Demo
> catalog in `seed-demo-data.sh`. Verified by `tests/e2e/sourcing_flow.py`.
>
> Deliberate changes from the design below:
> 1. **Quotes are linked by a sweep, not in the document pipeline.** Every
>    30 s the approval agent links `vendor_quotes` rows that quote an open
>    RFQ's reference and come from an invited vendor (`sweep_quotes`). This
>    keeps document-vendor-agent unchanged and avoids reading a quote
>    before the pipeline has committed it. A buyer can also enter a quote.
> 2. **`invoice.match_against_received` applies only once a request has a
>    goods receipt.** Invoices often arrive before the goods (the invoice
>    lifecycle test does exactly that); applying the rule to every request
>    would turn all of them into variances. With receipts, an invoice line
>    above the received quantity is a variance — the true three-way match.
> 3. **Catalog categories are hardware, software and SaaS.** There is no
>    services request type yet, so fixed-price IT services are left out.
>    Price drift is handled by `valid_until` and switching an item off; a
>    contract price change does not yet update the catalog by itself.
> 4. **A catalog seat add-on beyond the contract's seat limit (Phase 2) is
>    flagged on the request, not refused**, since buying more seats may be
>    the reason for amending the contract.
> 5. **The scorecard is computed on demand** (each vendor page view) and
>    for all vendors once a day, rather than only nightly.
> 6. **An RFQ needs at least two vendors** (three is suggested in the UI);
>    the request page shows the RFQ flag as a note (advisory) as designed.

### 3a. IT catalog

**What it is:** a curated list of approved IT items with negotiated prices:
standard laptop configurations ("Developer laptop — 32 GB, 3-year
warranty"), monitors and peripherals, approved software titles, SaaS seat
add-ons for existing subscriptions, and fixed-price IT services. Requesters
pick from it instead of typing free text.

**Why:** standardisation is where IT saves most (fewer models to support,
volume pricing, warranty alignment). Catalog requests are faster to approve
because the price is already agreed and linked to a contract; and they
answer Zoho's "catalog" break point.

**Design (approval-inventory-agent):**

| Table | Columns |
|---|---|
| `catalog_items` | `id`, `sku`, `name`, `category`, `vendor_id`, `contract_id` (price source), `unit_price`, `currency`, `spec` (jsonb), `inventory_sku` (link to stock), `license_id` (for seat add-ons), `lead_time_days`, `warranty_months`, `active`, `valid_until` |

- The request wizard gets a *From catalog* tab; items carry price, vendor and
  category, so the budget check (Phase 1) and the spend tier are exact.
- Stock first: if `inventory_sku` has stock, the existing reservation logic
  applies; otherwise the request goes to the catalog vendor.
- **SaaS seat add-on**: fulfilling the request increases
  `licenses.total_seats`, so the licence model and the reclaim logic see
  the new seats immediately (and the Phase 2 seat cap is checked first).
- Rule `catalog.preapproved_max_inr` (default `0` = off): catalog requests at
  or below it skip the manager step (separation of duties unchanged).
- Price drift: a catalog item whose contract price changed or expired
  (`valid_until`) is hidden.

### 3b. RFQ events and quote comparison

**What it is:** for purchases above a threshold (a laptop refresh, a new SaaS
tool, a network upgrade) the buyer runs a request-for-quotation event: invite
3+ vendors, collect quotes by a deadline, compare them on weighted criteria,
optionally run a second round with a shortlist, and award.

**What exists:** the document pipeline already reads quotes
(`vendor_quotes`: number, valid until, total, line items), and a dropped
quote already becomes a purchase request.

**Design:**

| Table (approval-inventory) | Columns |
|---|---|
| `rfq_events` | `id`, `reference` (`RFQ-xxxxxx`), `request_id` (optional draft request), `title`, `items` (jsonb), `criteria` (jsonb weights), `sealed` (bool), `round`, `deadline`, `status` (`draft|open|closed|awarded|cancelled`), `created_by`, `awarded_vendor_id`, `awarded_quote_id` |
| `rfq_invitations` | `rfq_id`, `vendor_id`, `invited_at`, `responded_at`, `declined_reason` |
| `rfq_responses` | `rfq_id`, `vendor_id`, `round`, `quote_id` (→ `vendor_quotes.id`), `lead_time_days`, `warranty_months`, `support_terms`, `score` (jsonb per criterion), `submitted_at` |

- **Responses arrive through channels we already have.** Vendors reply by
  e-mail to the intake address (or later the portal) with the RFQ reference
  on the quote; the pipeline extracts `RFQ-xxxxxx` the same way it extracts
  `PO-xxxxxxxx` (`find_po_reference`) and links the quote. No new upload
  path.
- **Weighted scoring** (Zoho: price and non-price): default criteria and
  weights as a rule `sourcing.default_criteria` =
  `{"price": 0.45, "lead_time": 0.15, "warranty": 0.1, "support": 0.1,
  "vendor_risk": 0.1, "delivery_record": 0.1}`. Vendor risk comes from
  contract-risk-agent's `GET /vendors/{id}/risk`; delivery record from the
  scorecard (3c). Price is compared on `total_inr` for the same items.
- **Sealed bids:** while `sealed` and before the deadline, the API returns
  only *who has responded*, never amounts (also to admins); the comparison
  opens at the deadline. Audit logged.
- **Rounds:** *start round 2* invites a shortlist and keeps round-1 scores
  for reference.
- **Award** fills the purchase request's vendor, items and amount from the
  winning quote and starts the normal approval workflow (budget check
  included). Losing vendors are notified (template hand-off to Anooj).
- Rule `sourcing.rfq_required_above_inr` (default `200000`): requests above
  it without an RFQ or a catalog/contract price get a *sourcing* flag on the
  request page (advisory, not blocking).
- Events: `rfq.issued` (notifications: invitations), `rfq.awarded`.

Frontend: RFQ home page `/app/sourcing/:id` with invitations, responses,
comparison table (scores per criterion, `LedgerStrip` for the best total) and
actions in `components/approvals/SourcingActions` (issue, extend deadline,
next round, award).

**Not built:** reverse auctions (see §0).

### 3c. Supplier scorecards

Computed nightly per vendor from data we already have: on-time delivery
(receipt date vs expected), invoice accuracy (share of invoices matched
without variance, from `invoice_matches`), RFQ response rate, SLA breaches
(Phase 2), current risk band. Shown on the vendor page as a `LedgerStrip`;
used by RFQ scoring. Owner: contract-risk-agent (already computes
platform-history risk signals).

### 3d. Partial goods receipts (true three-way match)

**What it is:** receiving 30 of 50 laptops now and 20 next week. Today
*Mark as received* receives the whole request.

**Design:**
- `goods_receipts` (`id`, `request_id`, `lines` jsonb with received
  quantities, `received_by`, `received_at`, `notes`, `asset_tags` jsonb) —
  serial numbers / asset tags captured per laptop for warranty tracking
  (Phase 2).
- New status `partially_received` in `shared/lifecycle.py` and the DB CHECK
  constraint (migration checks existing data first).
- Invoice ledger: rule `invoice.match_against_received` (default `true`):
  an invoiced quantity above the **received** quantity is a variance — that
  turns today's request-based match into a real three-way match.
- Event `goods.received` (stock levels, scorecard, budget unaffected).

### Tests and acceptance (Zoho break points)
- **Catalog:** a seat add-on increases licence seats; an expired catalog price
  can't be ordered.
- **Partial receipts:** invoice for 50 when 30 received → variance; second
  receipt → match.
- **Non-PO invoice:** still routed to review with *no purchase request* (as
  today) and can be linked to an RFQ award.
- Sealed bid amounts are not returned before the deadline, by any role.

---

## Phase 4 — Indian GST and TDS compliance

**Owners:** document-vendor-agent (tax extraction and validation at read
time), approval-inventory-agent (TDS at booking, 2B reconciliation, MSME due
dates). **All rates and thresholds are business rules seeded with the values
current in October 2026 and must be confirmed by the finance team or a
chartered accountant before use.**

### What it is and why it matters for IT
- IT services and software attract GST (typically 18 %); whether it is
  CGST + SGST or IGST depends on the vendor's and buyer's states — a wrong
  split means input tax credit (ITC) is lost.
- **Imported SaaS** (USD invoices from foreign vendors with no GSTIN) is
  usually under **reverse charge**: the buyer pays the GST. Our currency
  agent already sees these invoices; nobody flags the tax today.
- TDS applies to IT services and software payments under different sections
  of the Income-tax Act (e.g. professional/technical services, contracts,
  purchase of goods); the deduction changes the amount actually paid.
- ITC is only available if the vendor's invoice appears in the buyer's
  GSTR-2B; mismatches cost money every month.
- MSME vendors must be paid within 45 days (Income-tax Act s. 43B(h)),
  otherwise the expense isn't deductible that year.

### Design
1. **Tax extraction** (document-vendor): extend `field_extraction.py` to read
   CGST / SGST / IGST amounts, GST rate, HSN/SAC codes, buyer GSTIN, place of
   supply, IRN and the e-invoice QR. New pipeline stage `tax_agent` after
   `currency_agent`, recorded in `pipeline_checkpoints` like every stage.
2. **Validation** (no external API):
   - Intra- vs inter-state from the first two digits of the vendor and buyer
     GSTINs (`gst.buyer_gstin` rule) → expected CGST+SGST or IGST.
   - Rate by SAC/HSN from a small table `gst_rates` (seeded: IT services,
     software, hardware categories; editable).
   - Arithmetic: tax = taxable × rate within tolerance.
   - **E-invoice QR**: the QR is a JWT signed by the invoice registration
     portal; verify the signature offline with the portal's published
     public key and compare IRN, GSTINs and totals with the extracted values.
     Rule `gst.einvoice_required_turnover_inr` decides when a missing QR is
     flagged.
   - **Reverse charge**: foreign vendor (no GSTIN, non-INR) + services →
     `reverse_charge = true`; finance sees the GST payable.
   - Result stored on the document (`tax_check` jsonb); failures publish
     `invoice.tax_flagged` and force review (an existing mechanism:
     `needs_review_forced`), **without changing the confidence score**, so
     the research comparison stays valid.
3. **TDS at booking** (approval-inventory): `tds_sections` table (section,
   description, rate with PAN, rate without PAN, threshold, applies-to
   categories) seeded and editable; vendor gets `pan`, `tds_section_default`,
   `lower_deduction_certificate` (rate, valid until). The ledger stores
   `tds_amount` and `net_payable` per invoice allocation. Feeds Phases 6 and
   8.
4. **GSTR-2B reconciliation**: finance downloads the 2B JSON from the GST
   portal and uploads it (no paid GSP integration). Matching by vendor GSTIN
   + invoice number + taxable value + tax, with fuzzy invoice numbers (reuse
   the duplicate-check scorer). Output: matched, missing in 2B (ITC at risk —
   chase the vendor), in 2B but not in our books. Page `/app/finance/gst`.
5. **MSME 45-day tracking**: vendor fields `msme_udyam_number`,
   `msme_category`; due date = acceptance date + rule `msme.payment_days`
   (`45`); dashboard of invoices approaching the limit; feeds Phase 8.

### Acceptance (Zoho's "tax treatment" break point)
- Intra-state invoice with IGST → flagged; correct split → passes.
- Foreign SaaS invoice in USD → reverse charge flagged, GST payable shown.
- Valid e-invoice QR verifies; altered total fails.
- 2B upload lists a missing invoice.

---

## Phase 5 — Proposal agents (the "AI agents" gap)

### What it is
Coupa, SAP Ariba and Zapro market many AI agents. For an auditable IT
procurement platform the useful version is a **small set of proposal
agents**: background jobs in the existing workers that watch the data, apply
the existing models and rules, and put a **proposal with evidence** into the
approval inbox. A person accepts or rejects; the agent never acts alone.
This matches our agent definition (report §2.2.8) and does not touch the
chatbot.

### The agents

| Agent | Watches | Proposes | Impact metric |
|---|---|---|---|
| **SaaS right-sizing** | licence usage (anomaly model), contract renewal + notice deadline (Phase 2), seat floor | "Reduce Slack from 120 to 95 seats before 1 Mar (notice deadline): saves ₹3.0 L/yr" | ₹ saved per accepted proposal |
| **Duplicate SaaS / shadow IT** | licences, vendors, invoices by category across departments | "Notion and Confluence both in use by Engineering; 40 users overlap" | overlapping spend found |
| **Quote evaluation** | RFQ responses (Phase 3) | Ranked recommendation with the score breakdown and caveats (expiring validity, high-risk vendor) | time to award |
| **Invoice exception** | invoices held for variance, tax flags, missing receipts | Concrete fix: "request credit note for ₹1,600 (price above contract)" or "record receipt for 20 units" | time to resolve a held invoice |
| **Budget forecast** | budgets, commitments, scheduled renewals, catalog refresh plans | "IT-Engineering SaaS budget will be exceeded in Q4 by ₹2.1 L because of 3 renewals" | forecast error per quarter |

### Design
- **Owners:** right-sizing, duplicate SaaS, invoice exception, budget
  forecast in the approval-inventory worker; quote evaluation in the same
  worker (RFQ owner). No new service.
- Table `agent_proposals` (`id`, `agent`, `subject_type`, `subject_id`,
  `summary`, `evidence` jsonb, `estimated_saving_inr`, `status`
  (`open|accepted|rejected|expired`), `decided_by`, `decided_at`,
  `outcome` jsonb). Event `agent.proposal.created`.
- Accepting a proposal calls the **existing** action (create a reclaim
  request, start an RFQ round, open a credit-note request), so every control
  (SoD, budgets, approvals) still applies.
- Rules: `agents.enabled` (list), `agents.min_saving_inr` (`10000`),
  `agents.max_open_per_subject` (`1`).
- Optional plain-language summary through the local Ollama model, off by
  default; the structured evidence is always the source of truth.
  **Hand-off to Anooj:** read-only assistant tools to list proposals.
- Evaluation: acceptance rate and realised savings per agent in
  `docs/results/agents.md`; an agent below `agents.min_acceptance_rate`
  over a quarter is switched off automatically and reported.

---

## Phase 6 — ERP integration  *(scope decision needed)*

### What it is
The ERP stays the book of record for accounts. The platform **exports**
what it decides and **imports** the masters it needs:

| Direction | Object | When |
|---|---|---|
| Out | Vendor master (name, GSTIN, PAN, verified bank details, MSME) | on verification |
| Out | Purchase order (approved/ordered request, lines, GST) | on `approval.decided` / `contract.signed` |
| Out | Purchase bill (matched invoice with GST split, TDS, net payable) | on `invoice.matched` |
| In | GL accounts, cost centres, departments | daily |
| In | Payment status (paid, UTR) | daily, when Phase 8 isn't used |

### Design
- **Recommended:** a new small service `erp-connector` (port 8007) that
  consumes existing events with a read-only Kafka account, keeps
  `erp_sync_log` (object, id, target, status, attempts, last_error,
  external_id) and retries through `deliver()` + `event_dlq`. Keeping it
  separate means no agent learns ERP details. *(Adding a service is an
  architectural decision — confirm first.)*
- Adapters, in order: **generic CSV/JSON over SFTP** (works with anything),
  **Tally Prime** (XML over HTTP; very common in Indian mid-market),
  **Zoho Books** (REST + OAuth). SAP Business One / NetSuite later.
- Mapping screen (admin): our department / category → their cost centre /
  GL account; our vendor id → their ledger name.
- Idempotency: the external system's key is our document / request id, so a
  retry never posts twice.
- **Integration surface** (Zoho guide): publish the existing OpenAPI docs as
  a versioned public API and offer signed outbound webhooks for the same
  events, so customers without a supported ERP can integrate themselves.

Acceptance: a matched invoice appears in Tally Prime (trial) as one purchase
voucher with the right GST and TDS ledgers, once, even after a forced retry.

---

## Phase 7 — Supplier portal and punch-out

### What it is
A separate, minimal web area for **vendors' own staff**:

| Feature | Uses existing… | Note |
|---|---|---|
| Profile and compliance documents (GSTIN, PAN, MSME certificate, insurance) | vendors table, GSTIN/IFSC checks | Expiry reminders |
| **Bank-detail change** through a verified channel (Zoho guide) | `vendor_payment_change_requests` dual-control queue | Never applied directly; second internal person still verifies; `payment_hold` unchanged |
| RFQ responses (structured form + quote upload) | Phase 3 tables, document pipeline | Sealed rules apply |
| Invoice submission | upload service → ClamAV → pipeline, `source = portal` | Vendor is known from the JWT, so no fuzzy vendor match and no look-alike risk |
| PO acknowledgement and delivery dates | requests | Feeds the scorecard |
| Payment status and remittance | invoice ledger, Phase 8 | Read-only |
| Obligation acknowledgements (e.g. SLA reports) | Phase 2 | Upload evidence |

### Design
- **auth-service:** new role `supplier` with a `vendor_id` claim; accounts
  only by invitation from finance (existing one-time token mechanism);
  separate refresh-cookie path `/api/portal`; same argon2id, lockout and
  breach checks; offboarding already sets `vendors.portal_access_revoked`,
  which now ends portal sessions.
- **Separate API prefix** `/api/portal/*` with its own routers in each
  owning service; every query filtered by the JWT's `vendor_id`.
- **Supplier tokens rejected centrally.** `require_role` already refuses
  roles not on its list, but every endpoint that only needs "any signed-in
  user" would accept a supplier token. So supplier tokens carry their own
  audience (`aud = "portal"`), `shared/auth/middleware.get_current_user`
  rejects that audience everywhere except the portal routers, and a root
  test walks every internal route with a supplier token and expects 401/403.
- **nginx:** `/portal` and `/api/portal` exposed; stricter rate limits;
  upload size cap as today.
- **Frontend:** separate minimal shell (`/portal`), same design tokens.

### Punch-out (after the portal)
cXML PunchOutSetupRequest / OrderMessage with IT resellers that support it
(and Amazon Business, as Zapro does): the requester shops on the reseller's
site, the cart returns as a request with prices, and the normal budget and
approval flow follows. Only if a target reseller supports cXML; otherwise
the catalog (Phase 3) covers the need.

Acceptance: a supplier user answers an RFQ and submits an invoice that is
matched by the existing pipeline; a supplier token gets 403/404 on every
internal endpoint; offboarding revokes portal access immediately.

---

## Phase 8 — Payment runs  *(scope decision needed)*

### What it is
The platform **proposes and controls** payments; the bank executes them.

1. **Proposal run** (finance): eligible invoices = matched, no `payment_hold`,
   vendor bank details verified, TDS computed (Phase 4), due by payment terms
   or the MSME 45-day limit; grouped by vendor.
2. **Dual approval:** proposer ≠ approver (same separation-of-duties rule as
   requests); amounts above a rule need a second approver.
3. **Bank file export:** generic bulk-upload CSV per bank template
   (NEFT/RTGS) and ISO 20022 `pain.001`; file hash recorded in the audit log;
   bank details read at export time and compared with the verified record
   (a change after approval invalidates the run).
4. **Reconciliation:** finance uploads the bank's response / statement; UTR
   numbers mark items paid or failed; `payment.completed` notifies the vendor
   (portal, e-mail via Anooj's templates) and the ERP connector.

Data (approval-inventory): `payment_runs` (`id`, `status`
`draft|approved|exported|reconciled|cancelled`, `proposed_by`,
`approved_by`, `file_hash`, …), `payment_items` (`run_id`, `document_id`,
`vendor_id`, `gross`, `tds`, `net`, `bank_snapshot`, `utr`, `status`).
Rules: `payment.second_approver_above_inr`, `payment.run_cutoff_days`.

**Not built:** direct bank API calls, card payments, international wires.

---

## 3. Cross-cutting checklist per feature

For every phase, the pull request is done when:
- [ ] migrations are idempotent and owned by the right service; existing data
      checked before any new constraint;
- [ ] every new rule: Alembic seed, `docs/business-rules.md` row,
      `test_<key>` behaviour test (else `test_business_rules_registry.py`
      fails);
- [ ] every new topic: `kafka-topics.yaml`, `acls.conf`, `events.md`
      (else `test_kafka_acls.py` fails); published via the outbox;
- [ ] identity from the JWT only; object-level access tests for requesters
      and (Phase 7) suppliers;
- [ ] one home page per item; actions in the agent's component; Ledger tokens;
- [ ] notification templates and assistant tools listed as hand-offs to Anooj;
- [ ] every fix proven by reverting it; e2e extended for the new flow;
- [ ] `docs/TODO.md`, `IMPLEMENTATION_PLAN.md`, `project-flow.html`,
      `readmeforme.md` updated.

## 4. Decisions needed before starting

| Decision | Needed for | Options |
|---|---|---|
| Add a service for ERP integration | Phase 6 | new `erp-connector` (recommended) · adapters inside document-vendor-agent |
| Bring ERP export into scope | Phase 6 | yes · stay standalone (then only the public API and webhooks) |
| Bring payment proposals into scope | Phase 8 | yes (bank files only) · stop at "payment readiness" (eligible list, no file) |
| Expose the portal to the internet | Phase 7 | yes, with TLS and the deployment checklist · invitation-only behind VPN |
| Who confirms tax rules | Phase 4 | finance lead · external CA |
| Budget granularity | Phase 1 | department × category × quarter (recommended, matches the seeded rule) · add cost centres |
