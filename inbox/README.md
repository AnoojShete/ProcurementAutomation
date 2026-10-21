# Drop folder

Three folders:

| Folder | What it holds |
|---|---|
| `input/` | Drop a vendor **quote** (PDF, PNG or JPEG) here |
| `processed/` | Files the pipeline read successfully |
| `failed/` | Files that were rejected or failed, each with a `.error.txt` (file, time, document id, reason) |

Within a few seconds the document-vendor-agent worker picks a file up from
`input/` and the rest happens on its own:

1. ClamAV scan → stored in MinIO → `document.ingested` (Kafka)
2. OCR / classification / field extraction / vendor match → `document.classified`
3. The file moves to `processed/` (or to `failed/` if the pipeline failed)
4. A purchase request is created from the quote → `approval.requested`
   (auto-approved under the spend threshold, otherwise it waits for approvers)
5. On approval a contract is generated → `contract.generated`
6. The contract is sent for e-signature; the signer gets an email
7. When the signer finishes, the contract is marked signed → `contract.signed`

While a file is being uploaded or read it sits in the hidden `.processing/`
folder. Files dropped straight into `./inbox` are moved to `input/` when the
worker starts.

Watch it on **Control Panel → Documents** (admin) in the app: each folder's
count, each dropped file's stage, failure reasons, and the live Kafka log.
