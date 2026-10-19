# Presentation outline (FR-12)

A 15-minute deck for the end-of-October review: problem → solution →
architecture → each agent → results → limits. Every slide names the
picture and the number to paste; all of them are in `docs/results/`
(index: [docs/results/README.md](results/README.md)). The live demo
follows the deck ([docs/showcase.html](showcase.html)).

| # | Slide | Say (one line) | Show |
|---|---|---|---|
| 1 | Title | IT Procurement Intelligence Platform — five cooperating agents | Team names, Fractal Analytics 2026–27 |
| 2 | The problem | Procurement is a chain of manual hand-offs; the risky cases (fake invoices, changed bank details, unreliable vendors) are easy to miss | Three icons: retyping, chasing approvals, checking by eye |
| 3 | What we built | A document arriving anywhere is read, approved, contracted, signed, received and matched — people step in only for decisions | `docs/project-flow.html` (tab 1) screenshot |
| 4 | Architecture | Five FastAPI agents, events through Kafka with an outbox, Temporal for long processes, one Postgres, MinIO, a React app behind one gateway | README architecture diagram |
| 5 | Document & Vendor agent | Reads PDFs, scans and photos, sorts invoice / PO / quote / other, matches and onboards vendors, guards bank details | `screens/02-document-detail.png`; extraction 100 % (PDFs), classifier results; `samples/document-vendor-agent.json` |
| 6 | Approval & Inventory agent | Spend tiers and approval authority, nobody approves their own request, stock and reorder suggestions, licence reclaim | `screens/06-request-lifecycle.png`, `screens/07-inventory-reorder.png`; licence anomaly ROC-AUC 0.954 |
| 7 | Licence intelligence | An anomaly model trained on 360 simulated licences finds drop-offs and declines (87 % / 71 % caught); an "anomalous" licence gets a reclaim with a grace period | `screens/08-licence-anomaly.png`; `results/licence-anomaly.md` table — be upfront that the demo's two declining licences rank highest but sit just under "watch" |
| 8 | Contract & Risk agent | Contracts written and signed in the app, renewals from the notice deadline, vendor risk shown before signing (High needs acknowledgement); Legal-BERT reads the clauses; vendors screened against sanctions lists | `screens/09-contract.png`, `screens/03-vendor-risk.png`; risk model ROC-AUC 0.715 (ceiling 0.739), red-team 12/12; clauses F1 0.85 / 0.80 / 0.91 vs rules 0.50 / 0.19 / 0.02 (`results/clauses.md`) |
| 9 | Notifications & rules | Every lifecycle event becomes an email (coverage audited); 47 business rules editable live, each enforced one tested | `screens/11-business-rules.png`; `docs/notifications.md` table; `docs/business-rules.md` count |
| 10 | Reliability & controls | Outbox + retries + dead-letter queue, failed events visible, one correlation id through all logs, model fallback on demand | `screens/10-control-panel.png`, `screens/12-system-health.png`, `results/logs-correlation.png` |
| 11 | Results (ML) | Each model measured on held-out data against a baseline | Table from `results/README.md` (extraction, classifier, risk, licence anomaly, clauses) |
| 12 | Testing | Unit suites per service + end-to-end runs through the gateway; every fix proven by reverting it | Counts from `results/README.md` |
| 13 | Research direction | When can an invoice skip review? Calibrated, risk-controlled automation using company records. First run (3,000 synthetic invoices): company records lift AUROC 0.74 → 0.94, but at a ≤ 5 % error budget nothing can be certified yet — the duplicate rule misses resubmitted invoices; today's rule accepts 41 % with 6.8 % wrong | `docs/project-flow.html#research`, `results/selective.md` |
| 14 | Limits & next steps | All data synthetic; noisy scans read poorly; prototype, not production (CI tests, secrets, TLS next) | Bullets |
| A | Appendix: run it | `./run.sh` (builds what changed, starts everything), `./scripts/seed-demo-data.sh`, `install.sh` (first run) | Terminal screenshot of `./run.sh` output |

Report templates (Overall and Agent docs, "Results and Evaluation"): paste
per agent the sample from `docs/results/samples/`, the screenshot from
`docs/results/screens/`, and the metric row from `docs/results/README.md`.
Include `run.sh` and `install.sh` in the appendix (18 Jul feedback #3).
