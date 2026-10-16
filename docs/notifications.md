# Notification coverage audit (FR-10)

Checked **16 Oct 2026** against `services/notification-agent/app/kafka/consumer.py`
(what is consumed), `app/services/routing.py` (urgent vs digest),
`app/templates/` (what is rendered), `app/services/directory.py` (who
receives it), and the live notification log (`GET /api/notifications/log`,
1,557 rows on the development stack).

"Sent today" means the event is consumed **and** an email is sent or
queued for the daily digest. Counts are from the development log, so they
reflect test traffic, not real usage.

## Lifecycle stage → event → who hears → template → sent today

| Stage | Event (producer) | Should hear | Template | Priority | Sent today | Log count | Item link |
|---|---|---|---|---|---|---|---|
| Document needs review | `document.classified` with `needs_review` (document-vendor) | Finance / reviewer | `document_classified` | digest | ✔ | 171 queued | ✘ |
| Bank details changed | `vendor.payment_details_flagged` (document-vendor) | Finance (urgent, fraud control) | `vendor_payment_details_flagged` | urgent | ✔ | 2 sent | ✘ |
| Request needs approval | `approval.requested` (approval-inventory) | The approver for the level | `approval_requested` | urgent | ✔ — **but to a placeholder address** (see gap 1) | 162 sent | ✔ portal + one-click action link |
| Request decided | `approval.decided` (approval-inventory) | Requester | `approval_decided` | urgent | ✔ | 156 sent | ✘ |
| Contract generated | `contract.generated` (contract-risk) | Requester | `contract_generated` | urgent | ✔ | 203 sent | ✘ |
| Contract waiting for a signature | — (`contract.generated` goes to the requester only) | The signer | — | — | ✘ (gap 4) | — | — |
| Contract signed → ordered | `contract.signed` (contract-risk) | Requester | `contract_signed` | urgent | ✔ | 87 sent | ✘ |
| Goods received | — (no event; `apply_received` only writes the audit log) | Requester, finance | — | — | ✘ (gap 5) | — | — |
| Invoice matched / held | `invoice.matched` (approval-inventory) | Finance (on a hold or mismatch) | — | — | ✘ not consumed (gap 3) | — | — |
| Renewal / notice deadline | `contract.renewal.due` (contract-risk) | Contract owner | `contract_renewal_due` | urgent at the configured alert levels, else digest | ✔ | 1 sent | ✘ |
| Something waiting too long | `reminder.due` (all three agents, FR-03) | `recipient_role` in the payload | — | — | ✘ **not consumed** although `events.md` lists notification-agent (gap 2) | — | payload has `link` |
| Vendor risk changed | `risk.score.updated` (contract-risk) | Risk / procurement team | `risk_score_updated` | urgent if High, else digest | ✔ | 2 sent + 132 queued | ✘ |
| Vendor offboarded | `vendor.offboarded` (contract-risk) | Procurement, contract owners | `vendor_offboarded` | urgent | ✔ | 3 sent | ✘ |
| Licence usage / reclaim | `license.usage.updated`; reclaim warnings via `notification.send` (approval-inventory) | Licence owner, admin | `license_usage_updated`, `generic_fallback` | digest; `notification.send` uses its `priority` | ✔ | 336 queued; 48 sent + 109 queued | ✘ |
| Daily digest | digest flush loop | Each recipient with queued items | `digest_summary` | — | ✔ | 145 sent | ✘ |
| Order status summary | `order.summary.generated` (approval-inventory, hourly) | Procurement (optional) | — | — | ✘ not consumed (fine: shown in the app / assistant) | — | — |
| Internal only | `document.ingested`, `vendor.matched`, `business_rule.updated` | nobody | — | — | n/a | — | — |

Delivery: `email_service.py` sends through `shared/mailer.py` since 11 Oct —
Mailpit with `EMAIL_MODE=dev`, any SMTP provider with `EMAIL_MODE=smtp`.
Failures are retried and dead-lettered since FR-31.

## Gaps — for Anooj (notification-agent / email automation is his)

1. **Approval emails reach a placeholder, not the approver.**
   `approval.requested` carries role names in `approval_chain`
   (`dept_manager`, `finance`…); `directory.as_email` turns them into
   `dept_manager@users.procurement.local` (158 such rows). Resolve the
   level to real people through `approver_assignments` (the approval
   authority table) and their account email.
2. **`reminder.due` is published but never emailed.** Add it to
   `CONSUME_TOPICS` (the ACL already allows it), a `reminder_due`
   template using `kind`, `detail`, `waiting_hours` and `link`, recipient
   from `recipient_role` via the same resolution as gap 1. FR-03's
   reminders only reach people once this exists.
3. **Invoice holds aren't announced.** Consume `invoice.matched` and email
   finance when the result is a hold or mismatch (not on clean matches).
4. **Nobody is asked to sign.** Either a `contract.sent_for_signature`
   event or using `contract.generated` with the signer as recipient.
5. **"Goods received" has no event.** Needs an event from
   approval-inventory-agent first (`order.received`), then a template —
   the producer side is ours, the email side is Anooj's.
6. **Only approval emails link to the item.** The other templates should
   include the item's page (`/app/requests/:id`, `/app/contracts/:id`,
   `/app/vendors/:id`, `/app/documents/:id`) built from `PUBLIC_BASE_URL`,
   as `approval_requested` already does.
7. **Default recipient** `procurement-ops@example.com` receives everything
   without a named person (753 rows) — fine for development, needs a real
   distribution list.
