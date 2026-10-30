# Contract & Risk agent

## 1. Introduction

**Business problem.** Contracts are copied from old files, emailed for
signature and lost on shared drives; deadlines to cancel renewals are
missed; nobody checks the vendor before signing.

**Objectives.** Generate the contract from the approved request, send it for
e-signature, track signing and keep the signed copy, remind before notice
deadlines, and decide whether a vendor may be signed at all.

| Input | Output |
|---|---|
| `approval.decided` (final level) | A contract (text + PDF), sent for signature; `contract.generated`, `contract.signed`; signed PDF and signature certificate; vendor risk score and clearance |

## 2. Technical implementation

| Part | Detail |
|---|---|
| Components | Contract service (Jinja2 templates → text → PDF), built-in e-sign, clause router, renewal workflow (Temporal), risk scorecard and collectors, clearance (`services/clearance.py`) |
| AI models | Legal-BERT fine-tuned on CUAD (clauses and obligations), regex rules as fallback |
| Tables | `contracts`, `contract_obligations`, `sla_credits`, `risk_scores`, `risk_rulesets`, `vendor_decisions`, `vendor_evidence`, `vendor_sanctions_screenings`, `signing_mandates` |
| API | `/api/contracts` (list, detail, generate, send-for-signature, sign, document, signed-document, signature-certificate, esign/documents), `/api/vendors/{id}/risk`, `/clearance`, `/api/webhooks/esign`, `/api/mandates` (template, active, create, revoke, recent-auto-signed) |
| Communication | Consumes `approval.decided`, `document.classified`; publishes `contract.generated`, `contract.signed`, `risk.score.updated`, `contract.obligation.due`, `notification.send` (signer email), `reminder.due` |
| Deployment | API + Temporal worker; sanctions list in a volume (`./scripts/download-sanctions.sh`) |

## 3. Functional implementation

1. **Generate** only after the **final** approval level (a manager's approval of a
   manager + finance request waits for finance).
2. **Send for signature** automatically (rule `contract.auto_send_scope`): the
   signer, an authorised signatory, gets an email with a signing link.
3. **Clearance before signing**: a sanctions match or prohibited country blocks
   signing outright. A vendor that isn't cleared (High band, a provisional
   rating because checks are incomplete, or a reviewer's rejection) needs the
   signer's explicit acknowledgement.
   Every vendor gets a band. The scorecard has 14 parameters out of 100
   points. A check our side couldn't run is left out and the rest re-weighted;
   missing information about the vendor itself (no GSTIN, registration,
   financials, bank details or domain) counts in full, and a vendor with no
   verified identity is High. A provisional rating is never cleared.
4. **Sign**: typed or drawn signature, consent, SHA-256 seal of the contract and
   signer; the request moves to *ordered*; the requester and vendor are emailed.
   **Signing mandate** (off by default, rule `contract.auto_sign_enabled`): a
   finance user can accept a revocable mandate (password re-entry, at most 90
   days, a maximum amount per contract). When they give the final approval in
   bulk or from email, small contracts with a vendor that isn't blocked are
   signed straight away, and the certificate names the mandate and batch. An
   internal authorisation record, not a legally recognised e-signature.
   Not finished: the password re-check and the bulk path for vendor-linked
   requests (see the Overview's Needs attention list).
5. **Track**: the Control Panel lists every contract as *Pending E-Signature* or
   *E-Signature Complete* with its unsigned and signed PDFs; a reminder goes to
   the signer after 3 days.
6. **After signing**: clauses and obligations extracted; renewal reminders
   counted back from the notice deadline.

## 4. Results and evaluation

| Measure | Result | Source |
|---|---|---|
| Clause extraction on 102 CUAD contracts | F1 0.85 / 0.80 / 0.91 (renewal, notice, expiry) vs rules 0.50 / 0.19 / 0.02 | `docs/results/clauses.md` |
| Risk ruleset vs old random forest | ROC-AUC 0.738 vs 0.715; 29 red-team profiles all handled | `docs/index.html#risk` |
| Tests | 400 unit/integration tests; `risk_flow.py` 49/49; `obligation_flow.py` | `scripts/test-service.sh` |

![Contract with vendor risk before signing](../showcase/contract/01-contract-risk.png)

**Limitations.** The built-in seal is an unkeyed hash (tamper-evident only as
far as the audit log is trusted); a legally recognised provider is a future step.
