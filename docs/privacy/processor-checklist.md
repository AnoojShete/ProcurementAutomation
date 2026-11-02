# Sub-Processor & Third-Party Evaluation Checklist

> **DRAFT - requires legal review**  
> **Purpose**: Standard Operating Procedure for onboarding and reviewing third-party data processors, sub-processors, and external API providers.

---

## 1. Sub-Processor Registry Requirement
Before any third-party software, cloud service, or API integration handles platform personal data, it must be registered in the platform database table `data_processors` and reviewed by security and compliance officers.

### Required Fields in `data_processors`:
- **`name`**: Legal corporate identity of the sub-processor.
- **`purpose`**: Specific processing operation (e.g. "Electronic signature sealing", "Outbound transactional email routing").
- **`country`**: Hosting jurisdiction of the processing servers.
- **`dpa_reference`**: Identifier or link to executed Data Processing Addendum / Standard Contractual Clauses (SCCs).
- **`transfer_mechanism_note`**: Legal basis for cross-border transfer (e.g., EU-US Data Privacy Framework, UK Addendum, SCC 2021/914).
- **`reviewed_on`**: Timestamp of annual security and compliance review.

---

## 2. Technical Evaluation Checklist

Each processor candidate must satisfy the following technical gates:

- [ ] **Transport Encryption**: Enforces TLS 1.2 or TLS 1.3 for all data in transit; refuses unencrypted connections.
- [ ] **Data at Rest Encryption**: Encrypts all stored data with AES-256 or equivalent standard.
- [ ] **Data Minimisation**: Accepts only required operational parameters; raw sensitive credentials (e.g. database credentials, bank passwords) are never transmitted.
- [ ] **Zero Marketing / Secondary Use**: Contractually prohibits using platform recipient emails for marketing, training general foundation models, or third-party syndication.
- [ ] **Incident Notification SLA**: Mandates notification of security incidents or data breaches within 48 hours of detection.
- [ ] **Sub-Processor Transparency**: Commits to maintaining a public list of downward sub-processors and providing 30 days prior notice of changes.
- [ ] **Automated Deletion & Return**: Provides programmatic API or contractual assurance to delete customer data within 30 days of contract termination.

---

## 3. Approved Sub-Processors Baseline

| Processor Name | Core Service Provided | Country / Region | Transfer Mechanism | Status |
|---|---|---|---|---|
| **Company Corporate SMTP** | Outbound operational email dispatch | Internal / On-Premise | Not Applicable (Internal Controller infrastructure) | **Approved** |
| **Documenso** | Electronic signature framework | Self-hosted / Germany (EU) | GDPR Article 28 DPA (Self-hosted on Docker network) | **Approved** |
| **Have I Been Pwned** | Breach dataset verification | Local Postgres replica | Offline SHA-256 database; no outbound data sent | **Approved** |
| **DocuSign Inc.** (Optional) | Cloud e-signature service | United States | EU-US Data Privacy Framework & EU Standard Contractual Clauses | **Conditional** (Requires active DPA) |
| **The Guardian Open Platform** | Adverse media risk check | United Kingdom | UK GDPR adequacy decision | **Approved** |
