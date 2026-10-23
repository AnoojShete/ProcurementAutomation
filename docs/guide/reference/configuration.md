# Configuration

Settings come from `.env` (created from `.env.example` on first run). The
demo defaults work without editing it.

| Setting | Default | Notes |
|---|---|---|
| `APP_ENV` | `development` (set by compose) | Unset means production: default secrets refused, no demo accounts, `EMAIL_MODE=dev` refused |
| `JWT_SECRET`, `ESIGN_WEBHOOK_SECRET`, `RULES_ENGINE_INTERNAL_SECRET`, `INTERNAL_SERVICE_TOKEN`, `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD`, `KAFKA_PASSWORD_*` | published dev values | Must be real secrets outside development |
| `EMAIL_MODE` | `dev` | `dev` = Mailpit (<http://localhost:8025>); `smtp` = real delivery with `SMTP_*` |
| `APP_BASE_URL`, `PUBLIC_BASE_URL` | `http://localhost:8080` | Used for links in emails; HTTPS in production |
| `EMAIL_INTAKE_*` | Mailpit POP3 | The mailbox documents are read from |
| `JWT_EXPIRY_MINUTES` / `JWT_REFRESH_EXPIRY_DAYS` | 15 / 7 | Session lifetimes |

## Business rules (no restart)

Thresholds and behaviour live in **Business Rules** (admin), not in code. Examples:

| Rule | Meaning |
|---|---|
| `approval.spend_tiers` | Spend tiers (auto ≤ ₹500, manager ≤ ₹5,000, then manager + finance) |
| `approval.sla_escalation_hours`, `approval.reminder_sla_percents` | Approval deadlines and reminders |
| `document.confidence_review_threshold` | Below this confidence a document goes to review (0.8) |
| `contract.signature_reminder_days` | When the signer is reminded |
| `contract.auto_send_scope` | Send every approved contract for signature, or only drop-folder ones |
| `document.image_preprocessing` | Deskew and upscale images before OCR |
| `license.anomaly_*` | Licence anomaly thresholds |

## Company SMTP server (no restart)

Admins set the company's own SMTP server under **Email Settings** (sidebar or
Control Panel → Email Settings; API `/api/smtp`). The password is stored
encrypted (AES-256-GCM) with a key derived from `SMTP_ENCRYPTION_SECRET`.
**Note:** compose doesn't pass that variable to notification-agent yet, so the
built-in default key is used; set it before any shared deployment.

## Notification templates (no restart)

Control Panel → Notifications. See [Control Panel](../control-panel.md#notification-templates).

## Drop folder

| Setting (document-vendor-agent) | Default |
|---|---|
| `inbox_enabled` | `true` |
| `inbox_dir` | `/inbox` (the host's `./inbox`) |
| `inbox_poll_seconds` | `3` |
