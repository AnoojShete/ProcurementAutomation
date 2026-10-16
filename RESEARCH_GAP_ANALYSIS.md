# Research gap analysis: selective automation of procurement documents

Search date: **16 October 2026**. Visual version: `docs/project-flow.html#research` (open in a browser); this file is the full text. Prepared for the ProcurementAutomation
project (see `TODO.md` for the system context). Companion documents:
`RESEARCH_PAPER_PLAN.md` (paper blueprint), `IMPLEMENTATION_PLAN.md`
(checklist).

---

## 1. Executive summary

**Research problem.** The platform reads procurement documents (invoices,
purchase orders, quotes), extracts fields, matches them to the vendor
master, purchase orders, the invoice ledger and registries (GSTIN, IFSC),
and then decides per document: *process automatically* or *send to a
human reviewer*. Today that decision is a hand-weighted average of field
confidences multiplied by OCR quality, compared with a fixed threshold of
0.8 (`app/services/confidence.py`), plus about ten hard "force review"
rules (look-alike vendor, PO mismatch, duplicate, LayoutLMv3 disagreement…).
Nothing guarantees how many wrong values reach approval and payment, and
the threshold was never calibrated.

**State of research.** Calibrated confidence for straight-through
processing (STP) of business documents became an active topic in 2026:
split conformal prediction for key information extraction (Rombach &
Mehdiyev, 2026), a calibration benchmark for VLM extraction (Roy et al.,
2026), multi-signal calibration (Xu, 2026, preprint) and a decomposed
perception / layout / validation confidence with risk control (Jin et al.,
2026). All of them score a **single document in isolation**. Commercial
tools (Rossum, SAP Ariba, Coupa) do match extracted data against master
data and purchase orders, but with manually configured thresholds and
tolerances and no published error guarantees.

**Most significant validated limitation.** Within our search scope, no
academic study evaluates **enterprise-record evidence** — agreement with
the vendor master, purchase-order balance, prior invoices and tax/bank
registries — as an input to a *calibrated, risk-controlled* automation
gate. The closest work (Jin et al., 2026) uses only document-internal
validators, found that those "add little marginal signal" on invoices,
and makes decisions per field, never per document.

**Strongest candidate contribution.** A calibrated, risk-controlled
**document-level** automation gate that fuses document-internal signals
with enterprise-context evidence the platform already computes, evaluated
as a selective-prediction problem: how many documents can be processed
without review while the error rate among them stays below a chosen
budget α — and how much of that comes from enterprise context.

**Recommended direction.** Build a seeded *procurement world* generator
(vendor master, POs, ledger, invoices with controlled errors) on top of
the existing synthetic-document library, log per-document evidence from
the real pipeline, and compare: the current heuristic gate, a calibrated
document-only gate (state-of-the-art style), a rules-only enterprise
matcher (commercial style), and the proposed fused gate.

---

## 2. Scope and methodology

**Questions guiding the review**

1. How do existing systems decide whether an extracted business document
   can be processed without human review?
2. Which signals are used for that decision, and are they calibrated or
   risk-controlled?
3. Is information outside the document (master data, POs, history,
   registries) used as evidence, and has its contribution been measured?
4. Are decisions made per field or per document, and is human feedback
   used to update them?
5. Which datasets and metrics are used, and what do they lack for
   procurement (P2P) settings?

**Sources searched.** Web search over publisher sites and indexes
(Springer, Elsevier/ScienceDirect, ACM, IEEE, PMLR, NeurIPS, ICLR, ECVA,
arXiv, Research Square), Crossref and DataCite metadata APIs for
bibliographic verification, arXiv API for preprint metadata, and official
product documentation (Rossum, Microsoft Learn, AWS, UiPath, SAP
Learning). About 35 queries.

**Search terms (combined).** *Problem:* straight-through processing,
invoice automation, procure-to-pay, three-way matching, accounts payable,
human-in-the-loop document review. *Method:* selective classification,
learning to defer, calibration, conformal prediction, risk control,
uncertainty quantification. *Domain/system:* key information extraction,
visually rich document understanding, LayoutLM, invoice information
extraction, master data matching, entity linking to supplier database.
*Evaluation:* risk–coverage, auto-approval rate, expected calibration
error, benchmark datasets (SROIE, CORD, DocILE, FATURA, VRDU, BPI
Challenge).

**Inclusion.** Peer-reviewed papers, preprints from identifiable authors
with accessible abstracts, official product documentation, public
datasets. Foundational work from 2017 onward for selective prediction /
calibration; 2019 onward for document AI; 2023 onward for procurement-AI
reviews. **Exclusion.** Vendor marketing blogs as evidence of capability
(used only for orientation), papers whose metadata could not be verified,
patents (noted, not analysed).

**Citation chaining.** Backward from Jin et al. (2026) (its datasets and
baselines: DocILE, FATURA, VRDU, Learn-then-Test) and Rombach & Mehdiyev
(2026) (split conformal prediction); forward from Geifman & El-Yaniv
(2017) and Angelopoulos et al. via search results citing them.

**Limitations of this review.**
- No direct subscription searches of IEEE Xplore, ACM DL or Scopus; those
  were reached through web search and Crossref. Coverage of paywalled
  conference papers that are not indexed by the search engine is
  therefore incomplete.
- Full texts read: Jin et al. (2026) in full (arXiv HTML). Rombach &
  Mehdiyev (2026): Crossref abstract only (Springer page requires login).
  Xu (2026): metadata via Crossref, method details only from a search
  summary — treated as **not independently verified**.
- Product capabilities are taken from public documentation; anything not
  documented is marked *unknown*, not absent.
- Rapidly moving area: three of the closest papers appeared between March
  and September 2026. A follow-up search is needed before submission.

---

## 3. Existing research

### 3.1 Selective prediction, deferral and calibration (foundations)

- **Selective classification.** Geifman & El-Yaniv (2017) build a
  selective classifier from a trained network that abstains so that a
  user-chosen error rate holds with high probability (on ImageNet, 2 %
  top-5 error at 99.9 % probability with ~60 % coverage). This is the
  *risk–coverage* framing our problem needs.
- **Learning to defer.** Mozannar & Sontag (2020) learn when to hand a
  case to a human expert, with a consistent surrogate loss. Relevant if
  reviewer behaviour is modelled; we treat the reviewer as always correct,
  which is simpler and is listed as a validity threat.
- **Calibration.** Guo et al. (2017) show modern networks are poorly
  calibrated and that temperature scaling fixes much of it. Our current
  scores are not model probabilities at all (fixed constants such as 0.95
  / 0.6 per field), so calibration is a precondition for any guarantee.
- **Distribution-free risk control.** Learn-then-Test (Angelopoulos et
  al., 2025, *Annals of Applied Statistics*) picks thresholds by multiple
  testing so that a risk (e.g. error among accepted items) stays below α
  with probability 1−δ, without retraining. Conformal risk control
  (Angelopoulos et al., 2024) controls expected monotone losses. These give
  the statistical guarantee that a fixed 0.8 threshold lacks.

### 3.2 Document information extraction

- **Layout-aware models.** LayoutLM (Xu et al., 2020) and LayoutLMv3
  (Huang et al., 2022) jointly model text, layout and image; Donut (Kim et
  al., 2022) removes the OCR step. The platform uses LayoutLMv3 as a
  cross-check; it is not the subject of the contribution.
- **OCR / conversion engines used by the platform.** PP-OCR (Du et al.,
  2020; PaddleOCR) and Docling (Auer et al., 2024).
- **Benchmarks.** SROIE (Huang et al., 2019; receipts), CORD (Park et
  al., 2019; receipts), DocILE (Šimsa et al., 2023; 6.7k annotated real
  business documents incl. invoices and orders, 100k synthetic), FATURA
  (Limam et al., 2023; 10k synthetic invoices, 50 layouts), VRDU (Wang et
  al., 2023). **None of them ships the purchase orders, vendor master or
  payment history that the invoice belongs to** — they evaluate
  extraction, not the procurement decision.
- **Supplier long tail.** Krieger, Drews & Funk (2023) show ML extractors
  suffer layout bias on rarely seen suppliers — directly relevant to
  per-vendor coverage in our evaluation.

### 3.3 Confidence for straight-through processing of documents (closest work)

- **HYCEDIS** (Nguyen et al., 2022; KDD 2021 Document Intelligence
  workshop) combines a multimodal conformal predictor with an anomaly
  detector to score extracted key-value pairs without changing the host
  model.
- **Conformal KIE** (Rombach & Mehdiyev, 2026, *IJDAR* 29(2)) builds
  entity-level prediction sets on receipts: 98.3 % marginal coverage at
  α = 0.02 with ~70 % singletons, and proposes accepting singletons and
  sending the rest to review. Receipts only; signals are model-internal.
- **ConfBench** (Roy et al., 2026) benchmarks verbalized and
  log-probability confidence of seven VLMs over 20 degradation pipelines
  (1,346 document variants, 70k entity evaluations); calibration ranges
  from near-perfect to severely over-confident, and OCR+image input gives
  better confidence.
- **Multi-signal calibration** (Xu, 2026, Research Square preprint, not
  peer-reviewed) reportedly fuses OCR quality, layout ambiguity, model
  uncertainty, semantic validation and image quality on SROIE, CORD and
  FUNSD. *Method details not independently verified.*
- **Perception / layout / validation with risk control** (Jin et al.,
  2026): three feature channels fused by gradient boosting, threshold set
  with Learn-then-Test per field type. On DocILE, FATURA and VRDU the
  fused score reaches AUROC 0.91–0.99 vs 0.54–0.74 for verbalized VLM
  confidence, and auto-approves 39–72 % of fields at ≤ 10 % error vs
  0.1–7 % for the VLM baseline. **Validation checks are document-internal
  only** (format, range, ISO currency/date, IBAN/ISIN checksums,
  arithmetic, second-model agreement); the authors state the rule
  validators "add little marginal signal" on the invoice data. Decisions
  are **per field**; a feedback loop is proposed but **not evaluated**.

### 3.4 Procurement and supply-chain AI

- Reviews agree that AI in procurement is early-stage and dominated by
  automation of the procure-to-pay cycle: Guida et al. (2023),
  Spreitzenbarth et al. (2024, 46 works, 11 use-case clusters + 20 expert
  interviews), Balkan & Akyuz (2025, taxonomic review), Lakhal et al.
  (2025, source-to-pay framework; notes OCR + RPA for invoice
  classification, three-way matching and compliance monitoring as well
  documented in practice).
- Supply-chain risk prediction is mature: Baryannis, Dani & Antoniou
  (2019) on the interpretability–performance trade-off; Jahin et al.
  (2026, SLR of 54 studies). The platform's vendor-risk model is
  therefore **established** work, not a research contribution.
- Process data: the BPI Challenge 2019 log (van Dongen, 2019) records
  real purchase-order handling (PO creation, goods receipt, invoice
  receipt, clearing) but has no documents. No public dataset found links
  invoice *documents* with POs, goods receipts and a vendor master.

### 3.5 How the strands relate

Selective-prediction theory (3.1) supplies guarantees; document AI (3.2)
supplies extractors and benchmarks; 2026 STP work (3.3) joined them but
only on the document itself; procurement practice (3.4, §4) uses
enterprise matching heavily but without calibration or published error
rates. The unresolved point is the intersection: **does enterprise
evidence make calibrated automation safer or broader, and by how much?**

---

## 4. Existing systems and competitors

| System | Decision unit | Signals for automation | Enterprise data used | Threshold / guarantee | Published evaluation |
|---|---|---|---|---|---|
| **Rossum** (Automation rules docs) | Field; document automated only if every field has a validation source | Confidence score, built-in checks, *history-based* checks, custom (connector) checks, field-not-found | Yes — Master Data Hub matches vendors and POs; PO line-item matching extension | Manual per-field thresholds (default 97.5 %; "calibrated to probability of correctness" per Rossum docs) | None found |
| **Microsoft Azure AI Document Intelligence** | Field / element | Field confidence (0–1, described as probability of correctness) | Not documented for the extraction service | User-chosen; docs suggest ≥ 80 %, near 100 % for financial | None found |
| **AWS Textract + Amazon A2I** | Key / key-value / form | Confidence thresholds, missing key, random sampling | Not documented | Manual activation conditions | None found |
| **UiPath Document Understanding** | Field (Validation Station) | OCR and extraction confidence thresholds | Not documented in the reviewed pages | Manual; docs say confidence is "for guidance only" | None found |
| **SAP Ariba** (invoice reconciliation) | Invoice | 2-/3-way match exceptions with tolerances | Yes — PO, receipts | Manual tolerances per exception type | None found |
| **Coupa** | Invoice | Price / quantity / amount / tax tolerances | Yes — PO, receipts | Manual tolerances | Only third-party descriptions found → *unknown* |
| **Docling / PaddleOCR** (open source, used here) | Document conversion / OCR | Engine confidences | No | n/a | Technical reports only |
| **This project (today)** | Document | Weighted field confidence × OCR quality; 10 force-review rules incl. vendor master, PO/ledger, duplicates, GSTIN/IFSC, LayoutLMv3 agreement; per-vendor threshold learned from reviews | Yes | Fixed 0.8 (business rule), uncalibrated | `docs/results/extraction.md` (field accuracy only) |

Undocumented ≠ absent: the commercial tools may calibrate internally, but
none of the reviewed public documentation describes a statistical
guarantee or an evaluation of how much enterprise matching contributes.

---

## 5. Comparative capability matrix

Legend: ✔ documented · ✘ documented as absent / not done · ? not
documented · ◐ exists but insufficient for this use case.

| Capability | Jin et al. 2026 | Rombach & Mehdiyev 2026 | ConfBench 2026 | Rossum | SAP Ariba | This project today | Proposed |
|---|---|---|---|---|---|---|---|
| Calibrated correctness probability | ✔ | ✔ (sets) | ✔ (measured) | ? (claimed) | ✘ | ✘ | ✔ |
| Statistical error guarantee for accepted items | ✔ (LTT, per field) | ✔ (marginal coverage) | ✘ | ? | ✘ | ✘ | ✔ (LTT, per document) |
| Document-internal validation (format, arithmetic, checksum) | ✔ | ✘ | ✘ | ✔ | ◐ | ✔ | ✔ |
| Vendor-master / PO / ledger evidence | ✘ | ✘ | ✘ | ✔ (rules) | ✔ (rules) | ✔ (rules) | ✔ (calibrated) |
| Measured contribution of enterprise evidence | ✘ | ✘ | ✘ | ? | ? | ✘ | ✔ (ablation) |
| Document-level (payment-relevant) decision | ✘ | ◐ (document accuracy reported) | ✘ | ◐ (all fields must pass) | ✔ (rules) | ✔ (uncalibrated) | ✔ |
| Feedback from reviewers updates the gate | ✘ (proposed only) | ✘ | ✘ | ? ("history") | ? | ◐ (per-vendor threshold, unevaluated) | optional (H3) |
| Explanation of why a document needs review | ◐ (channels) | ◐ (set size) | ✘ | ✔ (blockers) | ✔ (exception type) | ✔ (agent trail) | ✔ (evidence + calibrated weights) |
| Robustness to stale / incomplete master data | n/a | n/a | n/a | ? | ? | ✘ | ✔ (sensitivity analysis) |

---

## 6. Research gap analysis

### G1 — Enterprise-context evidence in calibrated automation (primary)

1. **Problem.** Does evidence from records outside the document — vendor
   master match, GSTIN/IFSC registry status, PO existence and open
   balance, ledger/duplicate history, bank details vs master — improve a
   calibrated, risk-controlled decision to process a procurement document
   without review?
2. **Prior work.** Jin et al. (2026); Rombach & Mehdiyev (2026); Xu (2026);
   HYCEDIS (2022); Rossum, SAP Ariba, Coupa.
3. **Evidence of the gap.** Jin et al. list their validation checks; none
   uses an external record (verified in full text). Rombach & Mehdiyev's
   signals are model-internal (abstract). No academic study found that
   measures enterprise evidence inside a calibrated gate. *(Inferred by
   cross-paper comparison within the search scope — not an
   author-reported limitation.)*
4. **Counterevidence.** Commercial systems already use master-data and PO
   matching to unblock automation (Rossum, Ariba), so the *idea* is
   established in practice. Jin et al. found document-internal rule
   validators add little marginal signal on invoices — enterprise checks
   might likewise be redundant with model confidence.
5. **Remaining limitation.** In practice: manual thresholds, no published
   error guarantee, no measurement of the contribution. In research: not
   studied.
6. **Why it matters.** The costly procurement errors (paying the wrong
   vendor, paying twice, paying more than the PO) are exactly the ones
   document-internal signals cannot see; a document can be perfectly read
   and still wrong for the business.
7. **How to investigate.** Fused calibrated gate vs document-only
   calibrated gate vs rules-only matcher on the same documents (§9).
8. **Technical contribution.** An evidence representation of enterprise
   checks as calibrator features; a document-level LTT gate; a
   procurement-world generator with enterprise ground truth.
9. **Hypothesis (H1).** At document-level error budget α ∈ {1 %, 2 %, 5 %},
   the fused gate auto-processes significantly more documents than the
   document-only calibrated gate (pre-registered minimum effect: +5
   percentage points at α = 2 %), with empirical risk ≤ α.
10. **Data / experiments.** Procurement-world corpus (synthetic with
    controlled error injection) + external-validity run on DocILE or
    FATURA with derived enterprise context; ablations per evidence group.
11. **Risks.** Synthetic context can make enterprise checks artificially
    informative (mitigated by sensitivity analysis on master-data noise
    and by a public-data run); a negative result is possible and
    publishable as such.
12. **Assessment.** Novelty: **potentially underexplored** (practice
    exists; calibrated measurement does not, in our scope). Feasibility:
    **high** — all checks already exist in the pipeline and are logged in
    `pipeline_checkpoints`.

### G2 — Document-level risk control instead of per-field (complementary)

1. **Problem.** Approval and payment act on a whole document, but
   published gates guarantee per-field error. Combining per-field gates
   (all fields accepted) does not give a known document-level error.
2. **Prior work.** Jin et al. (per field only, stated); Rombach &
   Mehdiyev (report document accuracy but sets are per entity); Rossum
   (document automates only if all fields validate — manual).
3. **Evidence.** Jin et al.: "The reporting unit is a field extraction";
   no document-level analysis (full text).
4. **Counterevidence.** Document-level risk could be bounded with a union
   bound over fields; that is simple and may be close enough.
5. **Limitation.** Union bounds are conservative (lower automation);
   payment-critical fields matter more than others.
6. **Why it matters.** The business error is "a wrong document reached
   approval/payment", weighted by money at risk.
7. **How.** Calibrate directly on document correctness (payment-critical
   fields: vendor, total, currency, document number) and compare with
   per-field composition (all fields ≥ per-field LTT threshold; union
   bound) and min-field-confidence.
8. **Contribution.** Methodological comparison; cost-weighted risk
   (₹ at risk among accepted documents).
9. **Hypothesis (H2).** At the same document-level α, direct
   document-level calibration achieves higher coverage than per-field
   composition, while both keep empirical risk ≤ α.
10. **Data.** Same corpora as G1.
11. **Risks.** Fewer document-level labels than field labels → wider
    bounds; small calibration sets weaken LTT.
12. **Assessment.** **Incremental**, but necessary for the procurement
    claim. Feasibility **high**.

### G3 — Reviewer feedback keeping the guarantee under drift (optional)

1. **Problem.** New vendors and new templates shift the distribution; a
   gate calibrated once can silently violate α.
2. **Prior work.** Jin et al. propose periodic refresh from audited
   samples but do not test it; Krieger et al. (2023) document long-tail
   supplier bias; the project already learns per-vendor hints and
   thresholds from reviews (`app/services/learning.py`), unevaluated.
3. **Evidence.** Stated as unevaluated future work (Jin et al.).
4. **Counterevidence.** Non-exchangeable / adaptive conformal methods
   address drift in general.
5. **Limitation.** No procurement-specific evaluation.
6. **Why.** Vendor onboarding is continuous (BR-4 now onboards from a
   form).
7. **How.** Stream documents with new vendors appearing over time;
   compare static calibration, periodic recalibration from reviewed
   documents, and per-vendor thresholds.
8. **Contribution.** Empirical.
9. **Hypothesis (H3).** With periodic recalibration from reviewer labels
   the empirical risk of accepted documents stays ≤ α across time
   windows, while the static gate exceeds α after new templates appear.
10. **Data.** Time-ordered procurement-world stream.
11. **Risks.** Simulated drift may be unrealistic; scope creep.
12. **Assessment.** **Incremental**; drop first if time is short.

### Gaps considered and not pursued

| Candidate | Why not |
|---|---|
| Better vendor-risk model | Supply-chain risk ML is established (Baryannis et al., 2019; Jahin et al., 2026); our data is synthetic — no defensible claim. |
| Invoice fraud / BEC detection | High value, but no labelled data; only patents and vendor material found. |
| Licence-usage anomaly | No ground truth beyond injected anomalies; tuning is FR-32 engineering work. |
| LLM agent orchestration | The platform's agents are rule/ML stages, not LLM agents; the chatbot belongs to another team member. Combining LLM + agents is not a contribution by itself. |
| New extraction model | Crowded field (LayoutLM family, Donut); we cannot compete on extraction accuracy. |

---

## 7. Candidate innovations (evaluated)

| Criterion | I1 Enterprise-evidence calibrated gate (G1) | I2 Document-level risk control (G2) | I3 Feedback recalibration under drift (G3) | I4 Evidence-based review explanation | I5 Counterfactual "what would make this auto-approve" |
|---|---|---|---|---|---|
| Gap | G1 (cross-paper evidence) | G2 (Jin et al. per-field, stated) | G3 (Jin et al. future work, stated) | none distinct (Rossum blockers, Ariba exceptions already explain) | none verified |
| Novelty | Potentially underexplored | Incremental | Incremental | Established | Novelty unverified |
| Practical value | High: fewer reviews at the same safety, catches business errors | High: matches how payments work | Medium-high | Medium (UX) | Low-medium |
| Technical feasibility | High: checks exist and are logged | High | Medium | High (agent trail exists) | Medium |
| Data feasibility | Medium: needs generator extension + labels | Same as I1 | Medium: needs time-ordered stream | n/a | Same as I1 |
| Effort | Medium | Low (on top of I1) | Medium | Low | Medium |
| Evaluation feasibility | High (risk–coverage, ablation) | High | Medium | Low (needs user study) | Low |
| Baselines | Current heuristic, doc-only calibrated (Jin-style), rules-only (Rossum/Ariba-style) | Per-field composition, union bound, min-confidence | Static calibration | — | — |
| Paper suitability | Strong core claim | Strengthens the claim | Good extension section | Engineering only | Weak |
| Main risks | Synthetic context bias; null result | Small calibration sets | Unrealistic drift | — | — |

**Ranking.** I1 (primary) → I2 (complementary, same experiments, makes
the claim procurement-specific) → I3 (optional). I4 is built as
engineering (the review page shows the evidence) but is not claimed. I5
is dropped.

---

## 8. Recommended contribution

**Claim to investigate.** *For procurement documents, adding evidence from
enterprise records (vendor master, purchase orders and ledger, prior
invoices, tax and bank registries) to a calibrated, risk-controlled
automation gate increases the share of documents processed without
review at a fixed document-level error budget, compared with calibrated
gates using only the document itself; and the gain persists, shrinking
gracefully, when the enterprise records are incomplete or stale.*

**Relation to prior work.** Uses the risk-control machinery of
Learn-then-Test (Angelopoulos et al., 2025) and the calibrated-fusion
design of Jin et al. (2026) as the document-only baseline; adds the
evidence that commercial P2P tools use as hard rules (Rossum, SAP Ariba)
and measures it. It does **not** claim a new extractor, a new conformal
method, or that enterprise matching is new in practice.

---

## 9. Experimental design

### Research questions

| | Question | Hypothesis | Baseline(s) | Supports | Contradicts |
|---|---|---|---|---|---|
| RQ1 | Does enterprise evidence increase safe automation? | H1: fused gate coverage − doc-only coverage ≥ 5 pp at α = 2 % (document level), risk ≤ α | B1 doc-only calibrated; B2 rules-only; B0 current | Paired bootstrap 95 % CI of the difference > 0 and ≥ 5 pp; LTT risk held in ≥ 1−δ of splits | CI includes 0, or gain only when context is noise-free |
| RQ2 | Is document-level calibration better than composing field-level gates? | H2: higher coverage at equal document-level α | All-fields-pass with per-field LTT; union bound; min-field-confidence | Positive paired difference | Composition matches or beats it |
| RQ3 | How robust is the gain to imperfect enterprise data? | Gain decreases monotonically with master-data noise / missing POs but stays > 0 up to a stated level | Same as RQ1 at each noise level | Monotone, positive up to ~20 % stale records | Gain vanishes at small noise, or risk control breaks |
| RQ4 (optional) | Does reviewer-feedback recalibration keep the guarantee under drift? | H3 | Static calibration | Risk ≤ α per window with recalibration, > α without | No difference |

### Systems compared

- **B0 current production gate**: weighted heuristic × OCR quality,
  threshold 0.8, force-review rules (exactly `confidence.py` + pipeline).
- **B1 document-only calibrated gate** (state-of-the-art style, Jin et al.
  without VLMs): OCR quality, per-field extractor confidence,
  classification confidence, format/arithmetic/checksum validators,
  LayoutLMv3 agreement, preprocessing measurements (skew, noise σ) →
  calibrator → LTT threshold.
- **B2 rules-only enterprise matcher** (commercial style): automate iff
  vendor matched, PO found and within tolerance, not duplicate, registry
  checks pass, all fields present.
- **P fused gate**: B1 features + enterprise evidence groups
  (E-vendor: match score/type, look-alike; E-registry: GSTIN/IFSC status;
  E-PO: PO found, open balance ≥ total, variance; E-history: duplicate
  similarity, prior invoices from vendor; E-bank: bank details vs master).
- Calibrators: logistic regression (interpretable) and histogram gradient
  boosting (scikit-learn; no new dependency), with isotonic
  post-calibration if needed.

### Data

1. **Procurement world (primary, synthetic).** Extend
   `services/document-vendor-agent/scripts/synthetic_invoice_lib.py`
   (seeded): vendor master with look-alike names, POs and ledger,
   invoices/POs/quotes rendered as PDF and images, with **controlled
   injections**: visual degradation (rotation, noise, low resolution —
   already in `eval_extraction.py`), extraction-hard layouts, and business
   errors (amount ≠ PO, unknown vendor, duplicate, changed bank details,
   wrong currency). Target ~3,000 documents, ~100 vendors; splits
   *grouped by vendor* (train / calibration / test) so the test measures
   unseen vendors. Ground truth is known by construction.
2. **External validity.** DocILE (real invoices; licence/terms to check)
   or FATURA (synthetic invoices, Zenodo). Enterprise context is derived
   from ground truth with a controlled noise rate → reported as
   semi-synthetic.
3. **Not used for the core claim**: SROIE / CORD (receipts — no PO
   context), BPI 2019 (no documents).

### Metrics

| Metric | Why |
|---|---|
| Coverage (auto-processed share) at α ∈ {1, 2, 5} % | The business quantity: fewer reviews at a fixed safety level |
| Empirical selective risk + share of splits where risk > α | Checks the guarantee actually holds |
| AURC (area under risk–coverage) | Threshold-free comparison |
| AUROC of correctness | Discrimination (comparable with Jin et al.) |
| ECE / Brier (field and document) | Calibration quality of the probability shown to reviewers |
| ₹ at risk among accepted documents | Cost-weighted error; procurement-specific |
| Coverage per vendor decile (long tail) | Fairness across suppliers (Krieger et al., 2023) |
| Added latency per document | Enterprise lookups are DB queries; must stay small |

### Ablations

P vs P − {E-vendor}, P − {E-registry}, P − {E-PO}, P − {E-history},
P − {E-bank}; P with logistic vs boosting calibrator. Small matrix: 5 +
1 runs × seeds.

### Reproducibility

Seeded generator (SEED recorded per corpus), 20 random grouped splits,
fixed calibrator hyper-parameters chosen on training folds only,
`scripts/eval_selective.py` writing `docs/results/selective.json` and
`.md` (same pattern as `eval_extraction.py`), MLflow run per experiment,
negative results kept.

---

## 10. Limitations and threats to validity

- **Synthetic enterprise context (construct / external validity).** The
  generator decides how often business errors occur and how detectable
  they are. Mitigation: vary injection rates, report sensitivity (RQ3),
  run the public-data check, state that results are not real-world
  proof.
- **Extractor specificity.** Our extractor is rule/regex + PaddleOCR +
  LayoutLMv3 cross-check, not a VLM; absolute coverage will differ from
  Jin et al.; only relative comparisons are claimed.
- **Reviewer as oracle.** We assume reviewers are always right
  (Mozannar & Sontag model fallible experts); real review errors would
  lower all systems' effective accuracy.
- **Exchangeability.** LTT guarantees assume calibration and test data
  are exchangeable; vendor-grouped splits and the drift study (RQ4) probe
  this.
- **Small calibration sets** weaken bounds; report δ and set sizes.
- **Selection bias of the review**: rapidly moving 2026 literature;
  web-search coverage of paywalled venues is incomplete (§2).
- **Group effects**: abstention may concentrate on rare vendors; report
  per-vendor coverage.

---

## 11. References

Peer-reviewed unless marked *preprint* / *dataset* / *documentation*.
Metadata verified on 16 Oct 2026 via Crossref, DataCite, the arXiv API or
the publisher page.

1. Angelopoulos, A. N., Bates, S., Candès, E. J., Jordan, M. I., & Lei, L.
   (2025). Learn then test: Calibrating predictive algorithms to achieve
   risk control. *The Annals of Applied Statistics*, 19, 1641–1662.
   https://doi.org/10.1214/24-AOAS1998
2. Angelopoulos, A. N., Bates, S., Fisch, A., Lei, L., & Schuster, T.
   (2024). Conformal risk control. *ICLR 2024*.
   https://proceedings.iclr.cc/paper_files/paper/2024/hash/f3549ef9b5ff520a7e41ff3cc306ab2b-Abstract-Conference.html
3. Auer, C., Lysak, M., Nassar, A., Dolfi, M., Livathinos, N., et al.
   (2024). Docling technical report. *arXiv:2408.09869* (preprint).
4. Balkan, D., & Akyuz, G. A. (2025). Artificial intelligence (AI) and
   machine learning (ML) in procurement and purchasing decision-support
   (DS): a taxonomic literature review and research opportunities.
   *Artificial Intelligence Review*, 58, 341.
   https://doi.org/10.1007/s10462-025-11336-1
5. Baryannis, G., Dani, S., & Antoniou, G. (2019). Predicting supply chain
   risks using machine learning: The trade-off between performance and
   interpretability. *Future Generation Computer Systems*, 101, 993–1004.
   https://doi.org/10.1016/j.future.2019.07.059
6. Du, Y., Li, C., Guo, R., Yin, X., Liu, W., et al. (2020). PP-OCR: A
   practical ultra lightweight OCR system. *arXiv:2009.09941* (preprint).
7. Geifman, Y., & El-Yaniv, R. (2017). Selective classification for deep
   neural networks. *NeurIPS 2017*, 4878–4887. arXiv:1705.08500.
8. Guida, M., Caniato, F., Moretto, A., & Ronchi, S. (2023). The role of
   artificial intelligence in the procurement process: State of the art
   and research agenda. *Journal of Purchasing and Supply Management*, 29,
   100823. https://doi.org/10.1016/j.pursup.2023.100823
9. Guo, C., Pleiss, G., Sun, Y., & Weinberger, K. Q. (2017). On
   calibration of modern neural networks. *ICML 2017*, PMLR 70,
   1321–1330. https://proceedings.mlr.press/v70/guo17a.html
10. Huang, Y., Lv, T., Cui, L., Lu, Y., & Wei, F. (2022). LayoutLMv3:
    Pre-training for document AI with unified text and image masking.
    *ACM Multimedia 2022*, 4083–4091.
    https://doi.org/10.1145/3503161.3548112
11. Huang, Z., Chen, K., He, J., Bai, X., Karatzas, D., Lu, S., &
    Jawahar, C. V. (2019). ICDAR2019 competition on scanned receipt OCR
    and information extraction. *ICDAR 2019*, 1516–1520.
    https://doi.org/10.1109/ICDAR.2019.00244
12. Jahin, M. A., Naife, S. A., Saha, A. K., & Mridha, M. F. (2026). AI in
    supply chain risk assessment: A systematic literature review and
    bibliometric analysis. *SN Business & Economics* (per arXiv journal
    reference; publisher DOI not verified). arXiv:2401.10895.
13. Jin, Y., Wang, Y., Han, Y., Kwan, C. Y. S., Song, W., et al. (2026).
    Perception, layout, and validation: Calibrated confidence for reliable
    straight-through processing of financial documents.
    *arXiv:2609.20110* (preprint).
14. Kim, G., Hong, T., Yim, M., Nam, J., Park, J., et al. (2022). OCR-free
    document understanding transformer. *ECCV 2022*.
    https://doi.org/10.1007/978-3-031-19815-1_29
15. Krieger, F., Drews, P., & Funk, B. (2023). Automated invoice
    processing: Machine learning-based information extraction for long
    tail suppliers. *Intelligent Systems with Applications*, 20, 200285.
    https://doi.org/10.1016/j.iswa.2023.200285
16. Lakhal, N., Aazami, A., & Kummer, S. (2025). The role of artificial
    intelligence across the source-to-pay framework: Theoretical and
    practical aspects. *Digital Business*, 5, 100160.
    https://doi.org/10.1016/j.digbus.2025.100160
17. Limam, M., Dhiaf, M., & Kessentini, Y. (2023). FATURA: A multi-layout
    invoice image dataset for document analysis and understanding.
    *arXiv:2311.11856* (preprint; dataset on Zenodo).
18. Mozannar, H., & Sontag, D. (2020). Consistent estimators for learning
    to defer to an expert. *ICML 2020*, PMLR 119, 7076–7087.
    arXiv:2006.01862.
19. Nguyen, B.-S., Tran, Q.-B., Nguyen Dang, T.-A., Nguyen, D., & Le, H.
    (2022). HYCEDIS: HYbrid Confidence Engine for Deep Document
    Intelligence System. *arXiv:2206.02628* (preprint; KDD 2021 Document
    Intelligence workshop).
20. Park, S., Shin, S., Lee, B., Lee, J., Surh, J., Seo, M., & Lee, H.
    (2019). CORD: A consolidated receipt dataset for post-OCR parsing.
    *NeurIPS 2019 Workshop on Document Intelligence*.
    https://mlanthology.org/neuripsw/2019/park2019neuripsw-cord
21. Rombach, A., & Mehdiyev, N. (2026). Beyond accuracy: Understanding
    model confidence in key information extraction with conformal
    prediction. *International Journal on Document Analysis and
    Recognition*, 29(2), 551–563.
    https://doi.org/10.1007/s10032-026-00572-y
22. Roy, P., Martin, S., Rostami, M., Romo, S., Xue, R., Strahan, B.,
    Socolinsky, D. A., Xie, B., & Islam, M. M. (2026). Can you trust the
    confidence? ConfBench for vision-language models on document
    extraction. *arXiv:2608.01792* (preprint).
23. Šimsa, Š., Šulc, M., Uřičář, M., Patel, Y., Hamdi, A., Kocián, M.,
    Skalický, M., Matas, J., Doucet, A., Coustaty, M., & Karatzas, D.
    (2023). DocILE benchmark for document information localization and
    extraction. *ICDAR 2023*; arXiv:2302.05658 (proceedings DOI not
    verified).
24. Spreitzenbarth, J. M., Bode, C., & Stuckenschmidt, H. (2024).
    Artificial intelligence and machine learning in purchasing and supply
    management: A mixed-methods review of the state-of-the-art in
    literature and practice. *Journal of Purchasing and Supply
    Management*, 30, 100896. https://doi.org/10.1016/j.pursup.2024.100896
25. van Dongen, B. (2019). BPI Challenge 2019 (dataset). 4TU.Centre for
    Research Data. https://doi.org/10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1
26. Wang, Z., Zhou, Y., Wei, W., Lee, C.-Y., & Tata, S. (2023). VRDU: A
    benchmark for visually-rich document understanding. *KDD 2023*,
    5184–5193. https://doi.org/10.1145/3580305.3599929
27. Xu, Y., Li, M., Cui, L., Huang, S., Wei, F., & Zhou, M. (2020).
    LayoutLM: Pre-training of text and layout for document image
    understanding. *KDD 2020*, 1192–1200.
    https://doi.org/10.1145/3394486.3403172
28. Xu, Z. (2026). Knowing when document AI is wrong: Multi-signal
    confidence calibration for business document field extraction.
    *Research Square* (preprint, not peer-reviewed).
    https://doi.org/10.21203/rs.3.rs-10721490/v1 *(method details not
    independently verified)*

**Product documentation (accessed 16 Oct 2026)**

- Rossum — Automation rules overview:
  https://knowledge-base.rossum.ai/docs/automation-rules-overview ;
  Master Data Hub: https://knowledge-base.rossum.ai/docs/master-data-hub ;
  PO matching with line items:
  https://knowledge-base.rossum.ai/docs/po-matching-with-line-items-extension
- Microsoft — Interpret and improve accuracy and confidence scores:
  https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/concept-accuracy-confidence
- AWS — Human loop activation conditions with Amazon Textract:
  https://docs.aws.amazon.com/sagemaker/latest/dg/a2i-json-humantaskactivationconditions-textract-example.html
- UiPath — Create Document Validation Action:
  https://docs.uipath.com/action-center/automation-suite/2023.4/user-guide/create-document-validation-action
- SAP — Understanding invoice reconciliation (SAP Ariba):
  https://learning.sap.com/courses/sap-ariba-procurement-overview-1/understanding-invoice-reconciliation-1
