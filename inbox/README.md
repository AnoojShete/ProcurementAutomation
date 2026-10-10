# Drop folder

Put a vendor **quote** (PDF, PNG or JPEG) here. Within a few seconds the
document-vendor-agent worker picks it up and the rest happens on its own:

1. ClamAV scan → stored in MinIO → `document.ingested`
2. OCR / classification / vendor match → `document.classified`
3. A purchase request is created from the quote → `approval.requested`
   (auto-approved under the spend threshold, otherwise it waits for approvers)
4. On approval a contract is generated → `contract.generated`
5. The contract is sent for e-signature once (DocuSign when configured) —
   the signer gets one email
6. When the signer finishes, the contract is marked signed → `contract.signed`

Watch it on **Control Panel** (admin) in the app: the live Kafka log, each
dropped file's progress, and the MinIO / DocuSign connections.

Picked-up files move to `processed/`; rejected ones go to `failed/` with a
`.error.txt` saying why. Both folders are git-ignored.
