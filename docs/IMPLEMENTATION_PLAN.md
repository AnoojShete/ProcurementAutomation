# Implementation plan

My checklist. Tick items as they finish; details and evidence live in
`TODO.md` (IDs in brackets), research reasoning in
`RESEARCH_GAP_ANALYSIS.md` and `RESEARCH_PAPER_PLAN.md`.
Created Oct 16, 2026 · deadlines: development ends **end of October**,
testing **November**, submission **December**.

Labels: **[E]** essential for the system · **[R]** needed for the research
claim · **[X]** evaluates the claim · **[O]** optional, can be dropped.

## Already done (evidence in TODO.md)

- [x] Basic requirements BR-1…BR-7 (email intake, scan preprocessing,
      "other" + PO-backed classes, vendor onboarding, reorder suggestions,
      risk before signing, delivery/compliance risk signals)
- [x] R0 items FR-01, FR-02, FR-03, FR-06, FR-07, FR-30
- [x] Fixes: 400 on out-of-stock requests, no ₹0 split requests, vendor
      page reload
- [x] UI pass: dark mode, names instead of emails, clickable figures, one
      System page, unread-only notification bell [UX-1] (Oct 18)
- [x] MinIO image replaced so a fresh clone starts again [REPRO-1] (Oct 18)

## Phase 0 — Unblock (today)

- [x] Terminate the six stale approval workflows and cancel request
      `90261afb` [OPS-1] **[E]** — cleared by the Oct 18 demo-data reset
- [ ] Decide the drift-check minimum sample (e.g. 30 vendors) [DRIFT-1] **[E]**

**Done when:** no `approval-…` workflow is left Running for a deleted or
dead request.

## Phase 1 — Finish what the presentation needs (by Oct 31)

- [ ] A teammate runs `docs/index.html#demo-5min` (or the full `docs/index.html#demo-script`) by hand after `./scripts/reset-demo.sh` (scripts done: full one 18/18 by `tests/e2e/demo_scenarios.py`, 5-minute cut 6/6 by `tests/e2e/demo_5min.py`, backup recording in `docs/demo/`) [FR-05] **[E]**
- [x] Draft the presentation from the templates [FR-12] **[E]** — paste into the Word templates left
- [x] Add retry + DLQ to the notification consumer; tell Anooj [FR-31] **[E]**
- [x] Make model routing/fallback visible in a demo [FR-08] **[E]**
- [x] Add validation + tests for every business rule [FR-09] **[E]**
- [x] Audit which events send notifications [FR-10] **[O]**
- [x] Clause extraction with Legal-BERT [FR-13] **[O]**
- [x] Sanctions screening override [FR-14] **[O]**
- [x] Evaluate and tune the licence anomaly model [FR-32] **[O]**

**Done when:** the demo script runs end to end on a fresh seed and the
presentation draft is reviewed.

## Phase 2 — Research data and harness (critical path)

- [x] Extend `synthetic_invoice_lib.py` into a procurement world: vendor
      master with look-alikes, POs, ledger [RS-02] **[R]**
- [x] Add controlled injections: scan degradation + business errors
      (amount ≠ PO, unknown vendor, duplicate, changed bank details)
      [RS-02] **[R]**
- [x] Generate a 300-document pilot, then ~3,000 documents / ~100 vendors
      [RS-02] **[R]**
- [x] Write the evidence export from `pipeline_checkpoints` [RS-01] **[R]**
- [x] Build the batch harness that seeds the world and runs the real
      pipeline [RS-03] **[R]** — runs the production code in-process, not through the stack (Oct 19)
- [ ] Check DocILE's terms; pick DocILE or FATURA [RS-08] **[R]**

**Done when:** one command produces a labelled table (document, field,
features, correct?) for the pilot.

## Phase 3 — Gate and baselines

- [x] Score the current heuristic gate on the pilot (B0) [RS-05] **[X]**
- [x] Build the document-only calibrated gate (B1) [RS-05] **[X]**
- [x] Build the rules-only enterprise matcher (B2) [RS-05] **[X]**
- [x] Build the fused calibrated gate with Learn-then-Test (P) [RS-04] **[R]**

**Done when:** all four systems give coverage-at-α on the same splits.

## Phase 4 — Experiments and analysis

- [x] Run RQ1 + RQ2 on 20 vendor-grouped splits with bootstrap CIs [RS-06] **[X]**
- [x] Run ablations per evidence group [RS-07] **[X]**
- [x] Run the stale-master-data robustness sweep (RQ3) [RS-07] **[X]**
- [ ] Run the external-validity check on public invoices [RS-08] **[X]**
- [x] Analyse accepted-but-wrong documents by injection type [RS-09] **[X]**
- [ ] Run the drift / feedback study (RQ4) [RS-10] **[O]**

**Done when:** `docs/results/selective.{json,md}` holds every number the
paper will use, negative results included.

## Phase 5 — Testing, integration, delivery (November)

- [ ] Put the gate behind rule `document.review_policy`, heuristic
      default; show evidence on the review page [RS-11] **[E]**
- [ ] Run the tests in CI [FR-25] **[E]**
- [x] Fix the two failing root tests (one is Anooj's) [TEST-1] **[E]**
- [ ] Do the fresh-clone rehearsal in the UTM Ubuntu VM [FR-26] **[E]** — macOS build from a clean copy passes; the VM run is left
- [ ] Close the security P1s [FR-27] **[E]** — Oct 19: upgrades, logout revocation, 15-min tokens done; MLflow, Paddle 3, QA-19 left
- [ ] Final documentation pass [FR-28] **[E]**

**Done when:** a fresh Ubuntu clone passes every suite and the docs match
the system.

## Phase 6 — Paper

- [ ] Make risk–coverage figures and ablation tables [RS-12] **[R]**
- [ ] Re-run the literature search (2026 work moves fast) [RS-12] **[R]**
- [ ] Draft sections 1–10 from `RESEARCH_PAPER_PLAN.md` [RS-12] **[R]**
- [ ] Choose the venue after RQ1 results [RS-12] **[R]**

**Done when:** every number in the draft traces to the results file.

---

## Critical path

RS-02 generator → RS-01/RS-03 harness → RS-05 baselines + RS-04 gate →
RS-06 RQ1/RQ2 → RS-07 ablations/robustness → RS-12 paper. Phase 1 runs
in parallel because of the end-of-October deadline.

## Next three actions

1. A teammate rehearses the 5-minute demo on reset data [FR-05].
2. Finish the red-team list for the risk write-up [FR-04].
3. Start the procurement-world generator with a 300-document pilot [RS-02].

## Most important unresolved dependency

Labelled documents **with enterprise context** (vendor master, POs,
ledger). No public dataset has them, so the generator (RS-02) carries the
research; its realism is the main threat to validity.

## Minimum viable research contribution

RQ1 on the procurement-world corpus: B0, B1, B2 and the fused gate P,
coverage at α = 2 % with confidence intervals, risk control checked, one
ablation table. Everything else strengthens it.

## Optional — drop first if time is short

- RQ4 drift / feedback study [RS-10]
- External-validity run [RS-08] (then state it as a limitation)
- PySpark / Kubernetes [FR-15/16]
