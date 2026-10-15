# Vendor risk model

How the platform rates a vendor Low / Medium / High risk, what data the
model learned from, and how well it does. Numbers come from
`docs/results/risk-model.md` (regenerate with the command at the end).

## What it does

When a vendor is matched (or finance clicks *Recompute*), contract-risk-agent:

1. **Runs the hard checks first.** A vendor whose GSTIN is *cancelled* or
   *suspended* is **High**, whatever the model says, and the reason is shown
   as the first factor. Sanctions screening and IFSC verification belong to
   the same step but their results aren't stored yet, so they show as
   *not checked* (sanctions screening is roadmap item FR-14).
2. **Scores the vendor with a Random Forest** (200 trees, depth 6) on six
   signals: tenure, on-time delivery rate, financial stability, breach
   disclosures, security certification and a geographic-risk flag.
3. **Turns the score into a band**: Low ≤ 0.33 < Medium ≤ 0.66 < High
   (`config.yaml`).
4. **Explains it**: the vendor page shows the band, the factors that
   pushed this vendor's score, and *"based on N of 6 signals on file"*.

**Missing data is left out, not guessed.** Before Oct 16 a missing on-time
rate or financial score was filled with 0.5 — below the typical vendor —
so "we don't know" read as "risky". Now the model was trained with 20 % of
values randomly blanked and scores with the gaps; a missing signal is never
a factor. (The two yes/no flags can't be told apart from "not set" in the
database, so they always count as known.)

## The data

There is no public dataset of vendor incidents, so the training set is
**synthetic and seeded** (reproducible): 2,000 vendors.

- 80 % *typical* vendors: tenure 1–120 months, on-time rate mostly high
  (Beta 6,2), finances mostly sound (Beta 5,3), breaches rare (Poisson 0.3),
  35 % certified, 20 % in a flagged geography.
- 20 % *stressed* vendors: newer (1–36 months), delivery and finances
  anywhere from poor to good (Beta 2,2), more breaches (Poisson 1.5),
  15 % certified, 40 % flagged geography.
- **Label** ("had an incident"): a written rule — poor delivery (35 %),
  weak finances (25 %), breach history (25 %) and a flagged geography (10 %)
  raise the risk; certification and tenure lower it — plus noise, then an
  incident is drawn with that probability. 18 % of vendors have one.

The stressed segment was added on Oct 16. With only typical vendors (400
rows) really risky vendors almost never occurred, so the forest had nothing
to learn High from: the red-team profile "everything bad" came out Medium.

## Results (400 held-out vendors)

| | Oct 16 (2,000 rows, with stressed segment) | Before (400 typical rows) |
|---|---|---|
| ROC-AUC | **0.715** | 0.707 |
| Best possible ROC-AUC on these labels | 0.739 | 0.702 |
| Accuracy at 0.5 | 0.72 | 0.80 |
| Incidents caught at 0.5 (recall) | 39 / 72 (54 %) | 5 / 12 (42 %) |
| Red-team profiles as expected | **12 / 12** | 7 / 12 |

**How to read it.** The labels are random draws, so even the rule that
made them can't separate them perfectly: 0.739 is the ceiling, and the
model reaches 0.715 of it. Accuracy fell because, with balanced class
weights, the model now flags more vendors as risky — it catches more of
the real incidents at the price of more false alarms, which is the right
trade for a screening step that a human reviews. With 20 % of values
missing the ROC-AUC holds (0.726).

**Bands mean something.** Incident rate in the test set: Low 6.5 %,
Medium 20 %, High 40 %.

**What drives it** (feature importance): on-time delivery 0.35, financial
stability 0.21, tenure 0.21, breaches 0.09, certification 0.08, geography
0.06.

**Red team.** Twelve hand-written vendors with the band we'd expect,
written before running the model (`services/contract-risk-agent/ml/redteam_profiles.json`):
clear Lows and Highs, borderline Mediums, a perfect vendor with a cancelled
GSTIN (High by override), and three with missing data (nothing on file →
not High; good partial record → Low; only bad delivery known → not Low).
All 12 land as expected. One is close: *repeated breaches, flagged
geography* scores 0.665, just over the High line (0.66).

## Limits

- Synthetic data: the model learns our written rule, not real incidents.
  `risk_score_outcomes` (admins log real outcomes) and the weekly drift
  check are how real data would come in.
- On the platform today, **no vendor has risk signals recorded**
  (`vendor_risk_features` is empty), so every live score is "0 of 6
  signals" — the vendor page now says so instead of showing a confident
  Medium.
- Sanctions and IFSC overrides are wired but have no data yet.

## Reproduce

```bash
docker run --rm -e APP_ENV=development -v "$PWD/docs/results:/out" \
  --entrypoint python procurementautomation-contract-risk-agent \
  ml/evaluate_risk_model.py --out /out
```
