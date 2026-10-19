# Research paper plan

Blueprint for a paper built on the ProcurementAutomation platform. The
evidence behind every claim here is in `RESEARCH_GAP_ANALYSIS.md`
(references numbered as there, e.g. [13] = Jin et al., 2026). Tasks are
in `TODO.md` (RS-xx) and `IMPLEMENTATION_PLAN.md`.

**Status (19 Oct 2026): first full run done (RS-01…RS-07, RS-09) on the
synthetic procurement world. Numbers: `docs/results/selective.{json,md}`;
summary in §9.10. Sections 9.1–9.9 are still the plan, written before
the run.**

---

## 9.1 Provisional titles

1. *Beyond the Page: Enterprise-Record Evidence for Risk-Controlled
   Straight-Through Processing of Procurement Documents*
2. *When Can an Invoice Skip Review? Calibrated, Document-Level Automation
   Gates Using Purchase-Order and Vendor-Master Evidence*
3. *Measuring the Value of Enterprise Context in Selective Automation of
   Procure-to-Pay Documents*

(Title 3 is the safe choice if the result is negative or mixed.)

## 9.2 Problem statement

Procure-to-pay platforms extract fields from invoices, purchase orders and
quotes and must decide which documents can go straight to approval and
payment. A wrong automatic decision is costly — paying the wrong vendor,
paying twice, paying more than was ordered — while sending everything to
review defeats automation. Recent work makes this decision with
calibrated confidence and a statistical error guarantee [13, 21, 22], but
scores each document in isolation, per field. Commercial tools check the
same documents against vendor masters and purchase orders [Rossum, SAP
Ariba docs], but with hand-set thresholds and no published error rates.
We do not know how much enterprise evidence adds to a calibrated,
risk-controlled gate, nor how to control error at the level that matters
for payment: the whole document.

## 9.3 Research questions and hypotheses

- **RQ1** — Does enterprise-record evidence increase the share of
  documents that can be processed without review at a fixed
  document-level error budget?
  **H1**: fused gate coverage exceeds the document-only calibrated gate
  by ≥ 5 percentage points at α = 2 %, with empirical risk ≤ α.
- **RQ2** — Does calibrating directly at document level beat composing
  field-level gates?
  **H2**: higher coverage at the same document-level α.
- **RQ3** — How does the gain degrade with stale or incomplete
  enterprise records?
  **H3a**: gain decreases monotonically with master-data noise and stays
  positive up to a reported noise level; risk control still holds.
- **RQ4 (optional)** — Does recalibration from reviewer labels keep the
  guarantee as new vendors and templates appear?
  **H4**: risk ≤ α per time window with recalibration, > α without.

## 9.4 Related work structure

1. **Selective prediction and risk control** — selective classification
   [7], learning to defer [18], calibration [9], Learn-then-Test [1],
   conformal risk control [2]. *Difference*: we apply them, we do not
   extend them.
2. **Document information extraction** — LayoutLM / LayoutLMv3 [27, 10],
   Donut [14], OCR/conversion [6, 3]; benchmarks SROIE, CORD, DocILE,
   FATURA, VRDU [11, 20, 23, 17, 26]; long-tail suppliers [15].
   *Difference*: benchmarks lack enterprise context; we construct it.
3. **Confidence for straight-through document processing** — HYCEDIS
   [19], conformal KIE [21], ConfBench [22], multi-signal calibration
   [28, preprint], perception/layout/validation [13]. *Difference*: their
   evidence is document-internal and per field; ours adds enterprise
   records and controls document-level risk.
4. **AI in procurement / P2P** — reviews [8, 24, 4, 16]; three-way
   matching and master-data matching in practice (product docs).
   *Difference*: practice uses rules; we calibrate and measure.

## 9.5 Proposed methodology

```mermaid
flowchart LR
  D[Document<br/>upload · email · folder] --> X[Read & extract<br/>OCR · classify · fields]
  X --> DI[Document-internal evidence<br/>OCR quality · field conf. · format<br/>arithmetic · checksum · LayoutLMv3 agreement]
  X --> EC[Enterprise evidence<br/>vendor master · GSTIN/IFSC<br/>PO & ledger balance · duplicates · bank details]
  DI --> C[Calibrator<br/>p(document correct)]
  EC --> C
  C --> G{LTT gate<br/>risk ≤ α w.p. 1−δ}
  G -->|accept| A[Straight to approval]
  G -->|defer| R[Review queue<br/>shows the evidence]
  R -->|corrections| L[Labels → recalibration<br/>optional RQ4]
  L --> C
```

- **Integration with the existing system.** Evidence is already produced
  by pipeline stages (`services/document-vendor-agent/app/services/pipeline.py`)
  and stored per stage in `pipeline_checkpoints`. The gate replaces the
  decision in `confidence_agent` behind a business rule
  (`document.review_policy = heuristic | calibrated`), so the current
  behaviour stays the default until the evaluation supports a switch.
- **Calibrator.** Logistic regression (interpretable weights shown to
  reviewers) and scikit-learn histogram gradient boosting; trained on
  vendor-grouped training folds.
- **Gate.** Learn-then-Test over a grid of thresholds; binomial tail
  p-values; fixed sequence testing; α ∈ {1, 2, 5} %, δ = 0.1.
- **Document-level target.** A document is correct when all
  payment-critical fields (vendor, total, currency, document number) and
  the business outcome (right vendor, PO match status, duplicate flag)
  are correct.

## 9.6 Experimental plan

- **Data.** (1) Procurement-world corpus from the extended seeded
  generator: ~3,000 documents, ~100 vendors, controlled visual and
  business-error injections, vendor-grouped splits. (2) External-validity
  run on DocILE or FATURA with enterprise context derived from ground
  truth at controlled noise rates (labelled semi-synthetic).
- **Systems.** B0 current heuristic, B1 document-only calibrated
  (Jin-style without VLMs), B2 rules-only enterprise matcher, P fused;
  P − each evidence group (ablation).
- **Metrics.** Coverage at α; empirical risk and violation frequency
  over 20 splits; AURC; AUROC; ECE/Brier; ₹ at risk among accepted;
  coverage by vendor decile; added latency.
- **Analysis.** Paired bootstrap 95 % CIs for coverage differences
  (P − B1, P − B2); pre-registered minimum effect (5 pp at α = 2 %);
  risk–coverage curves; failure analysis of accepted-but-wrong documents
  by injection type.
- **Recording.** `scripts/eval_selective.py` →
  `docs/results/selective.{json,md}`; MLflow runs; corpus seed and
  generator version in every result file.

## 9.7 Intended contributions (until experiments support them)

- **Engineering**: an open procurement platform whose automation gate is
  calibrated and risk-controlled, with evidence shown to reviewers.
- **Methodological**: a document-level, cost-aware risk-control
  formulation fusing document-internal and enterprise evidence.
- **Empirical**: the first (within our search scope) measurement of how
  much enterprise evidence adds to calibrated selective automation, with
  ablations and robustness to stale records.
- **Practical/resource**: a seeded procurement-world generator linking
  documents to vendor master, POs and ledger (no such public dataset was
  found).

## 9.8 Paper outline

1. Abstract — written last, from the results actually obtained.
2. Introduction — problem, cost of errors, gap, RQs, contributions.
3. Related work — the four strands in 9.4.
4. Problem formulation — documents, evidence, document-level risk,
   selective automation with risk control.
5. Method — evidence features, calibrator, LTT gate, integration.
6. Experimental setup — data, injections, splits, baselines, metrics.
7. Results — RQ1–RQ3 (RQ4 if done), ablations, risk–coverage figures.
8. Discussion — when enterprise evidence helps and when it does not;
   operational guidance.
9. Limitations and threats to validity — synthetic context, extractor
   specificity, reviewer-as-oracle, exchangeability.
10. Conclusion and future work.
11. References.

Target venues to choose from (not yet decided): ICDAR workshops /
IJDAR (document analysis), a decision-support or information-systems
journal, or an applied ML workshop. Pick after RQ1 results.

## 9.9 Publication readiness — evidence required before any claim

- [ ] RQ1 result with confidence intervals on the procurement-world
      corpus, all four systems.
- [ ] Risk-control check: empirical risk ≤ α in ≥ 1−δ of splits.
- [ ] Ablation table (each evidence group).
- [ ] Robustness curve (RQ3).
- [ ] External-validity run on public invoices (or a clear statement why
      it could not be done).
- [ ] Failure analysis with examples.
- [ ] Literature search re-run within four weeks of submission (the 2026
      literature moves fast; Jin et al. appeared in September 2026).
- [ ] Every number in the paper traceable to `docs/results/selective.json`.

## 9.10 First results (19 Oct 2026)

Run: 3,000 generated invoices, 100 vendors (generator 1.0, seed 7), read
with the production code, 20 vendor-grouped splits, δ = 0.1. Every number
is in `docs/results/selective.json`.

- **H1 not supported at the planned budgets.** At α = 1, 2 and 5 % none
  of the calibrated gates built from the production evidence (B1, P, FC)
  accepts anything (P-hgb: 1.8 % at α = 5 %). Reason, from the
  diagnosis: about 5 % of the best-scored invoices carry an error no
  current check sees, mostly **duplicates with a new invoice number**
  (the production duplicate rule requires the numbers to be ≥ 85 %
  similar, and the PO still has quantity left), plus overbilling the
  three-way match can't see when scanned line items are misread. LTT
  correctly refuses to accept anything it can't certify.
- **Enterprise evidence does carry signal.** Threshold-free: AUROC 0.941
  (P) vs 0.741 (B1, document only); AURC 0.135 vs 0.268. Ablation: the PO
  match matters most (AUROC 0.833 without it), then bank details (0.900),
  duplicates (0.919) and GSTIN (0.924).
- **The current rules are not risk-controlled.** B0 (today's heuristic)
  accepts 41.4 % of invoices with 6.8 % of them wrong; B2 (all
  enterprise checks pass) accepts 59.4 % with 12.9 % wrong.
- **RQ2:** the field-composed gate (FC) accepts nothing at any α tested;
  no evidence yet for or against H2.
- **Exploratory (decided after seeing the diagnosis, so not a test of
  H1):** adding the duplicate check without the number condition (P+dup,
  equal to setting rule `vendor.duplicate_invoice_number_fuzzy_threshold`
  to 0) gives 16.6 % coverage at α = 2 % (risk 0.5 %, violations 10 %)
  and 42.2 % at α = 5 % (risk 2.6 %, violations 20 %, above δ).
- **RQ3 (at α = 10 %, added because nothing passes at ≤ 5 %):** P's AUROC
  falls from 0.941 to 0.841 as 40 % of master data goes stale; coverage
  is near zero throughout, so the coverage curve says little yet.
- **Validity of the guarantee:** violation rates up to 20 % on some
  exploratory settings exceed δ. LTT assumes calibration and test
  documents are exchangeable; vendor-grouped splits (and one vendor with
  350 of 3,000 invoices) break that, and test-set noise adds to it. To
  report: per-split risk, and a document-level split as a check.

What this means for the paper: Title 3 ("Measuring the value of
enterprise context…") fits. Before writing: (1) decide whether the
duplicate rule change is a product fix (then P+dup becomes the main
system and needs a fresh seed to be a real test), (2) re-run with a new
seed, (3) RS-08 external validity, (4) the guarantee under vendor shift.
