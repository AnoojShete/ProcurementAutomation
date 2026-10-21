# Screens (mockups)

Screenshots of the running application, taken by
`python tests/e2e/showcase_screens.py` from the live stack (so they match
the implemented system, not a design mock-up).

## Control Panel

![Control Panel overview: figures and connection status](../showcase/cpanel/01-overview.png)
*Figure 3. Control Panel → Overview: what is in each folder, waiting for approval
or signature, failed; and the state of the drop folder, Kafka, MinIO and e-signature.*

![Control Panel documents: Input, Processed and Failed folders with each dropped file's stage](../showcase/cpanel/02-documents.png)
*Figure 4. Control Panel → Documents: the three folders, each dropped file's stage and every failure reason.*

![Notification template editor with subject, body, placeholders and recipients](../showcase/cpanel/04-templates.png)
*Figure 5. Control Panel → Notifications: editing an email template without a code change.*

![Contracts and e-signatures: unsigned and signed PDFs with their status](../showcase/cpanel/05-esignatures.png)
*Figure 6. Control Panel → Contracts and e-signatures: Pending E-Signature / E-Signature Complete with PDF links.*

## Documents

![Document page: every extracted field with confidence, and the validation result of each pipeline stage](../showcase/cpanel/06-extraction.png)
*Figure 7. A document's extracted fields, confidence per field and validation results per stage.*

![Documents list during processing](../showcase/intake/03-processing.png)
*Figure 8. Documents being read, with live progress.*

## Approvals and contracts

![Approval queue](../showcase/approval/01-approval-queue.png)
*Figure 9. Approval inbox for an approver.*

![Request lifecycle with clickable steps](../showcase/approval/02-request-lifecycle.png)
*Figure 10. A request's lifecycle: approval, contract, signature, delivery, invoice.*

![Contract page with the vendor's risk shown before signing](../showcase/contract/01-contract-risk.png)
*Figure 11. Contract page: the vendor's risk is shown before signing.*

## Operations

![Kafka event log in the Control Panel](../showcase/reliability/01-kafka-log.png)
*Figure 12. Control Panel → Processing and logs: every Kafka event, searchable.*

![Business rules editor](../showcase/rules/01-business-rules.png)
*Figure 13. Business rules, edited live with history.*
