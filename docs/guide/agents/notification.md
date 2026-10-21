# Notification agent

## 1. Introduction

**Business problem.** People miss approvals and signatures because nobody
tells them; when they are told, the message text is buried in code.

**Objectives.** Email the right person at every stage (users, approvers,
signers, vendors), urgently or in a daily digest, from templates an
administrator edits in the Control Panel; keep a log and an in-app feed.

| Input | Output |
|---|---|
| 17 Kafka topics (approvals, contracts, reminders, budgets, RFQs, deliveries…) | Emails (Mailpit in development, SMTP in production), `notification_log`, the in-app feed and bell |

## 2. Technical implementation

| Part | Detail |
|---|---|
| Components | Kafka consumer (`app/kafka/consumer.py`), dispatcher (urgent vs digest), template store (`services/template_store.py`), directory (who receives), digest loop |
| Templates | Built-in Jinja2 files `app/templates/*.j2`; overrides and new templates in `notification_templates`, rendered in Jinja's sandbox |
| API | `/api/notifications/log`, `/feed`, `/unread-count`, `/read-all`; admin: `/api/notifications/templates` (list, get, create, edit, reset, preview) |
| Deployment | One container; reads other services' tables read-only to resolve recipients |

## 3. Functional implementation

| Stage | Who is emailed |
|---|---|
| Approval needed (each level) | The people assigned to that approval level |
| SLA reminder | The approvers of the waiting level (signer, finance or reviewers for other reminders) |
| Approval outcome | The requester |
| Contract sent for signature | The signer, with a signing link |
| Contract generated / signed | The requester; the vendor's contact when signed |
| Budget, obligation, RFQ, delivery, risk, offboarding | Budget owner, obligation owner, vendors, requester, procurement |

**Templates without code changes.** An admin edits subject, body, extra
recipients (copies) and on/off for any email, or creates a new template. A
save is checked first: the text must parse, and a built-in may only use the
placeholders its event carries. If an edited template still fails when
sending, the built-in is used, so an email is never lost. A template turned
off is logged as *skipped*.

## 4. Results and evaluation

- 116 tests: every template renders with its event's documented payload,
  recipients per event, editing and sandboxing, digest routing.
- Live check: an edited template with an extra recipient was received by both
  addresses in Mailpit; restoring the default brought the built-in back.

![Template editor](../showcase/cpanel/04-templates.png)

**Limitations.** Role mailboxes without an assigned person fall back to
placeholder addresses (`dept_manager@users.procurement.local`); production needs
real distribution lists.
