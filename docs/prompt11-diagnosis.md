# Prompt 11 Diagnosis Report

## Vendor Under Test
- **Vendor ID**: `e4b1673e-3b1c-4fdc-82d3-fa86c90feba5`
- **Legal Name**: `3Five8 Technologies Pvt. Ltd`
- **Country**: `IN`
- **GSTIN**: `29AAACZ3829K1ZT`
- **Website**: `adda.io`
- **Contact Email**: `support@adda.io`
- **Inherent Tier**: `Critical` (DB currently recorded as `moderate`)
- **Bank Details**: Not yet verified (`NONE`)

---

## 1. Latest Risk Score Dump (`risk_scores`)
- **Score ID**: `8e9d320e-92b0-474a-9406-b0f12834022c`
- **Scored At**: `2026-10-27 16:02:48.595309+00`
- **Total Points**: `0` / 100
- **Final Band**: `Unrated`
- **Rating Status**: `provisional`
- **Headline**: `Unrated - 0 points found so far, 4 required checks outstanding`

### Every Rule Result (`risk_score_rule_results`)
| order | signal_key | rule_id | status | points | reason_text |
|---|---|---|---|---|---|
| 0 | sanctions | R-SAN-04 | not_assessed | 0 | Not screened: —. |
| 1 | gst | R-GST-08 | not_assessed | 0 | GSTIN verification incomplete or missing domestic GSTIN (unknown). |
| 2 | bank | R-BNK-06 | not_assessed | 0 | Bank details not verified against directory. |
| 3 | jurisdiction | R-JUR-06 | assessed | 0 | Domestic vendor (India). |
| 4 | web | R-WEB-06 | assessed | 0 | SSL Labs grade A with valid certificate (Issuer: Amazon RSA 2048 M01, 47 days left). |
| 5 | email | R-EML-02 | assessed | 0 | DMARC policy is reject and valid SPF record is present. |
| 6 | breach | R-BRC-08 | not_assessed | 0 | Breach screening not available. |
| 7 | certification | R-CRT-01 | not_applicable | 0 | not required for this vendor's tier. |
| 8 | financial | R-FIN-07 | not_assessed | 0 | No financial documentation on file or evidence is older than 365 days. |
| 9 | company_age | R-AGE-04 | not_assessed | 0 | only the domain age is known; a registration or incorporation date is needed. |
| 10 | delivery_sla | R-SLA-06 | not_assessed | 0 | Insufficient order delivery data. |
| 11 | feedback | R-FBK-06 | not_assessed | 0 | Internal feedback ratings unavailable. |
| 12 | incidents | R-INC-05 | not_assessed | 0 | Incident history not yet evaluated. |
| 13 | adverse_media | R-MED-05 | assessed_no_finding | 0 | No adverse media found across screened publications (limited coverage note). |

---

## 2. Observations Dump (`vendor_signal_observations`)
| signal_key | status | skip_reason | fields | facts |
|---|---|---|---|---|
| sanctions | not_checked | null | `{"sanctions.status": "not_screened", "sanctions.best_score": 0.0, "sanctions.match_type": "unreachable", "sanctions.list_name": "Consolidated Sanctions List", "sanctions.list_version": "v1", "sanctions.matched_name": "None", "sanctions.review_threshold": 70, "sanctions.match_threshold": 85}` | Source: OpenSanctions, Status: Not Screened, Screened name: 3Five8 Technologies Pvt. Ltd |
| gst | ok | null | `{"gstin.number": "29AAACZ3829K1ZT", "gstin.status": "unknown", "gstin.verification_level": "offline_only", "gstin.provider_status_raw": "format_valid", "gstin.not_checked_reason": "No verification performed"}` | Source: internal, HTTP status: 200, GSTIN: 29AAACZ3829K1ZT, Verification level: offline_only |
| bank | not_checked | null | `{"bank.ifsc": "NONE", "bank.status": "none", "bank.change_pending": false}` | Source: Razorpay IFSC Directory, Status: None |
| jurisdiction | ok | null | `{"country.code": "IN", "country.is_domestic": true, "country.prohibited": false, "country.wgi_composite": 0.85}` | Country Code: IN, Prohibited: No |
| web | ok | null | `{"web.reachable": true, "web.ssl_grade": "A", "web.cert_valid": true, "web.hsts": true, "web.cert_issuer": "Amazon RSA 2048 M01", "web.cert_days_left": 47, "web.confidence": "live"}` | TLS Version: TLSv1.3, SSL Labs Grade: A, TLS Certificate: Valid, HSTS: Yes |
| email | ok | null | `{"email.has_mx": true, "email.dmarc_policy": "reject", "email.spf_present": true, "email.confidence": "live"}` | DMARC Policy: REJECT, SPF: Present, MX: Present |
| breach | not_checked | no_live_source | `{"breach.domain": "adda.io", "breach.source_reachable": false}` | Source: Have I Been Pwned (HIBP), Status: not_checked, Domain: adda.io |
| certification | ok | null | `{"cert.required": false, "cert.status": "none", "cert.name": "SOC 2 Type II / ISO 27001", "cert.expires_on": "—"}` | Required for tier: No, Status: None |
| adverse_media | ok | null | `{"media.sources_reachable": true, "media.qualifying_articles": 0, "media.headlines": []}` | Sources reachable: Yes, Qualifying articles: 0 |

---

## 3. Raw Responses Dump (`vendor_signal_raw_responses`)
| signal_key | provider | status | body_prefix (first 500 chars) |
|---|---|---|---|
| breach | Have I Been Pwned (HIBP) | null | `{"detail":"No live breach lookup in this deployment; verify any reported breach and its entity match by hand.","domain":"adda.io","skip_reason":"no_live_source"}` |
| gst | internal | 200 | `{"attestation":null,"country":"IN","gstin":"29AAACZ3829K1ZT","raw_response":{},"status":"unknown","verification_level":"offline_only"}` |
| sanctions | OpenSanctions | 200 | `{"list_name":"Consolidated Sanctions List","list_version":"v1","match_count":0,"match_threshold":85,"matches":[],"review_threshold":70,"screened_bank":"","screened_bic":"","screened_name":"3Five8 Technologies Pvt. Ltd"}` |
| web | SSL Labs / TLS Probe | 200 | `{"web.cert_days_left":47,"web.cert_issuer":"Amazon RSA 2048 M01","web.cert_problem":"None","web.cert_valid":true,"web.confidence":"live","web.hsts":true,"web.reachable":true,"web.ssl_grade":"A"}` |
| certification | Evidence Register | 200 | `{"cert.expires_on":"—","cert.name":"SOC 2 Type II / ISO 27001","cert.required":false,"cert.status":"none"}` |
| adverse_media | The Guardian / Open Media Feed | 200 | `{"cleared_urls":[],"extraction":{"discarded_not_vendor":0,"discarded_too_old":0,"lexicon_version":"1.0","matched_keywords":"***","retrieved_count":0},"headlines":[]}` |

---

## 4. Diagnosis Answers With Evidence

### a) Breach
- **Did the collector run?** Yes, `collect_breach` ran and recorded a row in `vendor_signal_observations`.
- **Which domain did it use?** It derived `domain = "adda.io"` from `vendor.website`.
- **What HTTP status did the breach source return?** None (`null`). No HTTP request was made. `collect_breach` hardcoded `request_method="NONE"` and stored `skip_reason="no_live_source"`.
- **Live curl from inside container**:
  ```bash
  curl -s -i -A "ProcurementIntelligence/1.0 (academic project; contact admin@procure.internal)" https://haveibeenpwned.com/api/v3/breaches
  ```
  **Result**: `HTTP/2 200`, content-type `application/json`, content-length `1129282` bytes. Body prefix:
  `[{"Name":"000webhost","Title":"000webhost","Domain":"000webhost.com","BreachDate":"2015-03-01",...`
- **Real cause**: A **code path that never runs** (no live lookup logic implemented in `collect_breach`; it is a stub). It is NOT a block (403), rate limit (429), empty domain, or deadline.

### b) GST
- **Was a live lookup attempted?** No. `data_source` defaulted to `"offline"`, so the live branch (`if live_enabled and country == "IN" and data_source == "real":`) was skipped.
- **Does any code compare entered vendor name with registry legal name?** No. Zero code compares names or computes similarity.
- **Is there a demo or fallback path returning "active" without a lookup?** Yes. Lines 308–309 in `identity_collectors.py` previously had:
  ```python
  if v_status in ("active", "valid"):
      fields["gstin.status"] = "active"
  ```
  which returns `active` whenever a database status field is pre-set, without any live verification.

### c) Sanctions
- **Is a list loaded, and was screening run?** No list was loaded on disk (`sanctions.load_index()` returned `None`). Screening was evaluated against an empty/missing index, resulting in `sanctions.status = "not_screened"`.
- **Why does the text say "Not screened: —" with an empty reason?**
  In `engine.py` (line 163):
  ```python
  if o_fetched_at and obs_status not in ("not_assessed", "error", "not_checked"):
  ```
  Because `obs_status` was `"not_checked"`, `engine.py` set `is_fresh = False` and wiped `obs_fields = {}`!
  When R-SAN-04 evaluated template `Not screened: {sanctions.status}.`, `{sanctions.status}` was not found in the empty dictionary, and `render_template` defaulted the missing key to `"—"`, resulting in `Not screened: —.`.

### d) Certification "not required" for Critical Tier
- In `collect_certification(db, vendor, now, effective_tier: str = "standard")`:
  The caller in `risk_service.py` called `collect_certification` without passing `effective_tier`. Thus it defaulted to `"standard"`.
  Since `"standard"` is not in `("high", "critical")`, `required` evaluated to `False` (`cert.required: false`), firing rule R-CRT-01 (`not_applicable`, "not required for this vendor's tier").

### e) Letter grade shown as "SSL Labs grade A"
- Produced by `collect_web` in `cyber_collectors.py`.
- **Does it call SSL Labs or compute the letter itself?** It **computes the letter itself** using a local heuristic based on TLS version (1.3/1.2) and HSTS header. It never calls SSL Labs, but falsely outputs `"SSL Labs Grade"` as the fact label and stores `web.ssl_grade = "A"`.

### f) Which placeholder printed "—" and which collector failed to supply it?
- The placeholder was `{sanctions.status}` in rule `R-SAN-04`.
- The collector `collect_sanctions` DID supply `"sanctions.status": "not_screened"`, but **`engine.py` discarded all fields** because `obs_status == "not_checked"`.
