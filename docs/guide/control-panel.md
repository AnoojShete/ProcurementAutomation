# Control Panel

The administrator's single place to run the platform: **sidebar → Control
Panel** (`/app/control-panel`, admin only). Each section is a tab; a deep
link opens one directly: `/app/control-panel?section=<key>`.

| Section (`key`) | What it shows | Routine tasks |
|---|---|---|
| Overview (`overview`) | Files in each folder, approvals and signatures waiting, failed events; drop folder, Kafka, MinIO and e-signature status | See at a glance what needs attention; click a figure to open its section |
| Documents (`documents`) | **Input / Being read / Processed / Failed** folder counts; each dropped file's stage; every failure reason | Follow a document to its request and contract; see why a file failed |
| Processing and logs (`processing`) | Live Kafka event log (filter by topic, time, text, correlation id); failed events (dead-letter queue) with the error | Trace one document across services; spot stuck consumers |
| Approvals (`approvals`) | Every request waiting for a decision, with its spend tier and SLA countdown | Open a request at its Approval step to decide |
| Notifications (`notifications`) | Every email template; recent notifications with status | **Create, edit, preview, turn off or restore** a template; add copy recipients |
| Contracts and e-signatures (`esign`) | Every contract with **Unsigned contract PDF / Signed contract PDF** links and **Pending E-Signature / E-Signature Complete** status | Download either PDF; open a contract to sign or send it |
| Email Settings (`email`) | Company SMTP server (password stored encrypted) | Set up and test sending from your own domain |
| Storage (`storage`) | MinIO bucket, object count, latest files | Check storage without the MinIO console |
| Administration (`admin`) | Links to System Health, Users, Controls, Business Rules, Audit | Manage users, rules and authority |

![Control Panel overview](showcase/cpanel/01-overview.png)

## Document lifecycle (folders)

```
./inbox/input/       drop files here
./inbox/.processing/ being uploaded, then held while the pipeline reads the file
./inbox/processed/   read successfully
./inbox/failed/      rejected or failed; <file>.error.txt holds file, time, document id and reason
```

A file is moved only when the pipeline has finished, so a scan that turns
out to be blank ends in `failed/`, not `processed/`.

![Documents section](showcase/cpanel/02-documents.png)

## E-signature tracking

| Document | Status |
|---|---|
| Unsigned contract PDF | Pending E-Signature |
| Signed contract PDF | E-Signature Complete |

Both PDFs are fetched through the app with the admin's own session, so no
one needs MinIO or an e-signature provider's site. The signed copy appears as
soon as the contract is signed.

![E-signatures section](showcase/cpanel/05-esignatures.png)

## Notification templates

1. Pick a template on the left (it shows the event that sends it and who receives it).
2. Edit the subject and body; click a placeholder to insert it (`{{ request_id }}`).
3. Optionally add copy recipients, or untick **Send this email**.
4. **Preview** shows it with sample values; **Save** applies it to the next email.
5. **Restore default** brings the built-in text back; **New** creates a template
   that services send by name.

![Template editor](showcase/cpanel/04-templates.png)
