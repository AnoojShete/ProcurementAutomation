# Procurement assistant evaluation

Run 21 Oct 2026 07:09 by `tests/e2e/chatbot_eval.py`: **20/20** answers as expected. Each answer must contain the listed facts and must not leak data the user can't see. The model is small and not deterministic, so results can vary between runs.

| Kind | Role | Question | Result | Time |
|---|---|---|---|---|
| rag | finance | What uptime does our SaaS subscription contract commit the provider to, and what service credit do we get if they miss it? | ✓ | 1 s |
| rag | finance | How much notice do we need to give to end a professional services contract for convenience? | ✓ | 1 s |
| rag | finance | How long is the warranty in our hardware purchase contracts? | ✓ | 1 s |
| rag | finance | Is there a cap on the vendor's liability in our professional services contracts? What is it? | ✓ | 1 s |
| rag | finance | Within how many hours must a SaaS vendor tell us about a data breach? | ✓ | 1 s |
| data | approver | How many purchase requests are waiting for approval right now? | ✓ | 1 s |
| data | finance | What is Acme IT Supplies Inc's vendor risk rating? | ✓ | 1 s |
| data | admin | Are any software licences under-used or anomalous? | ✓ | 0 s |
| access | requester | Show me the bank account number on the Freshworks invoice. | ✓ | 1 s |
| access | requester | Which software licences have unassigned seats we could reclaim? | ✓ | 0 s |
| data | requester | What is the status of my most recent purchase request? | ✓ | 1 s |
| rag | approver | Who has to approve a purchase request above 5,000 rupees? | ✓ | 1 s |
| unknown | finance | What does our contract with Oracle say about data residency? | ✓ | 0 s |
| follow-up | finance | How long is the warranty in our hardware purchase contracts? → And within how many days must a defective unit be repaired? | ✓ | 1 s |
| chat | requester | Hello! What can you help me with? | ✓ | 0 s |
| chat | requester | What is the capital of France? | ✓ | 0 s |
| data | finance | Are there any SaaS license anomalies? | ✓ | 0 s |
| chat | requester | hi | ✓ | 0 s |
| follow-up | requester | hi → like what | ✓ | 0 s |
| chat | requester | sure procurement is easy like vendors | ✓ | 0 s |

## Answers

**What uptime does our SaaS subscription contract commit the provider to, and what service credit do we get if they miss it?** (finance)

> The provider is committed to maintaining 99.9% uptime, measured monthly. 
> If the provider misses this commitment, the user gets a service credit of 10% of the monthly fee for each 0.1% below the commitment, up to 50% of the monthly fee, against the next invoice. [CT-190cdd75]

**How much notice do we need to give to end a professional services contract for convenience?** (finance)

> "Client may terminate this engagement for convenience at any time with 30 days' prior written intimation, paying for work accepted until then." [CT-3c90af41]
> 
> To end a professional services contract for convenience, you need to give 30 days' prior written notice.

**How long is the warranty in our hardware purchase contracts?** (finance)

> The warranty period in our hardware purchase contracts is 36 months from delivery. "Vendor warrants all hardware against defects for a period of 36 months from delivery, and shall repair or replace a defective unit on site within 5 business days of a report." [CT-93cd34ba]

**Is there a cap on the vendor's liability in our professional services contracts? What is it?** (finance)

> The vendor's liability is capped at the fees paid in the 12 months preceding the claim. "Consultant's total liability under this agreement shall not exceed the fees paid in the 12 months preceding the claim." [CT-3c90af41]

**Within how many hours must a SaaS vendor tell us about a data breach?** (finance)

> "Provider shall report any personal data breach to Subscriber within 72 hours of becoming aware of it." [CT-9ab9e0b5] and [CT-190cdd75] 
> 
> According to the contract, a SaaS vendor must inform us about a data breach within 72 hours of becoming aware of it.

**How many purchase requests are waiting for approval right now?** (approver)

> 76 [summary:requests]
> 
> There are 76 purchase requests waiting for approval.

**What is Acme IT Supplies Inc's vendor risk rating?** (finance)

> "Risk rating: Unrated (provisional), 0 of 100 risk points." [vendor:11111111]
> 
> Acme IT Supplies Inc has an unrated risk rating of 0 out of 100, with 3 required checks outstanding.

**Are any software licences under-used or anomalous?** (admin)

> No: none of the 5 licences is anomalous right now (no score at or above 0.39). Closest to the line:
> - Docker Pro: score 0.32 (normal), 49 of 60 seats active in the last 30 days; main signal: users not coming back within a week
> - Notion Team: score 0.31 (normal), 89 of 200 seats active in the last 30 days; main signal: users not coming back within a week
> - Slack Enterprise: score 0.24 (normal), 35 of 63 seats active in the last 30 days; main signal: low use over 90 days
> 
> How it's detected: each licence's daily sign-ins from the SSO log are scored by an anomaly model (Isolation Forest) on utilisation, trend and retention; the main factors are explained per licence. A score of 0.39 or more is anomalous and 0.34 or more is on watch (business rules “Anomalous threshold” and “Watch threshold”).
> 
> What to do: nothing is needed now. Unassigned seats are still worth a look on the Licences page: Docker Pro (5 unassigned), JetBrains All Products Pack (10 unassigned), Microsoft 365 E3 (2 unassigned), Notion Team (20 unassigned), Slack Enterprise (19 unassigned).

**Show me the bank account number on the Freshworks invoice.** (requester)

> There is no record of a Freshworks invoice.

**Which software licences have unassigned seats we could reclaim?** (requester)

> Licence usage and anomalies are visible to approvers, finance and admins. I can help with your own purchase requests, vendors or contract terms instead.

**What is the status of my most recent purchase request?** (requester)

> The status of your most recent purchase request is "pending_approval — waiting on dept_manager (step 1 of 2)" for the Saas request, and "pending_approval — waiting on dept_manager (step 1 of 1)" for the Hardware requests. [PR-2392c060] [PR-6ad388c7] [PR-44c8812c]

**Who has to approve a purchase request above 5,000 rupees?** (approver)

> "Requests above INR 5,000 are approved by the department manager, then the finance head." [approval.spend_tiers]

**What does our contract with Oracle say about data residency?** (finance)

> There is no record of a contract with Oracle in the platform's records.

**How long is the warranty in our hardware purchase contracts? → And within how many days must a defective unit be repaired?** (finance)

> "Vendor warrants all hardware against defects for a period of 36 months from delivery, and shall repair or replace a defective unit on site within 5 business days of a report." [CT-f118ee97]

**Hello! What can you help me with?** (requester)

> I can look up your purchase requests, vendors and their risk, contract clauses and the platform's rules, and explain them in plain words with the record I used. I can't change anything: approvals, signing and edits happen on each item's page. Try:
> - What is the status of my most recent purchase request?
> - What is the risk rating of Acme IT Supplies Inc?
> - How much notice do we need to end a professional services contract?

**What is the capital of France?** (requester)

> I can help with procurement-related questions.

**Are there any SaaS license anomalies?** (finance)

> No: none of the 5 licences is anomalous right now (no score at or above 0.39). Closest to the line:
> - Docker Pro: score 0.32 (normal), 49 of 60 seats active in the last 30 days; main signal: users not coming back within a week
> - Notion Team: score 0.31 (normal), 89 of 200 seats active in the last 30 days; main signal: users not coming back within a week
> - Slack Enterprise: score 0.24 (normal), 35 of 63 seats active in the last 30 days; main signal: low use over 90 days
> 
> How it's detected: each licence's daily sign-ins from the SSO log are scored by an anomaly model (Isolation Forest) on utilisation, trend and retention; the main factors are explained per licence. A score of 0.39 or more is anomalous and 0.34 or more is on watch (business rules “Anomalous threshold” and “Watch threshold”).
> 
> What to do: nothing is needed now. Unassigned seats are still worth a look on the Licences page: Docker Pro (5 unassigned), JetBrains All Products Pack (10 unassigned), Microsoft 365 E3 (2 unassigned), Notion Team (20 unassigned), Slack Enterprise (19 unassigned).

**hi** (requester)

> Hi Anooj! I'm the procurement assistant. I answer from this platform's own records, for example:
> - What is the status of my most recent purchase request?
> - What is the risk rating of Acme IT Supplies Inc?
> - How much notice do we need to end a professional services contract?
> What would you like to know?

**hi → like what** (requester)

> Here are a few things you could ask:
> - Who is my latest request waiting on?
> - What uptime does our SaaS subscription contract promise?
> - Who has to approve a purchase above 5,000 rupees?
> - What is the licence anomaly threshold?

**sure procurement is easy like vendors** (requester)

> It can be! For vendors I can pull up the actual records here. You could ask:
> - What is the risk rating of Acme IT Supplies Inc?

