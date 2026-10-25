# Auth service and business rules

## 1. Introduction

**Business problem.** Every action must be tied to a real, verified person
with the right role, and the procurement rules (thresholds, SLAs) must
change without a release.

**Objectives.** Accounts with email verification, secure sessions, roles
(requester, approver, finance, admin), and a business-rules engine that
admins edit live.

| Input | Output |
|---|---|
| Sign-up, login, rule edits | JWT access tokens (15 min) + refresh cookie (7 days); rules served to every agent; `business_rule.updated` |

## 2. Technical implementation

| Part | Detail |
|---|---|
| Security | argon2id passwords, breached-password check (HaveIBeenPwned), lockout after 5 failures, single-use hashed email links, CSRF on refresh |
| Tables | `auth_users`, `auth_tokens`, `auth_revoked_refresh_tokens`, `business_rules`, `business_rule_history` |
| API | `/api/auth/*` (register, verify, login, refresh, logout, forgot/reset, users), `/api/admin/business-rules` |
| Migrations | Alembic (`alembic_version_auth_service`); each new rule is seeded by a migration and has a behaviour test |

## 3. Functional implementation

- Identity always comes from the JWT, never from a request body.
- Every agent reads rules through `shared/rules_engine` (5-minute cache,
  refreshed on `business_rule.updated`).
- A rule change records who changed it, when and why.

## 4. Results and evaluation

- 115 tests; `auth_flows.py` e2e 42/42 (sign-up, verify, reset, lockout, enumeration, rate limits).

![Business rules](../showcase/rules/01-business-rules.png)
