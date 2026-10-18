# The 5-minute demo

For the presenter. One path through the system that shows every agent, the
human checks, and how it explains itself. The longer walkthroughs are
[showcase.html](showcase.html) (25 min) and
[demo-script.html](demo-script.html) (five scenarios, ~19 min).

`python tests/e2e/demo_5min.py` performs this exact path in a real browser,
checks every "you should see", and records it as
[demo/backup-recording.webm](demo/backup-recording.webm). Last rehearsed
18 Oct 2026: 6/6 steps, 35–42 s of clicking, so the rest of the time is
talking.

## Before the demo

| When | Do |
|---|---|
| The day before | `./scripts/reset-demo.sh --yes` (~3 min: backs up, clears the data, rebuilds realistic history), then `python tests/e2e/demo_5min.py`. All 6 steps should pass. |
| 30 min before | `./run.sh --no-build`. Open http://localhost:8080 in **two windows**: one signed in as `admin@demo.example.com`, one as `finance@demo.example.com` (password `DemoPass123!`). Open a terminal in the repo. |
| Have ready | A fresh quote under ₹500: `python tests/e2e/demo_5min.py --quote demo-quote.pdf` (new vendor and number each time; the sample quotes in `data/` are too large to auto-approve, and a re-used file is flagged as a duplicate). Also open the backup recording in a browser tab, paused. |
| Don't | Run the e2e test suites against the demo data: they create test vendors. If you do, run `reset-demo.sh` again. |

## The script

| Time | Who | Do | They see | Say |
|---|---|---|---|---|
| 0:00 | admin | Control Panel. In the terminal: `cp demo-quote.pdf inbox/`. | Within ~10 s a row in **Dropped files**: scanned, read, vendor created. | "Nobody clicked anything. The file was virus-scanned, read and classified, and a new vendor was created." |
| 1:00 | finance | Click the document. Scroll to **Extracted Fields**. If it says *Needs review*, scroll to **Extraction results**, then click **Confirm as Correct**. | Per-field confidence. Sometimes: the two extraction models disagree on the total (LayoutLMv3 reads the subtotal). | "When the models disagree, automation stops and a person decides. That's the point of the confidence gate." Then: "The request was created and auto-approved under ₹500, and the contract was sent." |
| 1:45 | finance | Contracts → the new contract → **Sign now**. Type a name, tick the consent, then **Sign & Execute Contract**. | Signed, with a SHA-256 seal and certificate; the request moves to *Ordered*. | "One human action from a dropped file to a signed contract." |
| 2:30 | finance | Vendors → **Rosoboronexport OJSC** → Sanctions Screening → **Screen now**. | *Potential match*, score 100, the sanctions lists named. | "Every vendor is screened against 25,000+ sanctioned companies. A match keeps the vendor High risk until finance writes down why it's a different company." |
| 3:15 | finance | Contracts → the **High**-risk signed contract → **Signature certificate**. | The certificate records risk band High and *acknowledged*. | "Nobody can sign with a High-risk vendor without acknowledging it, and the acknowledgement is part of the signed record." |
| 3:45 | admin | Control Panel → **Kafka log**, then **Failed events**. Then **Business Rules**. | Every event between the five agents; failed ones kept with their error; 47 rules. | "Nothing is hidden: every message between agents is logged, failures are kept, and every threshold is a rule you change live, with a justification and history." |
| 4:30 | n/a | Close. | n/a | Results: 828 service tests and 5 e2e suites passing; clause model F1 0.85 vs 0.50 for rules; licence anomaly ROC-AUC 0.95 ([results](results/README.md)). |

## If something breaks

Each fallback here was checked on 18 Oct 2026.

| What fails | What you see | Do |
|---|---|---|
| ClamAV not running | Upload/drop: *scanning unavailable, try again* (503). Nothing is stored unscanned. | Say "it fails closed, by design". `docker compose start clamav` is healthy again in ~15 s. Meanwhile show an existing document. |
| The dropped quote doesn't appear in 30 s | No row in Dropped files | `docker compose ps document-vendor-agent-worker`; skip to minute 1:45 using the draft contract from request **PR-22222222** (Acme IT Supplies). |
| Anything mid-demo, or no time | n/a | Play [demo/backup-recording.webm](demo/backup-recording.webm) (45 s, captioned) and talk over it. Stills for every module: [showcase.html](showcase.html). |
| The assistant (chat) doesn't answer | Ollama isn't running on the host | It isn't in the 5-minute path. `brew services start ollama`. |
| ML models not downloaded | Extraction and clause reading use the rule-based fallback, logged in System Health → Model Routing Log | Say so: the fallback is a feature (FR-08). `./scripts/download-models.sh` for next time. |
| No internet | Non-INR documents wait for an exchange rate (retried); sign-up's password check returns 503 | The demo uses INR and demo accounts, so it's unaffected. |
| Demo data looks wrong | Leftover test data, a failed step | `./scripts/reset-demo.sh --yes` (~3 min, backs up first). |
