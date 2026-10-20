# Competitive analysis

Based on the 12 products in Scry AI, *Best Procurement Automation Software*
(https://scryai.com/blog/best-procurement-automation-software/), each checked on
the vendor's own pages where they could be fetched (20 October 2026). Vendor
pages are marketing material; accuracy and adoption figures quoted by vendors
are their claims, not verified.

## 1. Choosing the five competitors

Each product was scored on the eight capability areas our platform covers:
document capture and extraction, vendor verification and fraud controls,
invoice matching, requisitions and approvals, inventory, software licences,
contracts and renewals, supplier risk (1 = covered, ½ = partly, 0 = not stated).

| Product | Score | Why |
|---|---|---|
| **Coupa** | **7** | Every area except licences; 50+ AI agents |
| **Zapro** | **6** | AI intake, AP matching, inventory, contracts, licence tracking |
| **SAP Ariba** | **5.5** | Guided buying, contracts, AI supplier risk, smart OCR, fraud detection |
| **Ivalua** | **4.5** | Full source-to-pay; no AI stated |
| **TYASuite** | **4** | Indian P2P suite: AI invoice capture, GST/TDS, 3-way match |
| Collatio (Scry AI) | 3.5 | Document AI and six-way matching only; no purchasing workflow |
| Procurify | 3 | Requests, budgets, 2/3-way matching |
| ZYNO | 2.5 | SME requisitions, quotations, invoice matching |
| Precoro, Spendesk, MetaWMS | 1.5 | Purchasing/approvals, cards, or warehouse only |
| Rippling | 1 | Cards, expenses, bills |

The five competitors are **Coupa, Zapro, SAP Ariba, Ivalua and TYASuite**.
Collatio is not one of the five, but it is the closest to our document agent and
research (matching an invoice against several records), so it is discussed in
the research gap.

**Top competitor: Coupa.** It overlaps with the most areas (7 of 8), has the
most mature AI (invoice capture via Rossum, obligation extraction from
contracts, supplier-risk and sanctions agents) and adds budgets, sourcing,
catalogs, a supplier network and payments. **Zapro** is the closest peer in
size and scope: mid-market, AI intake, contracts with renewal alerts, inventory,
and the only other product that tracks software licences.

## 2. Comparison

✓ = offered · ◐ = partly · – = not stated in the sources reviewed

| Capability | **This platform** | Coupa | Zapro | SAP Ariba | Ivalua | TYASuite |
|---|---|---|---|---|---|---|
| AI document capture and extraction | ✓ pdfplumber, Docling, PaddleOCR; upload, e-mail, folder | ✓ Rossum-based capture | ✓ | ✓ smart OCR | ◐ AP automation | ✓ ZeroTouch |
| Document classification with per-field confidence and review | ✓ | – | – | – | – | – |
| Measured error rate of automatic acceptance | ✓ calibrated gate study | – | – | – | – | – |
| Invoice matching | ✓ line-level 3-way, payment hold | ✓ | ✓ 2/3-way | ✓ | ✓ | ✓ 3-way, multi-GRN |
| Duplicate and fraud checks | ✓ duplicates, look-alike vendors | ◐ risk sentinel | – | ✓ fraud detection | – | ✓ duplicate/tax checks |
| Bank-detail change needs a second person | ✓ | – | – | – | – | – |
| Requisitions and approvals | ✓ spend tiers, SoD, SLA escalation, e-mail approval | ✓ | ✓ | ✓ guided buying | ✓ | ✓ |
| Budget control | – | ✓ | ✓ | – | – | ✓ |
| Sourcing / RFQ, quote comparison | ◐ quotes read into requests | ✓ | ✓ | ✓ bid-analysis agent | ✓ | ✓ |
| Catalogs / punch-out | – | ✓ | ✓ Amazon Business | ✓ | ✓ | – |
| Supplier portal / network | – | ✓ | ◐ onboarding templates | ✓ Business Network | ◐ | ✓ |
| Inventory | ✓ reservation, backorder, reorder | ✓ | ✓ | – | ◐ receiving | ◐ GRN and QC |
| Software-licence usage | ✓ ML anomaly + explained reclaim | – | ◐ licence and renewal tracking | – | – | – |
| Contract lifecycle | ✓ templates, in-app e-sign, renewal reminders | ✓ | ◐ repository, renewal alerts | ✓ | ✓ | – |
| ML clause / obligation extraction | ✓ Legal-BERT, evaluated on CUAD | ✓ obligation agent | – | – | – | – |
| Supplier risk scoring | ✓ explainable model, overrides, drift check | ✓ risk agents | ◐ performance tracking | ✓ AI risk analysis | ◐ | – |
| Sanctions screening | ✓ | ✓ | – | – | – | – |
| Indian tax compliance | ◐ GSTIN check digit, IFSC | – | – | – | – | ✓ GST, 2B, TDS |
| Payments | – | ✓ Coupa Pay | ◐ payment-status sync | – | ✓ | ✓ |
| Spend analytics | ◐ spend by category | ✓ with benchmarks | ✓ | ◐ | – | ✓ reports |
| ERP integration | – | ✓ | ✓ | ✓ | ✓ | ✓ SAP, Oracle, Tally |
| Conversational AI / agents | ◐ read-only assistant | ✓ 50+ agents | ✓ prompt-to-buy, agents | ✓ Joule | – | – |
| Deployment | Self-hosted, open-source components | SaaS | SaaS | SaaS | SaaS | SaaS (AWS) |

## 3. What they have and we don't

| Gap | Who has it | Priority for us |
|---|---|---|
| ERP integration (SAP, Oracle, Tally, NetSuite) | all five | High for adoption; out of project scope |
| Budget control before approval | Coupa, Zapro, TYASuite | High: rules are seeded but not enforced |
| Supplier portal (self-onboarding, invoice upload, payment status) | Coupa, Ariba, TYASuite | Medium |
| Sourcing / RFQ events and quote comparison | all five | Medium: we already read quotes |
| Catalogs and punch-out buying | Coupa, Zapro, Ariba, Ivalua | Low for IT procurement pilots |
| Payment execution | Coupa, Ivalua, TYASuite | Out of scope by design |
| Indian GST compliance (2B reconciliation, TDS, e-invoice) | TYASuite | Medium: only GSTIN/IFSC validation today |
| Many task agents (buying, sourcing, contracts) | Coupa, Zapro, Ariba | Low: auditability first |
| Contract obligation tracking beyond renewal terms | Coupa | Medium: extend the Legal-BERT questions |
| Benchmarked spend analytics | Coupa, Zapro | Low |

## 4. What we have and they don't (per their public material)

- An **error rate for automatic acceptance**, measured and controlled: vendors
  quote extraction accuracy (Coupa 96 %, TYASuite 99 %), not how often a
  document accepted without review is wrong.
- **Licence-usage anomaly detection** with explanations and a grace period;
  Zapro tracks licences but describes no usage model.
- **Dual control of bank-detail changes** and **look-alike vendor** detection.
- **Evaluated** models (clause extraction against rules on CUAD, risk model
  against its ceiling) with published results.
- **Self-hosted**: documents never leave the organisation's machine.

Zoho Procurement (not in the Scry list) is also worth watching: India-built,
requisitions to goods receipt, RFQs, contract tracking and agentic AI, per
Zoho's own buyer's guide.

How the gaps would be closed, phase by phase: [feature-expansion-plan.md](feature-expansion-plan.md).

Sources: [Scry AI article](https://scryai.com/blog/best-procurement-automation-software/),
[Coupa Sept 2026 release](https://www.coupa.com/blog/agentic-enterprise-september-2026-release/),
[Coupa demo: budgets and inventory](https://coupa.com/demo/lp_all-demand-demo-procurement-invoicing-payments),
[SAP next-gen Ariba](https://www.sap.com/products/spend-management/smart-source-to-pay-procurement-software.html),
[Zapro](https://www.zapro.ai/), [TYASuite procurement](https://www.tyasuite.com/procurement-software),
[Collatio](https://scryai.com/collatio/),
[Zoho procurement buyer's guide](https://www.zoho.com/procurement/academy/procurement-software.html).
