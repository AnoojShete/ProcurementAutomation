# Introduction and objectives

## Introduction

Buying IT for a company (laptops, software licences, SaaS subscriptions)
passes through many hands. A vendor sends a quote, someone types it into a
request, approvers are chased by email, a contract is drafted and signed,
and the invoice is finally checked against the order by eye.

This platform automates that chain with five cooperating services ("agents").
They read the documents, route approvals, generate and sign contracts, score
vendor risk and email the people involved. People approve, sign, confirm
deliveries and review anything the system is unsure about.

## Objectives

1. **Read procurement documents automatically**: classify quotes, invoices and
   purchase orders, and extract their fields with a confidence for each.
2. **Route approvals with enforced authority**: spend tiers, approver
   assignments, separation of duties, SLAs with reminders and escalation.
3. **Generate contracts and collect e-signatures** from the approved data,
   and keep the signed copy.
4. **Check vendors before money moves**: duplicate and look-alike vendors,
   bank-detail changes, sanctions, risk scorecard.
5. **Keep people informed**: an email at every stage, from templates an
   admin can edit.
6. **Give administrators one place to run it**: the Control Panel.
7. **Audit everything**: every decision and status change is recorded.

## Existing system

In a typical company today:

- quotes and invoices arrive by email and are retyped into a spreadsheet or ERP;
- approvals happen over email or chat, with no record of who could approve what;
- contracts are copied from an old Word file, emailed for signature and
  saved somewhere on a shared drive;
- invoices are matched to orders by hand;
- nobody checks whether a vendor's bank account changed or the vendor is on a
  sanctions list until something goes wrong.

## Challenges

| Challenge | Why it is hard |
|---|---|
| Documents vary | PDFs, scans and photos, different layouts, OCR noise |
| Trusting automation | A wrong total or vendor must not slip through; the system has to know when it is unsure |
| Approval rules change | Thresholds and approvers differ per company and change over time |
| Many steps, many services | A failure in the middle must not lose a document or leave a request half-done |
| Fraud | Fake or duplicate invoices, changed bank details, look-alike vendors |
| Visibility | Administrators need to see where every document and contract is without opening five tools |
