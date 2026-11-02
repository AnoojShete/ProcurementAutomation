# API Security Threat Model (OWASP API Security Top 10, 2023)

> **Document Status**: Active / Implemented  
> **Last Updated**: November 2026  
> **Applicable Scope**: Gateway (`nginx:8080`), `auth-service:8005`, `notification-agent:8004`, `document-vendor-agent:8001`, `approval-inventory-agent:8002`, `contract-risk-agent:8003`, and shared modules (`shared/`).

This threat model documents the concrete technical controls, architectural defenses, and verification test suites addressing the OWASP API Security Top 10 (2023) across the platform.

---

## OWASP API Security Top 10 Coverage Matrix

| OWASP Risk | Platform Vector & Impact | Technical Control Built | Verification Test | Status |
|---|---|---|---|---|
| **API1:2023 Broken Object Level Authorization (BOLA)** | Reading or tampering with another user's purchase requests, contracts, documents, or vendor risk evaluations by ID manipulation. | Central authorization policy engine (`shared/authz/policy.py`) with `can(user, action, resource)`. Every read/write endpoint validates ownership using authenticated user UUID (`user.id`), never email or caller-supplied claims. | `tests/test_api_security_owasp.py::test_bola_matrix_per_resource` | **Implemented** |
| **API2:2023 Broken Authentication** | Credential brute-forcing, token forging, algorithm downgrading ("none"), or refresh token replay attacks. | Strict JWT algorithm allow-list (`HS256`, explicit rejection of `"none"`), claim validation (`exp`, `nbf`, `iss`, `aud`, `kid`). Access token lifetime 15 minutes; refresh token 7 days with rotation and token family tracking (`auth_refresh_token_families`). Token family reuse immediately revokes all family sessions. Lockout after 5 wrong attempts per account/IP with non-enumerating identical error responses and timings. Step-up re-authentication (`reauth_at` claim within 5 min) for 6 high-risk operations. | `tests/test_api_security_owasp.py::test_jwt_attacks`, `tests/test_api_security_owasp.py::test_lockout_and_no_user_enumeration`, `tests/test_api_security_owasp.py::test_step_up_required_routes` | **Implemented** |
| **API3:2023 Broken Object Property Level Authorization** | Mass assignment attacks binding privileged fields (`role`, `status`, `user_id`, `approved_by`, `score`, `risk_band`) through client JSON payloads. | Pydantic request models configured with `model_config = ConfigDict(extra="forbid")`. Strict separation between input schemas and database/domain models. Sensitive fields are computed internally by business logic, never accepted from user payloads. Column sort and filter parameters use strict allow-lists. | `tests/test_api_security_owasp.py::test_mass_assignment_forbidden_properties`, `tests/test_api_security_owasp.py::test_sort_filter_allowlist` | **Implemented** |
| **API4:2023 Unrestricted Resource Consumption** | Slowloris attacks, unbounded file uploads, high-cost recomputations, database connection exhaustion, or memory exhaustion via deep JSON. | Gateway buffer and timeout caps (`client_header_timeout 10s`, `client_body_timeout 10s`, `keepalive_timeout 30s`, `client_max_body_size 1m` default, larger only on `/upload`). JSON body depth limit (max 10) and size limit. Distributed Redis token bucket rate limiting (`shared/security/rate_limiter.py`) per user/IP and endpoint category (anonymous, read, write, expensive, recompute) with hard minimums enforced via business rules. Capped pagination (max 100). | `tests/test_api_security_owasp.py::test_oversize_body_returns_413`, `tests/test_api_security_owasp.py::test_deep_json_depth_limit`, `tests/test_rate_limiter.py::test_rate_limit_bursts_and_retry_after` | **Implemented** |
| **API5:2023 Broken Function Level Authorization (BFLA)** | Non-admin users executing administrative functions (business rule editing, processing register exports, risk ruleset activation, internal endpoints). | Function-level dependency enforcement via `require_role("admin")`. Automated route inventory test verifying that all endpoints require authentication unless explicitly whitelisted. Gateway strictly blocks `/internal/*`, `/metrics`, `/docs`, `/openapi.json` with HTTP 404 outside development. | `tests/test_route_inventory_auth.py::test_route_inventory_auth_enforcement`, `tests/test_security_config.py::test_gateway_blocks_internal_metrics_docs` | **Implemented** |
| **API6:2023 Unrestricted Access to Sensitive Business Flows** | Automation of sensitive business flows: bulk approvals, vendor onboarding, email approval link spamming, payment detail manipulation. | Per-user daily velocity caps enforced via business rules (`security.sensitive_flow_daily_cap_*`). Velocity tracking generates automatic security alerts and potential account lockouts when a user exceeds 3x their standard historical velocity. | `tests/test_api_security_owasp.py::test_sensitive_flow_daily_caps_and_alerts` | **Implemented** |
| **API7:2023 Server-Side Request Forgery (SSRF)** | Outbound probes (vendor website, RDAP, DNS, webhooks, SMTP connection tests) reaching internal Docker containers, AWS/cloud metadata services (`169.254.169.254`), or private RFC 1918 subnets. | Dedicated outbound client (`shared/net/safe_http.py`) used for ALL external network requests. Resolves hostname to IP, checks IP against blocked ranges (loopback, private, link-local, cloud metadata, CGNAT, multicast, reserved), pins IP on the connection socket to defeat DNS rebinding, re-validates every redirect hop (max 2 redirects), and limits response size to 1 MB. | `tests/test_safe_http_ssrf.py::test_ssrf_all_scenarios` | **Implemented** |
| **API8:2023 Security Misconfiguration** | Missing HTTP security headers, permissive CORS wildcards, debug stack traces leaked to clients, default container execution as root. | Gateway enforces `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `frame-ancestors 'none'`, `Referrer-Policy: no-referrer`, strict CSP, and Permissions-Policy. CORS origin allow-list (never wildcard `*` with credentials). Standardized error JSON responses without stack traces. Sensitive secrets loaded from environment only. Session cookies use `HttpOnly`, `Secure`, and `SameSite=Lax`. | `tests/test_security_config.py::test_gateway_security_headers`, `tests/test_api_security_owasp.py::test_cors_preflight_and_headers` | **Implemented** |
| **API9:2023 Improper Inventory Management** | Unmanaged deprecated API versions, unprotected staging/demo endpoints exposed to the public internet, forgotten debug routes. | All endpoints grouped under versioned prefixes (`/api/v1` compatibility). Continuous route inventory test in CI scanning FastAPI app routers. Gateway denies any unmapped route with generic JSON 404. Demo endpoints (simulated signing, demo user accounts) strictly require `APP_ENV=development`. | `tests/test_route_inventory_auth.py::test_all_service_routes_inventoried`, `tests/test_security_config.py::test_demo_routes_disabled_in_prod` | **Implemented** |
| **API10:2023 Unsafe Consumption of APIs** | Blindly trusting responses from external services (e.g. GST portal, HIBP, Guardian news API, DocuSign/Documenso webhooks), leading to injection or logic flaws. | Schema validation on all third-party payloads before ingestion. All external fields treated as untrusted text. HTML and script tags stripped or plain-text escaped. Outbound webhook signatures verified using constant-time comparison (`hmac.compare_digest`) within 5-minute replay window, recorded in `processed_webhook_events`. | `tests/test_api_security_owasp.py::test_third_party_schema_validation`, `tests/test_api_security_owasp.py::test_webhook_signature_timestamp_and_replay` | **Implemented** |

---

## Technical Details of Core Defense Mechanisms

### 1. Central Policy Authorization (`shared/authz/policy.py`)
No service performs ad-hoc object level authorization. Every resource access delegates to `can(user, action, resource)`:
```python
can(current_user, Action.READ, purchase_request)
can(current_user, Action.APPROVE, purchase_request)
can(current_user, Action.WRITE, contract)
```
Ownership checks compare the authenticated user's ID against the resource's `requested_by_user_id` or `created_by_user_id`. Email addresses are never used for identity checks.

### 2. SSRF Protection Engine (`shared/net/safe_http.py`)
All HTTP requests to external destinations (vendor probes, website checks, email server validations) must use `safe_http_client`:
1. DNS resolution of host to IPv4/IPv6.
2. IP validation against blocked ranges:
   - `127.0.0.0/8`, `::1` (Loopback)
   - `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` (Private RFC 1918)
   - `169.254.0.0/16`, `fe80::/10` (Link-local & Cloud Metadata `169.254.169.254`)
   - `100.64.0.0/10` (Carrier-grade NAT)
   - `224.0.0.0/4`, `ff00::/8` (Multicast)
3. Connection is established directly to the verified, pinned IP address, preventing DNS rebinding between check and connect.
4. HTTP redirects are inspected and independently validated; maximum 2 redirects permitted.
5. Content length and streaming buffers enforce a maximum 1 MB response size.

### 3. Rate Limiting & Resource Protection
Token bucket algorithm implemented in Redis (`shared/security/rate_limiter.py`):
- `anonymous`: 30 requests / min / IP (minimum 10)
- `read`: 300 requests / min / user (minimum 50)
- `write`: 60 requests / min / user (minimum 10)
- `expensive` (bulk approvals, recomputation, export): 10 requests / min, max 2 concurrent per user
- `recompute`: 1 request / min / vendor
- Responses on breach: HTTP 429 with `Retry-After: <seconds>` and standard API error JSON envelope.

### 4. Logging & Log Redaction
The structured JSON log formatter (`shared/logging/formatter.py`) intercepts all log messages:
- Redacts authorization headers, Bearer tokens, JWT strings, and API secrets.
- Redacts password parameters (`password`, `current_password`, `new_password`).
- Redacts email action token paths (`/email-action/[REDACTED]`).
- Escapes carriage returns and newlines (`\r`, `\n`) to prevent log forging and injection.
