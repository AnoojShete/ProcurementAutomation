"""The drop folder (./inbox/input): put a quote PDF in it and the platform takes it
from there with no clicks —

    ./inbox/input/quote.pdf
      -> document-vendor-agent-worker picks it up (ClamAV scan, MinIO,
         document.ingested), runs the pipeline   -> document.classified
      -> approval-inventory-agent creates a purchase request from the quote
         (auto-approved under the spend threshold, else the usual approvers)
      -> contract-risk-agent generates the contract on approval.decided and
         sends it for e-signature once (DocuSign when configured)

Every service recognises a drop-folder document by its uploader, so a quote
uploaded by a person through the UI keeps its manual flow.
"""

# documents.uploaded_by / purchase_requests.requested_by for drop-folder items.
INBOX_UPLOADER = "inbox@procurement.local"
# documents.uploaded_by for documents taken from the intake mailbox (BR-1).
# Unlike the drop folder they keep the normal, reviewed flow.
EMAIL_INTAKE_UPLOADER = "email-intake@procurement.local"
