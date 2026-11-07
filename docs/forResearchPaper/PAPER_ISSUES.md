# Paper issues: what is left to solve

Paper: `docs/forResearchPaper/paper.tex` (PDF: `paper.pdf`). Status on 7 Nov 2026:
every placeholder is filled except the ones below, and the paper is 6 pages.
Numbers in the paper come from the 6 Nov re-run (see issue 9).

Written for: the four team members who will finish and submit the paper. No
background in the statistics is needed; the "why it matters" line says what each
item risks.

## A. Things only you can do (numbered, in order of importance)

1. **Check the page count with real pdfLaTeX.** I could only compile with
   `tectonic` (XeTeX), which does not use the Times font IEEE uses. I measured
   with a Times-like font and got 6 pages, no overfull-box warnings. Run
   `pdflatex paper.tex` twice; if it is 7 pages, shorten prose (do not shrink
   fonts or margins). *Why it matters: over the page limit = desk reject.*
2. **Institutional e-mails.** Four authors still show personal Gmail
   addresses taken from git history (Anjali, Vaidehi, Niraj, Anooj). Only
   Jyoti's is institutional (`jyoti.more@fcrit.ac.in`). Replace them in the
   author block of `paper.tex`.
3. **Reference [9] (Rossum "Master data hub").** The URL
   `https://knowledge-base.rossum.ai/docs/master-data-hub` now redirects to
   Coupa's documentation and I could not read it. Open it in a browser, confirm
   it is the right page, and fix the URL and access date.
4. **Reference [19] (DocILE).** Pages (147-166) and DOI are confirmed with
   Crossref, but the LNCS volume number is not in the entry. Add it from the
   Springer page.
5. **Acknowledgment and other AI tools.** I deleted the two placeholders
   because nobody supplied text. If you want to thank people or name other AI
   tools besides Claude, add it to the Acknowledgment section.
6. **Re-check the 2026 references.** [6] (arXiv 2609.20110), [23] (arXiv
   2608.01792) and [7] (IJDAR 2026) were verified in an earlier draft, not
   today. Open each one, confirm title, authors and whether a published version
   exists. The plan (section 9.9) also asks for a fresh literature search within
   four weeks of submission, because the claim "no study measures this" depends
   on it.
7. **Public repository for the code (reference in Section V).** The paper links
   `https://github.com/AnoojShete/ProcurementAutomation`. Confirm it is public
   (or becomes public at submission), contains the generator and
   `eval_selective.py`, and holds no secrets. If the venue is double-blind, set
   `\anontrue` and give an anonymous link instead (placeholder T16).
8. **Self-citation [11] is an unpublished project report.** Decide whether it
   can be shared with reviewers, or cite it as "available on request".
9. **Decide how to present the re-run.** The 19 Oct numbers could not be
   reproduced exactly after the Docker image was rebuilt (OCR output on mild
   scans and the scikit-learn version differ slightly). The paper now uses the
   6 Nov re-run everywhere and says so in the Limitations. Agree as a team that
   this is how you want to report it. Old numbers are kept in
   `docs/results/selective.md` history (git) only.
10. **Decide how to frame the duplicate-check result.** The gate that ignores
    the invoice number (G-rec+dup) certifies a useful share of invoices on three
    new seeds (21.0 % at 2 %, 37.0 % at 5 %), but its error rate is above the
    10 % allowance in some splits (15 % of splits at both budgets on seed 7, up
    to 20 % on another seed). The paper says so plainly. A stronger paper would
    fix this with cluster-aware bounds (invoices of one vendor are not
    independent), which is listed as future work, not done.
11. **Venue template and copyright block.** The file uses the generic IEEEtran
    conference class. When you pick the venue, add its copyright/ISBN line and
    check its own page and reference rules.
12. **Claim not re-checked today (Section VI-C).** "The PO still has quantity
    left, so the three-way match passes too" for the renumbered duplicates. It
    comes from the earlier draft; I verified the other claims in that paragraph
    (78 % of the top-slice errors are duplicates) but not this one. Spot-check
    with `eval_selective.py followup` output or soften the sentence.

## B. What I fixed directly

13. Filled all placeholders T1-T41 that can be derived from code, git history
    or results (list in the commit messages and in the results files).
14. Wrong fact in the paper: "15 % of vendors invoice in US dollars" was the
    generator's probability, the generated data has 21 of 100. Corrected.
15. Wrong description of the threshold grid: it starts at 1.5 times the minimum
    count (not exactly at it) and uses the calibration set only through its
    size. Corrected.
16. "Risk" in Table III is a mean over all 20 splits, an empty split counting as
    0 %. For sparse gates this hides the real risk (G-rec at 5 %: 0.6 % over all
    splits, 4.3 % over the 3 splits that accept). Both are now stated.
17. The sentence "arithmetic errors pass the consistency check" was wrong: the
    extractor flags all 127 as a mismatch; neither the deployed rule nor the
    learned gate treats that flag as a stop. Rewritten.
18. IEEE format: abstract cut to 247 words (limit 250); reference list rewritten
    in IEEE style (abbreviated journal titles, `doi:` with a space, arXiv number
    after the year, NeurIPS/ICML proceedings names); citation order checked
    against reference order (matches). Overfull boxes removed; author block
    re-broken.
19. Other documents that quoted the 19 Oct numbers now match the re-run:
    `docs/RESEARCH_PAPER_PLAN.md`, `docs/TODO.md`, and the dashboard sentences
    in `docs/index.html` (7.2 % wrong, not 6.8 %).
20. The study depends on the three-way-match code as it was on 19 Oct
    (commit a091d11); the live code has since gained partial receipts and TDS.
    The study now loads that older file (`data/ledger-a091d11/`, setting
    `STUDY_LEDGER_PATH`) so it stays reproducible. It is committed.
21. `scikit-learn` is now pinned (`==1.9.1`) in the document-vendor-agent
    requirements, so a rebuilt image gives the same results. Rebuild the image
    when you next touch that service.

## C. Reproducing the numbers

Scripts and results files (all record generator version, seed and commit):

| What | File |
|---|---|
| Main results, seed 7 | `docs/results/selective.json` / `.md` (commit 1306b21) |
| Conf+LTT, failure breakdowns, stale records, calibration slice | `docs/results/selective_followup.json` (commit 7157c60) |
| New seeds 11, 12, 13 and the duplicate-number variant | `docs/results/selective_heldout.json` (commit 1306b21) |

Commands: see "Research experiment" in `docs/readmeforme.md`. Add
`-e STUDY_LEDGER_PATH=/repo/data/ledger-a091d11/invoice_ledger.py` to the
docker command, and use stages `extract`, `evaluate`, `followup` and `heldout`
(`--seed 11`, `--dup-variant 0.5`). Reading 3,000 documents takes about an hour
per seed, and Docker needs about 6 GB free, so run one at a time.
