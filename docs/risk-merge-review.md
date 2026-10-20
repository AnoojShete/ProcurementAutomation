# Risk analysis module: merge and integration review

**Date:** 21 October 2026.

**What was merged:** `origin/updated_risk` (Niraj, commit `3e1f5bf`, "Prompt 9C deterministic vendor risk scorecard and clearance architecture") into `anjali`, on top of Phases 1–3.

**What it replaces:** the trained Random Forest risk model with a deterministic, audit-logged 100-point ruleset. Its main parts:
- signal collectors with a circuit breaker
- rating statuses (`assessed` / `provisional` / `not_rated`) and an "Unrated" band
- a purpose-aware clearance gate (`GET /vendors/{id}/clearance`)
- post-score decisions, evidence, disputes, replay and audit bundles
- ruleset governance (`/admin/risk-rulesets`) and weekly monitoring

**How it was checked:**
- The merge was done with `--no-commit`.
- Unit suites for every service and the root tests were run.
- A new live e2e, `tests/e2e/risk_flow.py`, covers the module and every place the rest of the system reads risk.
- All earlier e2e suites and the five demo scenarios were re-run.

## Result

| Check | Result |
|---|---|
| Unit tests | 1,040 pass: document 334, approval 249, contract-risk 299, auth 100, notification 58. Root: 144 passed, 4 skipped, plus 14 |
| Risk module + integration e2e (`risk_flow.py`) | 49 / 49 |
| New and changed risk pages in a browser (scorecard and all its tabs, vendor page, risk dashboard, ruleset governance, monitoring card) | no crashes, no page errors |
| Gateway e2e · invoice lifecycle · budgets · obligations · sourcing | 17/17 · 71/71 · 30/30 · 47/47 · 69/69 |
| Demo scenarios (`demo_scenarios.py`) | 18 / 18 steps as described |
| Regression proof | Each fix below that has a unit test fails with the fix reverted |

The merged system works. Getting there needed the fixes below. The **flagged** items are open decisions for the risk owner; they were not changed.

## Errors found and fixed

| # | Error | Effect | Fix |
|---|---|---|---|
| F1 | Both branches added contract-risk Alembic revisions **0008** and **0009** | Alembic refuses to run (duplicate revisions) | `updated_risk` migrations renumbered to **0010** (scorecard) and **0011** (clearance); the chain is now 0007 → 0011. A database that already ran `updated_risk`'s own 0008/0009 needs `alembic stamp 0007` and then `upgrade` (every migration is idempotent) |
| F2 | `app/services/scorecard/` (package without `__init__.py`) next to anjali's `app/services/scorecard.py` | The module shadows the package, so `from app.services.scorecard.engine import …` fails and the service doesn't start | anjali's file renamed to `performance_scorecard.py` (vendor *performance* scorecard, Phase 3c) |
| F3 | Migration 0011 inserted into `business_rules` with columns `key`, `value`, `updated_by` | **contract-risk-agent could not start** on a real database. The upgrade rolled back cleanly. Its `ON CONFLICT DO UPDATE` would also have overwritten `vendor.petty_tier_max_amount` | Insert removed (auth-service owns the rules table). Test: `test_migrations_do_not_write_business_rules` |
| F4 | Code reads `risk.petty_threshold`, `risk.alert_recipients`, `risk.min_relationship_days` and `risk.raw_retention_months`, none of which is seeded | Admins can't change them; `test_business_rules_registry.py` failed | auth migration **0018** seeds them; a row each in `business-rules.md`; behaviour tests `test_risk_*` in `test_rules_wiring.py`; validator for `risk.alert_recipients` |
| F5 | High-risk alert e-mails now go only to `risk.alert_recipients`, which was unset | Alerts **stopped silently** (they used to go to the risk team) | Seeded with the previous address. The alert is a small function (`send_high_risk_alert`) with a test |
| F6 | `updated_risk`'s frontend did not compile: 43 TypeScript errors | `npm run build` (and so `run.sh`) fails. Causes: `RiskDashboardPage` deleted the definitions of `distribution`, `total` and `scored` together with the drift card; `CardHeader actions=` should be `action=`; missing `Link` import; types missing fields the backend returns | Fixed. Typecheck and build are clean |
| F7 | `GET /vendors/{id}/risk/remediation-plan` used `.order_index(...)` instead of `.order_by(...)` | Always 500 | Fixed, with a test. The plan also now receives the rating status and blocked-by list (it showed `null`) |
| F8 | `GET /vendors/risk-monitoring/weekly-report` built `func.sum(func.cast(cond, func.literal(1)))` | Always 500 | `sum(case(...))`, with a test |
| F9 | `risk_score_updated.j2` ended its subject with `{% endif %}`; with `trim_blocks` the `---` separator merged into the subject | **Every risk-update e-mail failed to render** (notification tests failed) | `{% endif +%}` |
| F10 | The vendor page still rendered the Risk Signals card, which calls the removed `/vendors/{id}/risk-signals` | 404 card on every vendor page | Card and dead API calls removed; the vendor page links to the full scorecard (`/app/vendors/{id}/risk`) |
| F11 | Onboarding now requires `country`; demo scenario 4 onboarded without it and used the removed `PATCH /risk-signals`; scenario 1 assumed a Medium vendor signs without acknowledgement | `reset-demo.sh` would stop at scenario 1 | Scenarios updated for the scorecard (country, recompute + clearance, acknowledgement when asked); `demo_5min.py` and `demo-5min.md` updated |
| F12 | 5 tests in `updated_risk` failed on that branch too | Red suites | Updated for the new engine: e-sign mock, v2 event payload checked against `events.md`, a replay test that checked the *whole test process* for ML imports (now a fresh interpreter), a test patching a removed function, and the lifecycle marker check |
| F14 | The full risk scorecard page (`/app/vendors/{id}/risk`) rendered `thought_process` steps, which are objects, as text | **The page crashed the whole app** (React error #31) for every scored vendor | Steps rendered as group, points and narrative; the type now matches the API. Every tab and Recompute were then checked in a browser |
| F15 | The scorecard header read `assessed_at`, `ruleset_version` and `worst_case_*` at the top level; the API nests them under `audit` and `range`. "Unrated" used the green (success) badge, and the page had its own "Back to Vendor Profile" link | The header showed "Last assessed: —", "Ruleset v", "Worst-Case: pts ()"; an unrated vendor looked safe | Values read from `audit` / `range`; Unrated is neutral; per-page back link removed (the top bar's back arrow covers it) |
| F13 | `invoice_lifecycle.py` asserted the ML model's fields (`signals_total == 6`, GSTIN/sanctions/IFSC overrides) | 4 failing checks | Now checks band, points, rating status, "no false Low" and that GST, sanctions and bank are scorecard signals |

## Flagged for the risk owner (not changed)

| # | Finding | Evidence | Suggestion |
|---|---|---|---|
| G1 | **Contract signing and `/clearance` disagree.** `signing_risk()` asks for an acknowledgement unless the vendor is `assessed`. It ignores post-score decisions (approve / accept risk) and vendor status. The README says downstream services "always query `/clearance`" | Acme after an admin *accept_risk*: `/clearance` says `cleared: true`; its contract still says "acknowledgement required (Unrated)" | Make `signing_risk` use the clearance logic (one function, `purpose=contract`, spend = contract amount) |
| G2 | Budget routing (`approval.high_risk_vendor_requires_finance`) and RFQ scoring read `risk_scores.band` directly, not `/clearance` | An **Unrated** vendor gets no finance step; only High does | Decide whether Unrated should route like High, or call `/clearance` from approval-inventory-agent |
| G3 | In this stack almost every vendor is **provisional / Unrated**: external sources are unreachable and existing vendors have no `country`. Existing scores were backfilled to `not_rated` until recomputed | Acme: 9 of 14 checks *not assessed*, 0 points, Unrated. So every signature needs an acknowledgement, and the High-risk finance step fires only on sanctions | Recompute every vendor after deploying; add `country` to existing vendors and the seed; say so when demoing |
| G4 | The worker still schedules the weekly **PSI drift** workflow against the archived ML baseline | `contract-risk-agent-worker` logs "Drift monitor schedule already running" | Stop the schedule and replace it with the weekly monitoring report |
| G5 | Access rules | Decisions allow a `procurement` role that doesn't exist. Any requester can add evidence (it waits as `pending_review`) or raise disputes for any vendor. Ruleset reads and the weekly report are open to every signed-in user. `accept_risk` is admin-only (finance gets 403), by design | Confirm these are intended |
| G6 | `risk.score.updated` and the alert are published directly after the commit, not through the outbox | Pattern predates the merge | Use `staged(producer, db)` like the other services |
| G7 | `/clearance` returns `reasons: ["rating_provisional"]` together with `cleared: true` when a decision clears the vendor | Same Acme call as G1 | Return only the deciding reason |
| G8 | New database triggers: `risk_scores` and the signal tables are append-only; changing `vendors.status` to `active` raises unless the vendor is cleared or exempt | No current code path changes the status to `active`, so nothing breaks today | Any future activation flow must call `/clearance` first and handle the error |
| G9 | Eight rule keys from the removed migration (for example `risk.min_assessed_share_pct`, `collector.breaker_failures`) are not read by any code: those values are fixed in the ruleset / collectors | — | Seed only what the code reads (done for `risk.min_relationship_days`) |
| G11 | Small inconsistencies in the engine's output | The narrative's last step says "Result Low" for an Unrated vendor; `GET /risk` reports `ruleset_version: 1` while the audit block says ruleset v2 | Use `final_band` in the narrative; read the version from the stored ruleset |
| G10 | The trained Random Forest (ROC-AUC 0.715, `docs/results/risk-model.md`) is archived in `ml/archive/` | The shipped engine has no evaluation against incident outcomes yet | Report updated to say so; evaluate the ruleset on the synthetic incident data |
