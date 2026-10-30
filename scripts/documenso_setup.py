"""One-time setup of the stack's Documenso for contract signing. Re-runnable.

    python scripts/documenso_setup.py     # then: docker compose up -d contract-risk-agent && docker compose restart nginx

1. Makes the signing certificate Documenso seals every completed contract
   with (secrets/documenso/cert.p12, self-signed: fine for development; a
   real deployment uses a certificate from a certifying authority).
2. Creates the platform's Documenso account (confirming its email through
   Mailpit), an API token and the webhook to contract-risk-agent.
3. Writes APP_DOCUMENSO_API_TOKEN, APP_DOCUMENSO_WEBHOOK_SECRET and the
   account's password to .env.

Needs the stack running (`documenso` healthy) and `requests`
(pip install -r tests/e2e/requirements.txt).
"""
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
CERT_DIR = ROOT / "secrets" / "documenso"
DOCUMENSO = os.getenv("DOCUMENSO_PUBLIC_URL", "http://localhost:3010")
MAILPIT = os.getenv("MAILPIT_URL", "http://localhost:8025")
ADMIN_EMAIL = "esign-admin@procurement.local"
WEBHOOK_URL = "http://contract-risk-agent:8003/webhooks/documenso"
WEBHOOK_EVENTS = ["DOCUMENT_RECIPIENT_COMPLETED", "DOCUMENT_COMPLETED", "DOCUMENT_REJECTED"]


def read_env() -> dict:
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()
    return values


def write_env(updates: dict) -> None:
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
    done = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in updates and not line.lstrip().startswith("#"):
            lines[i] = f"{key}={updates[key]}"
            done.add(key)
    missing = [k for k in updates if k not in done]
    if missing:
        lines += ["", "# Documenso (scripts/documenso_setup.py)"] + [f"{k}={updates[k]}" for k in missing]
    ENV_FILE.write_text("\n".join(lines) + "\n")


def ensure_certificate(passphrase: str) -> None:
    p12 = CERT_DIR / "cert.p12"
    if p12.exists():
        print(f"certificate: {p12.relative_to(ROOT)} (kept)")
        return
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    key, crt = CERT_DIR / "key.pem", CERT_DIR / "cert.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-days", "1095", "-nodes",
         "-keyout", str(key), "-out", str(crt),
         "-subj", "/CN=Procurement Platform e-signature (development)/O=IT Procurement Intelligence Platform"],
        check=True, capture_output=True,
    )
    export = ["openssl", "pkcs12", "-export", "-out", str(p12), "-inkey", str(key), "-in", str(crt),
              "-passout", f"pass:{passphrase}"]
    # Documenso reads PKCS#12 files in the older encryption; OpenSSL 3+
    # needs -legacy for that, LibreSSL has no such flag.
    if subprocess.run(export + ["-legacy"], capture_output=True).returncode != 0:
        subprocess.run(export, check=True, capture_output=True)
    p12.chmod(0o644)  # read by the container's non-root user
    print(f"certificate: created {p12.relative_to(ROOT)}; restart documenso to load it")


class Documenso:
    """Its browser endpoints (sign-up, sign-in, tRPC) — the API token and
    webhook can only be made from a signed-in session."""

    def __init__(self):
        self.cookies: dict = {}

    def call(self, method: str, path: str, **kw) -> requests.Response:
        headers = {"Origin": DOCUMENSO, "Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items())}
        headers.update(kw.pop("headers", {}))
        res = requests.request(method, DOCUMENSO + path, headers=headers, timeout=30, **kw)
        # Its cookies are set for Domain=localhost, which requests' cookie jar refuses.
        for cookie in res.raw.headers.getlist("Set-Cookie"):
            name, value = cookie.split(";", 1)[0].split("=", 1)
            self.cookies[name] = value
        return res

    def trpc(self, proc: str, data=None, team_id=None, query=False):
        headers = {"content-type": "application/json"}
        if team_id is not None:
            headers["x-team-id"] = str(team_id)
        if query:
            qs = "" if data is None else "?input=" + urllib.parse.quote(json.dumps({"json": data}))
            res = self.call("GET", f"/api/trpc/{proc}{qs}", headers=headers)
        else:
            res = self.call("POST", f"/api/trpc/{proc}", headers=headers, data=json.dumps({"json": data}))
        if res.status_code >= 400:
            raise SystemExit(f"Documenso {proc} failed ({res.status_code}): {res.text[:300]}")
        return res.json()["result"]["data"]["json"]

    def sign_up(self, password: str) -> None:
        def inbox() -> list:
            found = requests.get(f"{MAILPIT}/api/v1/search", params={"query": f"to:{ADMIN_EMAIL}"}, timeout=10).json()
            return found.get("messages") or []

        seen = {m["ID"] for m in inbox()}
        res = self.call("POST", "/api/auth/email-password/signup",
                        json={"name": "Procurement Platform", "email": ADMIN_EMAIL, "password": password})
        if res.status_code >= 400:
            raise SystemExit(f"Documenso sign-up failed ({res.status_code}): {res.text[:300]}")
        token = None
        for _ in range(20):
            for m in [m for m in inbox() if m["ID"] not in seen]:
                text = requests.get(f"{MAILPIT}/api/v1/message/{m['ID']}", timeout=10).json().get("Text", "")
                match = re.search(r"verify-email/([A-Za-z0-9_-]+)", text)
                if match:
                    token = match.group(1)
                    break
            if token:
                break
            time.sleep(1)
        if not token:
            raise SystemExit("Documenso's confirmation email didn't arrive in Mailpit")
        res = self.call("POST", "/api/auth/email-password/verify-email", json={"token": token})
        if res.status_code >= 400 or res.json().get("state") != "VERIFIED":
            raise SystemExit(f"Documenso didn't confirm the account's email: {res.text[:200]}")

    def sign_in(self, password: str) -> bool:
        csrf = self.call("GET", "/api/auth/csrf").json()["csrfToken"]
        res = self.call("POST", "/api/auth/email-password/authorize",
                        json={"email": ADMIN_EMAIL, "password": password, "csrfToken": csrf})
        return res.status_code < 400


def token_works(token: str) -> bool:
    res = requests.get(f"{DOCUMENSO}/api/v2/envelope", headers={"Authorization": token}, timeout=15)
    return res.status_code == 200


def main() -> None:
    env = read_env()
    try:
        requests.get(f"{DOCUMENSO}/api/health", timeout=10).raise_for_status()
    except requests.RequestException as e:
        sys.exit(f"Documenso isn't reachable at {DOCUMENSO} ({e}). Start it: docker compose up -d documenso")
    ensure_certificate(env.get("DOCUMENSO_SIGNING_PASSPHRASE") or "dev-documenso-signing")

    password = env.get("DOCUMENSO_ADMIN_PASSWORD") or ("Ds-" + secrets.token_urlsafe(18))
    doc = Documenso()
    if not doc.sign_in(password):
        doc.sign_up(password)
        if not doc.sign_in(password):
            sys.exit(f"Couldn't sign in to Documenso as {ADMIN_EMAIL}. If the account exists with another "
                     "password, set DOCUMENSO_ADMIN_PASSWORD in .env.")
        print(f"account: created {ADMIN_EMAIL}")
    else:
        print(f"account: {ADMIN_EMAIL} (kept)")

    org = doc.trpc("organisation.getMany", query=True)[0]
    team_id = doc.trpc("team.find", {"organisationId": org["id"]}, query=True)["data"][0]["id"]

    token = env.get("APP_DOCUMENSO_API_TOKEN")
    if token and token_works(token):
        print("API token: kept")
    else:
        token = doc.trpc("apiToken.create", {"teamId": team_id, "tokenName": "procurement-platform",
                                             "expirationDate": None}, team_id=team_id)["token"]
        print("API token: created")

    secret = env.get("APP_DOCUMENSO_WEBHOOK_SECRET") or secrets.token_urlsafe(24)
    hooks = doc.trpc("webhook.getTeamWebhooks", team_id=team_id, query=True)
    current = [h for h in hooks if h["webhookUrl"] == WEBHOOK_URL]
    if any(h.get("secret") == secret and sorted(h["eventTriggers"]) == sorted(WEBHOOK_EVENTS) and h["enabled"]
           for h in current):
        print("webhook: kept")
    else:
        for h in current:
            doc.trpc("webhook.deleteWebhook", {"id": h["id"]}, team_id=team_id)
        doc.trpc("webhook.createWebhook", {"webhookUrl": WEBHOOK_URL, "eventTriggers": WEBHOOK_EVENTS,
                                           "secret": secret, "enabled": True}, team_id=team_id)
        print(f"webhook: {WEBHOOK_URL}")

    write_env({"APP_DOCUMENSO_API_TOKEN": token, "APP_DOCUMENSO_WEBHOOK_SECRET": secret,
               "DOCUMENSO_ADMIN_PASSWORD": password})
    print("\n.env updated. Load it: docker compose up -d contract-risk-agent contract-risk-agent-worker "
          "&& docker compose restart nginx")


if __name__ == "__main__":
    main()
