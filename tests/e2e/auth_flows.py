"""Account flows end to end, through the nginx gateway, with real emails
read back from Mailpit: sign up → confirmation email → confirm → log in →
change password → log out → forgot password → reset email → reset → log in.
Plus: expired and reused links, lockout after wrong passwords, generic
answers for unknown addresses, gateway rate limit on email endpoints.

Checks the emails themselves (From, Reply-To, text + HTML parts, a link that
opens the app) and the database (argon2id hash, no plain text, token stored
only as a hash).

Needs the stack running with EMAIL_MODE=dev (the default). Uses fresh
addresses each run and deletes its test accounts at the end.
    python tests/e2e/auth_flows.py
Requires: requests.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid

import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GATEWAY = os.getenv("GATEWAY", "http://localhost:8080")
API = GATEWAY + "/api"
MAILPIT = os.getenv("MAILPIT", "http://localhost:8025")
RUN = uuid.uuid4().hex[:8]
PASSWORD = f"orange piano {RUN} lighthouse"
NEW_PASSWORD = f"seven quiet {RUN} rivers flow"

results = []


def check(name, condition, detail=""):
    results.append(bool(condition))
    print(f"  {'✓' if condition else '✗'} {name}" + ("" if condition or not detail else f"  — {detail}"))
    return condition


def step(title):
    print(f"\n── {title}")


def sql(query):
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", os.getenv("POSTGRES_USER", "postgres"),
         "-tAF|", "-c", query], cwd=ROOT, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def address(tag):
    return f"e2e-auth-{RUN}-{tag}@example.com"


def wait_for_mail(to, subject_part, after=0.0, timeout=20):
    """Newest message to `to` whose subject contains subject_part, received
    after `after` (epoch seconds)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = requests.get(f"{MAILPIT}/api/v1/search", params={"query": f'to:"{to}"', "limit": 20}).json()
        for m in found.get("messages", []):
            received = time.mktime(time.strptime(m["Created"][:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
            if subject_part.lower() in m["Subject"].lower() and received >= after - 2:
                return requests.get(f"{MAILPIT}/api/v1/message/{m['ID']}").json()
        time.sleep(0.5)
    return None


def link_token(message, path):
    match = re.search(re.escape(GATEWAY) + re.escape(path) + r"#token=([A-Za-z0-9_-]+)", message["Text"])
    return match.group(1) if match else None


def count_mail(to):
    return requests.get(f"{MAILPIT}/api/v1/search", params={"query": f'to:"{to}"'}).json().get("messages_count", 0)


def post(session, path, body, gateway_retry=True, **kw):
    """POST through the gateway. This script makes far more auth requests
    per minute than a person would, so it waits out the gateway's per-IP
    limit (code "rate_limited"); the limit itself is checked at the end.
    auth-service's own lockout (code "account_locked") is returned as is."""
    for _ in range(30):
        r = session.post(f"{API}{path}", json=body, **kw)
        if not (gateway_retry and r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"):
            return r
        time.sleep(2)
    return r


def csrf(session):
    return {"X-CSRF-Token": session.cookies.get("csrf_token", path="/")}


def main():
    s = requests.Session()
    email = address("main")

    step("Sign up")
    t0 = time.time()
    r = post(s, "/auth/register", {"email": email.upper(), "password": PASSWORD})
    check("sign-up accepted (202, generic message)", r.status_code == 202 and "inbox" in r.json()["data"]["message"], r.text)
    row = sql(f"SELECT email, hashed_password, email_verified_at IS NULL, role FROM auth_users WHERE email = '{email}'")
    stored_email, hashed, unverified, role = row.split("|")
    check("stored lower-case, role requester, not yet confirmed", stored_email == email and role == "requester" and unverified == "t")
    check("password stored as an argon2id hash, not plain text", hashed.startswith("$argon2id$v=19$") and PASSWORD not in hashed)
    r = post(s, "/auth/login", {"email": email, "password": PASSWORD})
    check("login refused until the email is confirmed", r.status_code == 403 and r.json()["error"]["code"] == "email_not_verified", r.text)

    step("Confirmation email")
    mail = wait_for_mail(email, "Confirm", after=t0)
    if not check("confirmation email arrived in Mailpit", mail is not None):
        return
    check("From header is set", mail["From"]["Address"] and "Procurement" in (mail["From"]["Name"] or ""), mail["From"])
    check("has plain-text and HTML versions", bool(mail["Text"].strip()) and "<a href=" in mail["HTML"])
    token = link_token(mail, "/verify-email")
    check("link points at the app's /verify-email page", token is not None, mail["Text"][:300])
    check("the link opens the app (200)", requests.get(f"{GATEWAY}/verify-email").status_code == 200)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    check("database holds the token's hash, never the token",
          sql(f"SELECT count(*) FROM auth_tokens WHERE token_hash = '{token_hash}'") == "1"
          and sql(f"SELECT count(*) FROM auth_tokens WHERE token_hash = '{token}'") == "0")
    r = post(s, "/auth/verify-email", {"token": token})
    check("confirming works", r.status_code == 200, r.text)
    r = post(s, "/auth/verify-email", {"token": token})
    check("the same link can't be used twice", r.status_code == 400 and r.json()["error"]["code"] == "invalid_token", r.text)

    step("Log in, refresh, change password, log out")
    r = post(s, "/auth/login", {"email": email, "password": PASSWORD})
    check("login works after confirming", r.status_code == 200, r.text)
    access = r.json()["data"]["access_token"]
    check("refresh token only in an httpOnly cookie", "refresh_token" not in r.text and "HttpOnly" in r.headers.get("Set-Cookie", ""))
    me = s.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {access}"}).json()["data"]
    check("/auth/me returns the account without secrets", me["email"] == email and "hashed_password" not in me)
    other_device = requests.Session()
    post(other_device, "/auth/login", {"email": email, "password": PASSWORD})

    t1 = time.time()
    r = post(s, "/auth/change-password", {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
             headers={"Authorization": f"Bearer {access}"})
    check("change password works", r.status_code == 200, r.text)
    check("this device keeps working", post(s, "/auth/refresh", {}, headers=csrf(s)).status_code == 200)
    check("the other device is signed out", post(other_device, "/auth/refresh", {}, headers=csrf(other_device)).status_code == 401)
    check("'password changed' notice emailed", wait_for_mail(email, "password was changed", after=t1) is not None)
    r = post(s, "/auth/logout", {}, headers=csrf(s))
    check("logout works", r.status_code == 200 and post(s, "/auth/refresh", {}, headers=csrf(s)).status_code in (401, 403))

    step("Forgot / reset password")
    t2 = time.time()
    r = post(s, "/auth/forgot-password", {"email": email})
    unknown = post(s, "/auth/forgot-password", {"email": address("nobody")})
    check("same answer for known and unknown addresses", r.status_code == unknown.status_code == 202 and r.json() == unknown.json())
    mail = wait_for_mail(email, "Reset", after=t2)
    check("reset email arrived", mail is not None)
    reset_token = link_token(mail, "/reset-password") if mail else None
    check("reset link points at /reset-password", reset_token is not None)
    check("nothing was sent to the unknown address", count_mail(address("nobody")) == 0)
    r = post(s, "/auth/reset-password", {"token": reset_token, "new_password": "short"})
    check("weak new password refused", r.status_code == 400 and r.json()["error"]["code"] == "weak_password")
    r = post(s, "/auth/reset-password", {"token": reset_token, "new_password": PASSWORD})
    check("reset works (same link still valid after the refusal)", r.status_code == 200, r.text)
    r = post(s, "/auth/reset-password", {"token": reset_token, "new_password": NEW_PASSWORD})
    check("reset link can't be reused", r.status_code == 400 and r.json()["error"]["code"] == "invalid_token")
    check("old password no longer works", post(s, "/auth/login", {"email": email, "password": NEW_PASSWORD}).status_code == 401)
    check("new password works", post(s, "/auth/login", {"email": email, "password": PASSWORD}).status_code == 200)

    step("Expired links")
    exp = address("expired")
    post(requests.Session(), "/auth/register", {"email": exp, "password": PASSWORD})
    mail = wait_for_mail(exp, "Confirm")
    exp_token = link_token(mail, "/verify-email")
    sql(f"UPDATE auth_tokens SET expires_at = now() - interval '1 second' "
        f"WHERE user_id = (SELECT id FROM auth_users WHERE email = '{exp}')")
    r = post(s, "/auth/verify-email", {"token": exp_token})
    check("expired confirmation link refused", r.status_code == 400 and r.json()["error"]["code"] == "invalid_token")
    sql(f"UPDATE auth_users SET email_verified_at = now() WHERE email = '{exp}'")
    post(s, "/auth/forgot-password", {"email": exp})
    mail = wait_for_mail(exp, "Reset")
    exp_reset = link_token(mail, "/reset-password")
    sql(f"UPDATE auth_tokens SET expires_at = now() - interval '1 second' WHERE purpose = 'reset_password' "
        f"AND user_id = (SELECT id FROM auth_users WHERE email = '{exp}')")
    r = post(s, "/auth/reset-password", {"token": exp_reset, "new_password": NEW_PASSWORD})
    check("expired reset link refused", r.status_code == 400)

    step("Lockout after wrong passwords")
    codes = [post(s, "/auth/login", {"email": email, "password": f"wrong guess {i}"}).status_code for i in range(5)]
    check("4 × 401 then locked (429)", codes == [401, 401, 401, 401, 429], codes)
    r = post(s, "/auth/login", {"email": email, "password": PASSWORD})
    check("while locked, even the right password is refused", r.status_code == 429 and "Try again" in r.json()["error"]["message"])
    ghost = [post(s, "/auth/login", {"email": address("ghost"), "password": f"x{i}"}).status_code for i in range(5)]
    check("unknown addresses behave the same (no account enumeration)", ghost == codes, ghost)
    sql(f"UPDATE auth_login_attempts SET locked_until = now() - interval '1 second' WHERE email = '{email}'")
    check("after the lock expires the right password works",
          post(s, "/auth/login", {"email": email, "password": PASSWORD}).status_code == 200)

    step("Sign-up with an existing address")
    t3 = time.time()
    r = post(s, "/auth/register", {"email": email, "password": "another passphrase entirely"})
    check("same 202 answer as a new sign-up", r.status_code == 202 and "inbox" in r.json()["data"]["message"])
    check("owner gets an 'already have an account' email", wait_for_mail(email, "Sign-up attempt", after=t3) is not None)
    check("their password was not replaced", post(s, "/auth/login", {"email": email, "password": PASSWORD}).status_code == 200)

    step("Audit trail")
    actions = sql(f"SELECT string_agg(action, ',' ORDER BY created_at) FROM audit_log WHERE entity_type = 'user' "
                  f"AND entity_id = (SELECT id FROM auth_users WHERE email = '{email}')")
    check("sign-up, confirmation, password changes and lockout are audited",
          all(a in actions for a in ("user.registered", "user.email_verified", "user.password_changed",
                                     "user.password_reset", "user.locked_out")), actions)
    check("no password or token in the audit trail",
          sql(f"SELECT count(*) FROM audit_log WHERE payload::text LIKE '%{RUN}%' OR payload::text LIKE '%{token}%'") == "0")

    step("Gateway rate limit on email-sending endpoints")
    flood = [post(requests.Session(), "/auth/forgot-password", {"email": address("flood")}, gateway_retry=False)
             for _ in range(12)]
    limited = [r for r in flood if r.status_code == 429]
    check("forgot-password flood gets 429 from the gateway", limited, [r.status_code for r in flood])
    check("the gateway's 429 is the standard JSON error",
          limited and limited[0].json()["error"]["code"] == "rate_limited")


if __name__ == "__main__":
    try:
        main()
    finally:
        sql(f"DELETE FROM auth_login_attempts WHERE email LIKE 'e2e-auth-{RUN}-%'")
        sql(f"DELETE FROM audit_log WHERE entity_type = 'user' AND entity_id IN "
            f"(SELECT id FROM auth_users WHERE email LIKE 'e2e-auth-{RUN}-%')")
        sql(f"DELETE FROM auth_users WHERE email LIKE 'e2e-auth-{RUN}-%'")
    passed = sum(results)
    print(f"\n{'=' * 60}\n  auth flows: {passed} passed, {len(results) - passed} failed\n{'=' * 60}")
    sys.exit(0 if results and all(results) else 1)
