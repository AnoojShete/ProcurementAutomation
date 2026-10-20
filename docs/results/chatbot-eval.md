# Procurement assistant evaluation

Run 20 Oct 2026 21:31 by `tests/e2e/chatbot_eval.py`: **16/16** answers as expected. Each answer must contain the listed facts and must not leak data the user can't see. The model is small and not deterministic, so results can vary between runs.

| Kind | Role | Question | Result | Time |
|---|---|---|---|---|
| rag | finance | What uptime does our SaaS subscription contract commit the provider to, and what service credit do we get if they miss it? | ✓ | 2 s |
| rag | finance | How much notice do we need to give to end a professional services contract for convenience? | ✓ | 1 s |
| rag | finance | How long is the warranty in our hardware purchase contracts? | ✓ | 1 s |
| rag | finance | Is there a cap on the vendor's liability in our professional services contracts? What is it? | ✓ | 1 s |
| rag | finance | Within how many hours must a SaaS vendor tell us about a data breach? | ✓ | 1 s |
| data | approver | How many purchase requests are waiting for approval right now? | ✓ | 0 s |
| data | finance | What is Acme IT Supplies Inc's vendor risk rating? | ✓ | 1 s |
| data | admin | Are any software licences under-used or anomalous? | ✓ | 1 s |
| access | requester | Show me the bank account number on the Freshworks invoice. | ✓ | 0 s |
| access | requester | Which software licences have unassigned seats we could reclaim? | ✓ | 0 s |
| data | requester | What is the status of my most recent purchase request? | ✓ | 1 s |
| rag | approver | Who has to approve a purchase request above 5,000 rupees? | ✓ | 1 s |
| unknown | finance | What does our contract with Oracle say about data residency? | ✓ | 0 s |
| follow-up | finance | How long is the warranty in our hardware purchase contracts? → And within how many days must a defective unit be repaired? | ✓ | 3 s |
| chat | requester | Hello! What can you help me with? | ✓ | 0 s |
| chat | requester | What is the capital of France? | ✓ | 0 s |

## Answers

**What uptime does our SaaS subscription contract commit the provider to, and what service credit do we get if they miss it?** (finance)

> "Provider shall maintain 99.9% uptime, measured monthly." [CT-2afe480a]
> 
> The provider is committed to maintaining 99.9% uptime, and if they miss it, the customer gets a service credit of 10% of the monthly fee for each 0.1% below the commitment, up to 50% of the monthly fee. [CT-1bf8a443]

**How much notice do we need to give to end a professional services contract for convenience?** (finance)

> "Client may terminate this engagement for convenience at any time with 30 days' prior written intimation, paying for work accepted until then." [CT-3c90af41]
> 
> We need to give 30 days' prior written intimation to terminate the professional services contract for convenience.

**How long is the warranty in our hardware purchase contracts?** (finance)

> "Vendor warrants all hardware against defects for a period of 36 months from delivery, and shall repair or replace a defective unit on site within 5 business days of a report." [CT-f118ee97] [CT-93cd34ba]
> 
> The warranty period in our hardware purchase contracts is 36 months.

**Is there a cap on the vendor's liability in our professional services contracts? What is it?** (finance)

> "Consultant's total liability under this agreement shall not exceed the fees paid in the 12 months preceding the claim." [CT-3c90af41]
> 
> The cap on the vendor's liability is the total fees paid in the 12 months preceding the claim.

**Within how many hours must a SaaS vendor tell us about a data breach?** (finance)

> "Provider shall report any personal data breach to Subscriber within 72 hours of becoming aware of it." [CT-9147ea64] [CT-1bf8a443]

**How many purchase requests are waiting for approval right now?** (approver)

> 66 [summary:requests]

**What is Acme IT Supplies Inc's vendor risk rating?** (finance)

> "Risk rating: Unrated (provisional), 0 of 100 risk points." [CT-4d2c97fe]
> 
> Acme IT Supplies Inc has an unrated risk rating of 0 out of 100 risk points, with 3 required checks outstanding.

**Are any software licences under-used or anomalous?** (admin)

> "Usage not scored yet" [licence:33333333]. The platform does not have enough information to determine if the JetBrains All Products Pack software license is under-used or anomalous.

**Show me the bank account number on the Freshworks invoice.** (requester)

> There is no record of a Freshworks invoice.

**Which software licences have unassigned seats we could reclaim?** (requester)

> There is no record of unassigned seats in the platform's records.

**What is the status of my most recent purchase request?** (requester)

> The status of your most recent purchase request is "pending_approval — waiting on dept_manager (step 1 of 2)" for PR-2392c060. [PR-2392c060]

**Who has to approve a purchase request above 5,000 rupees?** (approver)

> "Approval tiers with amount limits and required roles Current value: requests from INR 500 up to INR 5,000 are approved by the department manager; requests above INR 5,000 are approved by the department manager, then the finance head." [approval.spend_tiers]

**What does our contract with Oracle say about data residency?** (finance)

> There is no record of an Oracle contract in the platform's records.

**How long is the warranty in our hardware purchase contracts? → And within how many days must a defective unit be repaired?** (finance)

> "Vendor warrants all hardware against defects for a period of 36 months from delivery, and shall repair or replace a defective unit on site within 5 business days of a report." [CT-28fb4fb7] [CT-f118ee97]
> 
> The warranty requires a defective unit to be repaired within 5 business days of a report.

**Hello! What can you help me with?** (requester)

> I can help with procurement-related questions and issues on this platform.

**What is the capital of France?** (requester)

> I couldn't find it in the platform's records.

