# TODO

Open work, grouped by priority, each with why it matters. What changed
and when is in `git log`; finished roadmap items keep a dated evidence
line here. Started Sep 27, 2026; roadmap added Oct 15; updated every phase.

- **P0**: broken now, or a security exposure. Fix before the next demo /
  any shared deployment.
- **P1**: real gap in a feature or in safety; next in line.
- **P2**: hardening, cleanup, nice to have.

## P0

- [ ] **Rotate the GSTINCheck API key** (`67d40c75…`): committed as a
  default before Sep 25 and still in git history. Put the new one in
  `.env` only. *Why: leaked credential.*
- [ ] **Any non-local deployment**: set `APP_ENV=production` and real
  `JWT_SECRET`, `ESIGN_WEBHOOK_SECRET`, `RULES_ENGINE_INTERNAL_SECRET`,
  `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD`, `KAFKA_PASSWORD_*`, Grafana
  admin password; `EMAIL_MODE=smtp`; `AUTH_COOKIE_SECURE=true` behind
  HTTPS; build the frontend with `VITE_SHOW_DEMO_ACCOUNTS=false`.
  Services refuse to start with the published defaults outside
  development. *Why: the demo secrets are public.*

## Fractal roadmap — Oct 15, 2026

Added **Oct 15, 2026** from the Fractal Drive folder (*Fractal Analytics
Project 2026-2027*): mentor feedback (27 Jun, 4 Jul, 18 Jul, 29 Aug),
Team A minutes (27 Jun, 26 Sep), the Project Tech Stack, our submitted
Architecture, Overall Project and Individual Agent docs, the two
documentation templates, and the other teams' docs (for features worth
matching). Each "Now" line was checked against the code on Oct 15.
Items here that overlap an older P1/P2 entry say so; that entry is closed
together with the roadmap item.

Dates from the mentors: development ends **end of October**, final
presentations by end of October (10 Oct minutes), testing and
stabilisation in **November**, submission in **December**.

- **R0** (by Oct 24): what the 29 Aug feedback asked Team A to show, and
  the "overall" items that apply to us.
- **R1** (by Oct 31): things our submitted docs or the tech stack say we
  have, but the code doesn't.
- **R2** (only once R0 and R1 are done): features the other teams or
  commercial tools have, which we can add cheaply.
- **R3** (November): testing, evidence and documentation for submission.

Team boundary still applies: email automation and the chatbot are
Anooj's. Roadmap items that touch them go only as far as publishing an
event or writing a spec for him.

### Priority 1 — basic requirements still missing (checked Oct 16)

The basic scope (document & vendor intelligence, approval & inventory,
contract & risk; platform/infrastructure excluded) was checked against the
code on Oct 16. Everything else in it is built; these are the gaps, done
before any other roadmap item.

- [ ] **BR-1 Email ingestion of documents.** *Now:* upload, API and the
  drop folder feed the pipeline; nothing reads documents from a mailbox.
  *Do:* poll a mailbox (IMAP; Mailpit in development) for attachments and
  send them through the same scan → store → pipeline path as an upload,
  recording the sender. Inbound only (outbound email stays with
  notifications). *Done when:* an emailed PDF becomes a classified
  document with its sender recorded, and a non-document attachment is
  rejected with a reason.
- [ ] **BR-2 Image preprocessing before OCR** (= FR-11's OpenCV part).
  *Now:* OpenCV installed, never used. *Do:* resize, denoise, deskew /
  rotation correction for scans and photos. *Done when:* a rotated or noisy
  scan reads correctly (before/after numbers in `docs/results/`).
- [ ] **BR-3 Classification: PO / Non-PO / Others.** *Now:* invoice, PO,
  quote only; an unrecognised document is forced to "invoice". *Do:* an
  `other` class for documents that are none of these (sent to review), and
  invoices marked PO-backed or non-PO (does it cite a purchase order?).
  *Done when:* tests for each class and the PO / non-PO flag.
- [ ] **BR-4 Vendor onboarding and profile validation.** *Now:* vendors are
  only created from documents. *Do:* an onboarding form (name, contacts,
  GSTIN, bank details, category) that validates the profile (GSTIN format /
  checksum, IFSC, duplicates / look-alikes) and routes bank details through
  the existing two-person verification. *Done when:* a vendor can be
  onboarded from the UI and invalid profiles are rejected with reasons.
- [ ] **BR-5 Reorder suggestions.** *Now:* a 10 %-of-stock display
  heuristic. *Do:* stored reorder point and reorder quantity per item
  (rule-backed defaults), suggestions from stock + reservations +
  backorders, shown on the inventory page. *Done when:* a backordered item
  produces a suggestion with the quantity explained.
- [ ] **BR-6 Vendor risk shown before signing.** *Now:* the contract page
  doesn't show the vendor's risk. *Do:* the risk band, reasons and hard
  overrides on the contract page and in the signing dialog; High needs an
  explicit acknowledgement before signing. *Done when:* signing a contract
  for a High-risk vendor requires that acknowledgement (test).
- [ ] **BR-7 Risk from delivery delays and compliance history** (= FR-30).

### R0 — mentor feedback, 29 Aug

- [x] **FR-01 Auto-send for signature after every approval** (29 Aug,
  Team A #1; overall #4). *Now:* `auto_send_for_signature`
  (`contract_service.py`) returns `not_from_drop_folder` for every
  contract whose request didn't come from `./inbox`, so a request made in
  the app needs someone to click "Send for signature". *Do:* a business
  rule `contract.auto_send_scope` (`drop_folder` | `all`, default `all`)
  read by that function; keep "send once" and the audit entries; the
  request page shows "sent automatically" in the Signature step. *Done
  when:* an in-app request, once approved, reaches `awaiting_signature`
  with no clicks (new e2e check in `invoice_lifecycle.py` or
  `test_flow.py`); setting the rule to `drop_folder` restores today's
  behaviour (unit test).
  *Evidence (Oct 16):* rule `contract.auto_send_scope` (auth-service
  migration 0004, default `all`, invalid values rejected);
  `test_docusign.py::TestAutoSend` 9 passed (in-app sent, `drop_folder`
  skips in-app but sends drop-folder, built-in signer); e2e
  `invoice_lifecycle.py` 69/0 with the new "sent for signature with no
  clicks" + "sent automatically" checks, 67/2 with the rule set to
  `drop_folder` (those two fail); Signature step shows "Sent for signature
  automatically after approval". Status name in code is
  `pending_signature`.
- [x] **FR-02 Renewal reminders count from the notice deadline** (29 Aug,
  Team A #2; closes the P1 Contracts item). *Now:* `renewal_workflow.py`
  fires at `contract_end_date − 60/30/15` even though its docstring says
  notice deadline; a contract created inside a window fires every missed
  milestone at once. *Do:* deadline = `end_date − notice_period_days` (end
  date if unknown); skip milestones already past, except the nearest one;
  put the next reminder date on the contract page. *Done when:* unit
  tests on the schedule function (notice 30 d, notice unknown, created
  10 days before the deadline → one reminder), plus one live run with a
  short-dated contract showing `contract.renewal.due` in the Control
  Panel.
  *Evidence (Oct 16):* `app/services/renewal_schedule.py` (shared by the
  workflow and the API); `test_renewal_schedule.py` 5 passed (notice 30 d,
  notice unknown, created 10 d before the deadline → one reminder,
  between milestones, messy rule values; 2 fail with the old maths);
  live: contract 26aa6be0 set to end today+40 / notice 30 → workflow
  history shows the `renewal-from-notice-deadline` patch marker, one
  `contract.renewal.due` (alert 15) and completion; the event is on the
  Control Panel's Kafka log; contract page shows Notice Deadline and Next
  Renewal Reminder. All 47 open pre-change renewal workflows replay on
  the new code (`__stack_trace` query, 47/47). contract-risk suite 92
  passed. 10 new test contracts (in-app requests, approved, contracts
  auto-generated): all 10 workflows carry the patch marker and their
  first timer fires 2027-07-17 (deadline 2027-09-15 − 60), matching the
  contract page; the old maths would give 2027-08-16. The 47 workflows
  started before the change keep their old end-date schedule by
  decision (not restarted).
- [x] **FR-03 Reminders for pending actions** (29 Aug overall #5;
  Proposal §5.3 "reminders at 50 % and 80 % of SLA"). *Now:* only
  renewal reminders and SLA escalation exist; nothing reminds an approver
  before the SLA breaches, a signer whose contract waits, or a reviewer
  with a stale review-queue item. *Do:* one `reminder.due` event (topic
  added to `kafka-topics.yaml`, `acls.conf`, `events.md`) published via
  the outbox for: approval at 50 %/80 % of SLA (Temporal timer in
  `approval_workflow.py`, cancelled by a decision); contract in
  `awaiting_signature` for N days, and pending bank-detail verification; review-queue document older than N hours. All N
  are business rules. notification-agent templates for `reminder.due`. *Done when:* a test per source shows the event is published
  and not published after the action is taken; the event appears on the
  Control Panel.
  *Decision (Oct 16):* approval reminders as versioned timers in the approval workflow (`workflow.patched`), checking every open workflow still replays.
  *Evidence (Oct 16):* topic `reminder.due` (kafka-topics.yaml, acls.conf,
  events.md; builder + once-per-threshold marker in `shared/reminders.py`).
  Approvals: timers at `approval.reminder_sla_percents` of the SLA behind
  `workflow.patched("approval-sla-reminders")` — `test_approval_reminders.py`
  3 passed in Temporal's time-skipping server (no decision → 50 %, 80 %;
  decision at 60 % → 50 % only; 2 fail without the timers); live with a
  1 h SLA at 1 %/2 %: untouched request got both, request approved at
  ~50 s got only the first. Signature (`contract.signature_reminder_days`),
  bank-detail (`vendor.bank_verification_reminder_hours`) and review-queue
  (`document.review_reminder_hours`) sweeps: `test_reminder_sweep.py` in
  both services + `tests/test_reminders.py`; live: 143 stale reviews + 2
  waiting contracts reminded once, still 145 after six more sweeps. Shown
  on the Control Panel ("Reminder: approval sla on purchase_request …").
  Suites: approval 118, contract-risk 105, document-vendor 217, auth 60.
  Of the 5 open approval workflows, 4 replay on the new code; the 5th
  (`approval-90261afb…`, started Sep 25) has failed every task with
  TMPRL1100 since **Sep 27** — broken before this change (see P1).
  *For Anooj (spec):* notification-agent should consume `reminder.due`
  (add the read ACL with it) and send a template per `kind` to
  `recipient_role`, linking to `link`.
- [ ] **FR-04 Risk analysis on synthetic data, documented and
  evaluated** (29 Aug, Team A #3). *Now:* RandomForest on
  `ml/data/synthetic-vendors/vendor_risk_training_data.csv`, accuracy/AUC
  logged to MLflow; no dataset card, no per-band results. Missing
  features are filled with `DEFAULT_FEATURES` (0.5), but the Agent doc
  says they are "excluded, never imputed". The hard overrides the doc
  describes (sanctions match / cancelled GSTIN / failed IFSC → High) are
  not in `risk_service.py`. *Do:* `ml/evaluate_risk_model.py` writes
  `docs/results/risk-model.json` + `.md` (dataset size and class balance,
  how labels are generated, accuracy, ROC-AUC, confusion matrix per band,
  feature importances); the 10–15-profile red-team set from the Agent doc
  as a fixture with expected bands; hard overrides before the model,
  shown as a factor; `signals_used / signals_total` in the risk response
  and on the vendor page instead of silent defaults. *Done when:* the
  evaluation script runs in the image and its output is committed; tests
  for override-beats-model and missing-data-not-penalised pass;
  `docs/risk-model.md` explains dataset, criteria and results in
  presentation-ready words.
  *Partial (Oct 16):* `ml/evaluate_risk_model.py` runs in the image
  (model now trained at image build) → `docs/results/risk-model.{json,md}`:
  2,000 synthetic vendors (20 % stressed segment added — with the old 400
  typical rows "everything bad" scored Medium), ROC-AUC 0.715 vs ceiling
  0.739 (old 0.707 vs 0.702), per-band incident rate 6.5 / 20 / 40 %,
  red-team 12/12 (old data 7/12). Missing values left out (model trained
  with 20 % blanked); `signals_used/total`, hard-check states and the GSTIN
  override on the risk API and vendor page (migration 0006).
  `test_risk_model.py` 14 passed (11 new + the 3 earlier ones; 5 of the
  new fail with the old defaults/no overrides); contract-risk 103 passed; `invoice_lifecycle.py` 71/0 (risk
  check now: coverage reported, factors only from signals on file).
  `docs/risk-model.md` written; results committed (03e7f59). *Missing:* the
  12 red-team profiles are ours (the Agent doc's list isn't in the repo —
  compare them); sanctions and IFSC overrides report "not checked" (no
  data: FR-14, and IFSC results aren't stored); live vendors have no risk
  signals, so every live score is 0/6 and the drift check flags PSI 7.2.
- [ ] **FR-05 Demo script** (29 Aug, Team A #4: "explain each step, the
  workflow and the expected outcome"). *Do:* `docs/demo-script.md`, one
  table per scenario (in-app request → approval → auto-sent contract →
  signature → ordered → received; drop-folder quote; invoice match and
  mismatch; risky vendor; bank-detail change), each row = action, which
  agent and event, what you should see. A `scripts/seed-demo-data.sh`
  option for any data the scenarios need. *Done when:* someone who didn't
  build it runs every scenario from a fresh `./run.sh` using only the
  script.
- [x] **FR-06 Kafka monitoring that survives a restart** (29 Aug overall
  #6; Team B #2). *Now:* Control Panel shows live events, but
  `event_monitor.py` keeps the last 500 in memory (gone on restart, no
  search); consumer lag is on System Health; DLQ rows aren't shown.
  *Do:* persist the monitor's events to an `event_log` table
  (document-vendor-agent migration, with a retention rule); filter by
  topic / correlation id / time; a "Failed events" panel listing
  `event_dlq` with the error. *Done when:* events are still there after
  `docker compose restart document-vendor-agent`; a forced consumer
  failure shows in the failed-events panel.
  *Evidence (Oct 16):* `event_log` table (document-vendor migration 0008;
  summaries only, unique per topic/partition/offset), retention rule
  `monitor.event_log_retention_days` (auth-service migration 0006, hourly
  prune). The monitor resumes after the last stored offset. Live: 472 rows
  → stop the service → a risk event published meanwhile → 473 rows after
  restart, 0 partitions with offset gaps. Filters on the API and page
  (topic, time window, text, correlation id — one approval's correlation
  id returned its approval.decided, contract.generated and
  notification.send). "Failed events" panel (`/failed-events`, summarised,
  no raw payload): the showcase out-of-order `invoice.matched` appeared
  with its PermanentEventError. `test_event_log.py` 6 passed (resume test
  fails with the old in-memory restart). document-vendor 223 passed.
  Control Panel's DocuSign labels now say built-in E-signature.
- [x] **FR-07 Application logs you can search** (29 Aug overall #7).
  *Now:* every service writes JSON logs with `correlation_id`, but only
  `docker logs` can read them. *Do:* Loki + Promtail in compose (pinned
  versions, 127.0.0.1 only), Grafana datasource, a "Logs" dashboard with
  a correlation-id variable; check every service writes one access-log
  line per request. *Done when:* one correlation id from an upload shows
  that request's log lines from all services in one Grafana query
  (screenshot into `docs/results/`).
  *Decision (Oct 16):* add Loki + Promtail (pinned, 127.0.0.1 only).
  *Evidence (Oct 16):* Loki + Promtail 2.9.8 (127.0.0.1:3100; Promtail
  reads container logs via the Docker socket, skips the log stack itself),
  Grafana "Logs" dashboard (correlation-id box, service filter). Before
  this, HTTP requests had no correlation id and the workers logged plain
  text: nginx now sends `X-Correlation-ID` ($request_id),
  `shared/http/correlation.py` sets it per request, echoes it and writes
  one JSON access line (all five services checked live), the
  document-vendor → ledger call forwards it, and the three workers log
  JSON. One upload's id (`71f1e695…`) shows lines from document-vendor,
  its worker, approval-inventory, contract-risk and notification-agent in
  one Grafana query: `docs/results/logs-correlation.png`.
  `tests/test_correlation.py` 5 passed. Note: on this Mac something else
  answers `localhost:3000`; Grafana is at `http://127.0.0.1:3000`.
- [ ] **FR-08 Model routing and fallback, demonstrable** (29 Aug overall
  #2, #3; Team B #1, #5). *Now:* two routers write `model_routing_log`:
  extraction (Docling/Paddle → LayoutLMv3 cross-check) and clauses (regex →
  keyword, both rules). The chatbot uses one Ollama model with no
  fallback. *Do:* a way to show the fallback on demand (admin toggle or
  business rule "force primary failure", development only); the routing
  log on System Health shows reason and duration; `docs/model-routing.md`
  lists every router, its primary and fallback, and when the fallback
  fires. A real ML primary for clauses is FR-11. *Done when:* a test per
  router forces the primary to fail and asserts the fallback row; the
  demo script has a "fallback" scenario.
- [ ] **FR-09 Business rules validated** (29 Aug overall #1; Team B #7).
  *Now:* `shared/rules_engine` and the Business Rules page exist; there's
  no list of what each rule changes or a test for each rule. *Do:*
  `docs/business-rules.md` (rule key, default, where it's enforced, its
  test); a test per rule that changes it and checks the behaviour
  changes. *Done when:* every key in the rules table appears in the doc
  and has a test (a root test fails if a key is missing).
- [ ] **FR-10 Notification coverage audit** (29 Aug overall #8). *Do:* a
  table in `docs/notifications.md`: each lifecycle stage → event → who
  should hear → template → sent today (y/n). Hand the gaps to Anooj
  (don't build email automation). Also check whether the stale TODO lines
  "Mailpit only" and "no item links" still hold: `email_service.py` has
  used `shared/mailer.py` since Oct 11, and portal links exist in the
  consumer. *Done when:* the table is in the repo, and the P1 Platform
  lines are corrected or closed.
- [ ] **FR-11 Document layout analysis accuracy** (29 Aug overall #9; Team
  B #6; Team C #1, #4). *Now:* Oct 15 confidence work (sample scan 0.50
  → 0.93). OpenCV is in `requirements.txt` but no code imports `cv2`.
  There's no accuracy measurement over a document set. TODO still says
  image OCR crashes on Apple Silicon, while the Oct 14 commit says it's
  fixed (`LD_PRELOAD`). *Do:* `scripts/eval_extraction.py` over
  `data/synthetic-invoices` (+ a few rotated/noisy scans) → field-level
  accuracy per field into `docs/results/extraction.json`; OpenCV
  pre-processing for image pages (deskew, denoise, adaptive threshold)
  behind a rule, kept only if accuracy goes up; a JSON Schema for the
  extraction output in `shared/schemas/`. Re-check the aarch64 OCR line
  and close it. *Done when:* before/after numbers are in the results
  file; the schema is validated in a test.
- [ ] **FR-12 Presentation draft and template-shaped documentation** (29
  Aug overall #10, #11; 18 Jul #2, #3). *Now:* the submitted Overall and
  Agent docs follow the templates, but every "Results and Evaluation"
  section says "to be completed". *Do:* a `docs/results/` folder
  holding what those sections need: one sample input and its JSON output
  per agent, screenshots taken by `tests/e2e/ui_flows.py` (Playwright),
  and the metrics from FR-04/FR-08/FR-11 and the e2e pass counts.
  Include `run.sh`/`install.sh` in the appendix (18 Jul #3). Draft deck
  outline (problem, solution, architecture, implementation, results) in
  `docs/presentation-outline.md`. *Done when:* each agent has a sample,
  a screenshot and a metric to paste into the Word doc.

#### Added to R0 on Oct 16 (every yellow/red box on the flow chart)

- [ ] **FR-13 Clause extraction with a model, rules as fallback**
  (Agent doc §2.2 says Legal-BERT on CUAD; code is regex). Moved from R1 on Oct 16. *Do:* either
  add `alex-apostolo/legal-bert-base-cuad` QA as primary (local cache
  like LayoutLMv3, `download-models.sh`), regex as fallback via
  `clause_router.py`, evaluated on a held-out CUAD slice → `docs/results/
  clauses.json`; **or** correct the docs to say rule-based. Ask before
  choosing (image size and CPU time).
  *Decision (Oct 16):* add Legal-BERT (CUAD) as primary, rules as fallback.
- [ ] **FR-14 Sanctions screening and the strategic-tier checks**
  (Agent doc §2.3; Overall doc §6). Moved from R1 on Oct 16. Also store IFSC results (`validate_ifsc` exists but nothing calls it or keeps its result) so the IFSC override in FR-04 can fire. *Now:* `vendor_tier_service.py`
  lists `opencorporates`, `sanctions_screening`, `risk_model` for
  strategic vendors, but none runs. *Do:* OpenSanctions bulk file
  (downloaded by a script, refreshed by a daily job, no API key) + rapidfuzz
  match → `POST /vendors/{id}/screen-sanctions` and `/clear-sanctions-flag`
  (justification required, audit-logged); a match is an FR-04 hard
  override. OpenCorporates only behind Live Verification Mode, or drop it
  from the list. *Done when:* precision tests (a near-match is flagged, an
  unrelated company isn't); the strategic tier's checklist shows real
  results. Closes part of the P2 "external data" item.
- [ ] **FR-29 Train the document classifier** (flow chart: "ML classifier
  not trained"). *Now:* `classification.py` is a keyword classifier; an ML
  classifier is wired in but no trained model ships. *Do:* train it on
  `data/synthetic-classification` (+ the invoices/quotes/POs we generate),
  evaluate against the keyword classifier on a held-out set → `docs/results/
  classifier.json`; keep keywords as the fallback (FR-08 router). *Done
  when:* accuracy per class for both is in the results file and the ML
  classifier is used only if it's better.
- [ ] **FR-30 Risk signals from platform data** (flow chart: "no vendor
  has risk signals recorded"; follows FR-04). *Now:* `vendor_risk_features`
  is empty, so every live score is "0 of 6 signals" and the drift check
  flags PSI 7.2. *Do:* fill what the platform knows — tenure from the
  vendor's first document/request, on-time delivery from ordered →
  received dates (Oct 15 lifecycle), plus a finance-only form for
  certification / breaches / geography, audit-logged; re-score on change.
  *Done when:* a vendor with platform history scores on ≥ 3 signals, the
  form updates the score, and the drift check is re-baselined or explained.
- [ ] **FR-31 Notification consumer retry + dead-letter** (flow chart:
  "No retry / DLQ"; P1 Platform line). *Now:* notification-agent's Kafka
  consumer isn't wrapped with `shared/eventing.deliver`, and on Oct 14 it
  silently stopped for three days when its login failed. *Do:* wrap it,
  and make `/health` report unhealthy when the consumer has stopped.
  notification-agent is Anooj's service: spec + his OK first.
  *Decision (Oct 16):* allowed to change notification-agent; Anooj to be told.
- [ ] **FR-32 Licence-usage anomaly model, evaluated and tuned** (flow
  chart: "Needs tuning"). *Do:* the same treatment as FR-04 for the
  IsolationForest: precision/recall on the synthetic SSO logs' injected
  anomalies → `docs/results/licence-anomaly.json`, threshold chosen from
  that curve (business rule), and the reasons shown on the licence page.
  *Done when:* the results file exists and the threshold is justified in it.
- [ ] **FR-33 P0 credentials** (flow chart: P0 red box): rotate the
  GSTINCheck key and set real secrets before any shared deploy. Only a
  person can do this (no key rotation by the assistant).

### R1 — what the docs and tech stack say we have

- [ ] **FR-15 PySpark in the pipeline** (Project Tech Stack:
  "Dataprocessing: PySpark"; Architecture §5.1). *Now:* no PySpark
  anywhere. *Do:* one batch job (`services/analytics-job/`, its own
  image, run by compose profile or a schedule) that reads approved
  requests, receipts and invoice matches and writes per-vendor KPIs
  (on-time delivery rate, invoice variance, order count) to a table;
  the risk model reads `on_time_delivery_rate` from it instead of
  synthetic values when present (tagged "platform data"). *Done when:*
  the job runs on the seeded data and the vendor risk page shows the
  feature's source. Ask before adding the service.
- [ ] **FR-16 Kubernetes manifests / Helm chart** (Tech Stack:
  Kubernetes; 4 Jul feedback; Architecture §5.2). *Now:* `infra/k8s/`
  is empty. *Do:* a Helm chart (or plain manifests) for the services,
  workers, gateway and frontend, using the existing images and env;
  infra (Postgres, Redpanda, MinIO, Temporal) via their charts or
  single-replica manifests; tested on local kind/minikube only. Don't
  deploy anywhere shared. Ask the mentor whether a cluster is coming.
  *Done when:* `helm install` on kind passes every `/health` through the
  gateway; the steps are in `readmeforme.md`.
- [ ] **FR-17 Database and object-storage pages** (29 Aug Team C #5,
  "applicable wherever relevant"). *Now:* Control Panel lists the latest
  MinIO files only. *Do:* admin-only "Data" page: read-only browse of
  an allowlist of tables (bank numbers and tokens masked, paginated)
  and MinIO browse/search/download of documents and signed contracts,
  through existing service APIs (no direct DB access from the gateway).
  *Done when:* an admin can find a document's row and its file without
  a terminal; a requester gets 403 (test).
- [ ] **FR-18 Request trace view** (Overall doc §7: "full request tracing
  across all four services"). *Do:* on the request and document pages,
  a "Trace" tab listing that item's events (FR-06 table), audit rows and
  routing-log rows by `correlation_id`, in time order. *Done when:* one
  in-app request shows every hop from upload to signature.
- [ ] **FR-19 Re-verify the 26 Sep minutes items**. Item-specific
  approval links (be55179), multi-document upload (Sep 26), signed-copy
  download, contract generation and the order monitor are built. Check
  each live and record the evidence in `docs/results/`. Open item: the
  order monitor's summary is published as `order.summary.generated`, but
  sending it to people "at configurable intervals" is notification work. The chatbot is.

### R2 — competitive features (only once R0 and R1 are done)

- [ ] **FR-20 Delivery tracking and late-delivery alerts** (Team B's
  Fulfillment agent; builds on Oct 15 `ordered` → `received`). Expected
  delivery date on an ordered request, an overdue `reminder.due`, and
  on-time rate feeding FR-15.
- [ ] **FR-21 Vendor scorecard + guided buying** (Architecture §3.3, SAP
  Ariba/Coupa; Team B Analytics agent). Vendor page scorecard (risk band,
  on-time rate, invoice variance, spend); the request wizard suggests an
  existing approved vendor or contracted price for the same item.
- [ ] **FR-22 Scheduled procurement report** (Team C's planned Report
  Generation agent). Weekly PDF: spend by department, pending approvals,
  contracts nearing their notice deadline, high-risk vendors. Stored in
  MinIO and downloadable; sending it by email goes to Anooj.
- [ ] **FR-23 Duplicate / overlapping SaaS detection** (Overall doc
  §11; Zylo/Torii). Group licences by category taxonomy, flag overlaps,
  estimate consolidation savings on the Spend page.
- [ ] **FR-24 Read-only MCP server** (Overall doc §11). Expose the
  existing read endpoints (request status, contract renewals, vendor
  risk) as MCP tools with a service token; coordinate with Anooj so the
  chatbot can use the same tools.

### R3 — November: testing, evidence, submission

- [ ] **FR-25 CI runs the tests** (= P1 Platform "CI only builds
  images"): service suites, root tests, `npm run typecheck`, ruff (= P2
  lint).
- [ ] **FR-26 Fresh-clone rehearsal on Ubuntu** (4 Jul / 18 Jul
  feedback; mentor's Ubuntu VM requirement). Follow only `readmeforme.md` on a
  clean Ubuntu VM, run every e2e suite, and record times and results in
  `docs/results/fresh-clone.md`.
- [ ] **FR-27 Security P1s before any shared demo**: dependency upgrades,
  contract access, shorter tokens (existing P1 entries), the GSTIN key
  rotation (P0).
- [ ] **FR-28 Final documentation pass**: fill both templates from
  `docs/results/`, update the architecture diagram (draw.io) and
  `docs/project-flow.html`, and remove claims that are still not built.

## P1

- [ ] Approval workflow `approval-90261afb-5b86-4463-bcf3-3fc6d422fb5d`
  (started Sep 25) has failed every workflow task with a
  non-determinism error (TMPRL1100) since Sep 27 — an earlier change to
  `approval_workflow.py` without versioning. It can't progress or be
  queried. Terminate or reset it (needs a decision). *Why: a request stuck
  in pending_approval forever.*

**Security audit follow-ups**
- [ ] Upgrade FastAPI/Starlette (starlette 0.37.2 advisories), Pillow
  10.4.0, pdfminer.six 20231228 (via pdfplumber) — all parse untrusted
  uploads; needs a coordinated upgrade and a retest of Docling/Paddle.
  *Why: known CVEs on the upload path.*
- [ ] MLflow 2.14.3 has many advisories; bound to localhost for now.
  *Why: must not be exposed as is.*
- [ ] Contracts and contract PDFs are readable by any signed-in user;
  restrict to staff + the request's requester. *Why: commercial data
  leak to requesters.*
- [ ] Access tokens stay valid for up to `JWT_EXPIRY_MINUTES` (60) after a
  user is disabled or demoted — other services verify tokens without a
  DB lookup. Shorten to ~15 min (the frontend refreshes silently) or add
  a revocation check. *Why: disabling an account isn't immediate.*

**Document pipeline**
- [ ] Scanned PDFs pay Docling's cold model load (~60 s) per document,
  since extraction runs in a killable child process. Keep a warm process
  pool. *Why: throughput.*
- [ ] Images OCR badly on Apple Silicon: PaddleOCR crashes in the aarch64
  worker image, so PNG/JPG uploads fail with "couldn't read any text".
  Reproduce: `docker compose exec document-vendor-agent-worker python -c
  "from paddleocr import PaddleOCR"`. *Why: image uploads don't work on
  the team's Macs.*
- [ ] The ML document classifier (`ml/train_classifier.py` →
  `classifier.joblib`) is wired in but no model is trained or shipped, so
  classification is always keyword-based. Train it in the image build or
  remove the dead path. *Why: docs and pitch mention ML classification.*

**Approvals / inventory**
- [ ] Anomaly model ranking looks wrong on the seeded data (a license at
  76 % utilisation scores anomalous). Tune before quoting savings.
- [ ] Two different SSO log generators: the committed dataset comes from
  `services/approval-inventory-agent/scripts/generate_sso_logs.py`
  (5 licenses); the repo-root `scripts/generate_sso_logs.py` makes a
  different 8-license set and would break the seeded licenses if run.
  Keep one. *Why: regenerating the data silently breaks the demo.*
- [ ] Seed or stub a demo reclaim request so the license page's approval
  panel can be shown without creating one first; and add
  `tests/e2e/ui_flows.py` (Playwright) to CI once tests run there.
- [ ] Signing up doesn't create an approval-authority assignment: a user
  promoted to approver can't approve until an admin adds one on the
  Controls page. Surface this on the Users page. *Why: confusing for
  real users.*

**Contracts**
- [x] Renewal reminders fire 60/30/15 days before `contract_end_date`,
  not before the notice deadline (`end_date − notice_period_days`).
  *Why: reminders can arrive after the notice window closed.* Closed by
  FR-02 (Oct 16).
- [ ] The Documenso client is only tested against mocked HTTP; run it once
  against a real Documenso instance before calling it integrated.
  Without Documenso settings, signing is simulated.

**Platform**
- [ ] CI only builds images. Run `scripts/test-service.sh all`, the root
  tests and `npm run typecheck` in `.github/workflows/ci.yml` (e2e needs
  the full stack). *Why: this audit found three bugs a CI run of the
  fresh-clone e2e would have caught.*
- [ ] Wrap notification-agent's consumer with `shared/eventing.deliver`
  (retry + DLQ) like the other consumers. *Why: a failing event is
  dropped.*
- [ ] Move the remaining direct publishes to the outbox:
  `approval.requested`, `license.usage.updated`, `risk.score.updated`,
  `vendor.offboarded`, renewal alerts. *Why: an event can be lost on a
  crash between commit and publish.*
- [ ] `digest_service.flush_due_digests` retries a permanently failing
  digest forever.
- [ ] notification-agent: real SMTP (reuse `shared/mailer.py`) and real
  recipients (resolve approval levels through `approver_assignments`
  instead of placeholder role addresses), plus links to the item. Its
  mail still goes to Mailpit only.
- [ ] Assistant/chatbot must call `/orders/summary/latest` with a staff or
  service token (requesters get 403).

## P2

- [ ] approval-inventory-agent registers its own `HTTPException` handler
  with uppercase codes (`NOT_FOUND`) over the shared one (`not_found`).
- [ ] Lint: ~78 unused imports and ~15 redefinitions (e.g. duplicate
  imports in approval-inventory-agent `main.py` / `api/requests.py`).
  Add ruff to the repo and CI.
- [ ] `GET /inventory` runs the anomaly scorer per license per request
  (N+1); read the stored `anomaly_score`.
- [ ] Exact duplicate detection covers invoices only (POs/quotes
  uploaded twice aren't flagged).
- [ ] Batch upload scans files one at a time on one DB session.
- [ ] `mem_limit` / `cpus` on heavy containers (document worker: Docling
  + Paddle + LayoutLMv3, up to 4 in parallel).
- [ ] Health checks for `temporal-ui`, `mlflow`, `prometheus`, `grafana`,
  `nginx`; pin the `latest` images (redpanda, minio, prometheus, grafana,
  kafka-exporter, temporal-ui, mailpit) — a Temporal UI breakage already
  came from an unpinned image.
- [ ] Refresh tokens aren't rotated and there's no per-session revocation
  list (logout clears this browser's cookie; "sign out everywhere" ends
  all sessions). Fine for now; revisit for production.
- [ ] Kafka traffic is SASL_PLAINTEXT (no TLS); fine on one Docker host.
- [ ] TLS/HSTS at the gateway for anything beyond localhost.
- [ ] Sign-up returns 503 when HaveIBeenPwned is unreachable (offline
  demos can't create accounts). Decide: keep failing closed, or allow
  with a warning.
- [ ] The "you already have an account" email has no cooldown (the gateway
  per-IP limit is the only brake).
- [ ] Purge used/expired `auth_tokens` and old `auth_login_attempts` rows.
- [ ] `/documents/learning/stats` is readable by any signed-in user
  (vendor names and review counts only).
- [ ] Frontend: react-router 6 → 7 (open-redirect advisory), vite/esbuild
  major (dev server only); no ESLint configured.
- [ ] notification-agent: aiosmtplib 3.0.1 → 5.x.
- [ ] Classifier retraining from `extraction_feedback`; today learning
  covers field labels and per-vendor thresholds only.
- [ ] `seed_demo_users.py` prints the demo password to stdout; fine
  locally, not in a shared log pipeline.
- [ ] Remove the dead `vendorsApi.logOutcome` frontend call or wire it up.
- [ ] Repo cleanup: `install.sh` points to a `README-VM.md` that doesn't
  exist; `docker-compose.override.yml.example` is a stale 15-line stub;
  `infra/k8s/` is empty; `frontend/legacy-static/` is unused.
- [ ] External data for vendor risk (OpenCorporates, SEC EDGAR, SSL Labs),
  sanctions screening (OFAC / OpenSanctions), and validating clause
  extraction against CUAD — the "future scope" items; all current risk
  data is synthetic.
- [ ] Built-in e-sign seal is an unkeyed SHA-256 (tamper-evident only if
  the audit log is trusted); sign it with a server key (HMAC) if it has to
  stand on its own. The certificate also stores the drawn signature image
  in the audit row.
- [ ] Grafana: an approval SLA-breach panel needs a counter in
  approval-inventory-agent.

## The five platform capabilities (proposed and built Sep 26)

Outbox / DLQ / state machine / reconciler, approval authority, invoice
ledger, bank-detail quarantine + payment hold, learning from corrections —
all built and on the Controls page. What's partial is listed above:
outbox coverage, notification-agent DLQ, classifier retraining, and the
P0 ledger foreign key.
