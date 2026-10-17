"""Every account flow against a real Postgres: sign-up → confirm email →
login → change password → logout → forgot/reset password, plus the
failure cases (expired and reused links, lockout, generic answers).

Single-use links and the lockout counter are enforced by SQL statements,
so these tests need a real database. They create a throwaway database
(AUTH_TEST_DATABASE_URL, default name auth_test), run the migrations into
it, and drop it afterwards. scripts/test-service.sh sets the URL when the
compose stack is running; without it the tests are skipped.
"""
import os
import re
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import psycopg2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

TEST_DB_URL = os.environ.get("AUTH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason="AUTH_TEST_DATABASE_URL not set (needs Postgres)")

SERVICE_DIR = Path(__file__).resolve().parent.parent
PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a completely different passphrase"


def _admin_dsn() -> str:
    base, _, _ = TEST_DB_URL.rpartition("/")
    return f"{base}/postgres"


def _db_name() -> str:
    return TEST_DB_URL.rpartition("/")[2]


@pytest.fixture(scope="module")
def database():
    name = _db_name()
    assert name.endswith("_test"), "refusing to recreate a database whose name doesn't end in _test"
    admin = psycopg2.connect(_admin_dsn())
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
        cur.execute(f'CREATE DATABASE "{name}"')
    conn = psycopg2.connect(TEST_DB_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        # The shared audit_log table normally comes from shared/db/init.sql.
        cur.execute("""CREATE TABLE audit_log (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), entity_id uuid,
                       entity_type text, action text, payload jsonb, created_at timestamptz DEFAULT now(),
                       performed_by varchar(255), details jsonb)""")
    subprocess.run(["alembic", "upgrade", "head"], cwd=SERVICE_DIR, check=True,
                   env={**os.environ, "ALEMBIC_DATABASE_URL": TEST_DB_URL})
    yield conn
    conn.close()
    with admin.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    admin.close()


def sql(conn, query, *args):
    with conn.cursor() as cur:
        cur.execute(query, args)
        return cur.fetchall() if cur.description else None


class Outbox:
    """Captures the emails the endpoints would send."""

    def __init__(self):
        self.sent = []

    async def __call__(self, to, message):
        self.sent.append((to, *message))

    def last_to(self, address):
        mails = [m for m in self.sent if m[0] == address]
        assert mails, f"no email sent to {address}"
        return mails[-1]

    def token_for(self, address):
        _, subject, text_body, html_body = self.last_to(address)
        return re.search(r"#token=([A-Za-z0-9_-]+)", text_body).group(1)


@pytest.fixture
def env(database):
    from app.api import auth, users
    from app.database import get_db
    from shared.http.error_handlers import register_error_handlers

    sql(database, "TRUNCATE auth_users, auth_tokens, auth_login_attempts, audit_log CASCADE")
    engine = create_async_engine(TEST_DB_URL.replace("postgresql://", "postgresql+asyncpg://"), poolclass=NullPool)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def db():
        async with sessions() as session:
            yield session

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(auth.router, prefix="/api/auth")
    app.include_router(users.router, prefix="/api/auth/users")
    app.dependency_overrides[get_db] = db
    outbox = Outbox()
    with patch("app.emails.send_quietly", outbox), \
            patch("app.api.auth.is_password_breached", AsyncMock(return_value=False)), \
            TestClient(app, base_url="http://testserver") as client:
        yield client, outbox, database


def signup(client, outbox, email, password=PASSWORD):
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 202, r.text
    return r


def verified_user(client, outbox, email):
    signup(client, outbox, email)
    r = client.post("/api/auth/verify-email", json={"token": outbox.token_for(email)})
    assert r.status_code == 200, r.text


def login(client, email, password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def csrf(client):
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def bearer(r):
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


# ------------------------------------------------------------ happy path

def test_full_account_lifecycle(env):
    client, outbox, db = env
    email = "Priya.Shah@Example.com"
    signup(client, outbox, email)

    # Stored lower-cased, as an argon2id hash, not yet confirmed.
    [(stored_email, hashed, verified, role)] = sql(
        db, "SELECT email, hashed_password, email_verified_at, role FROM auth_users")
    assert stored_email == "priya.shah@example.com"
    assert hashed.startswith("$argon2id$") and PASSWORD not in hashed
    assert verified is None and role == "requester"

    # Can't log in before confirming.
    r = login(client, email)
    assert r.status_code == 403 and r.json()["error"]["code"] == "email_not_verified"

    # The email: plain text + HTML, working link, token only as a hash in the DB.
    to, subject, text_body, html_body = outbox.last_to("priya.shah@example.com")
    assert "Confirm" in subject and "http://localhost:8080/verify-email#token=" in text_body
    assert "<a href=" in html_body
    token = outbox.token_for("priya.shah@example.com")
    assert sql(db, "SELECT count(*) FROM auth_tokens WHERE token_hash = %s", token) == [(0,)]

    assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 200
    r = login(client, email)
    assert r.status_code == 200
    assert "refresh_token" in client.cookies and "refresh_token" not in r.text
    assert client.get("/api/auth/me", headers=bearer(r)).json()["data"]["email"] == "priya.shah@example.com"

    # Refresh works, logout ends it.
    assert client.post("/api/auth/refresh", headers=csrf(client)).status_code == 200
    assert client.post("/api/auth/logout", headers=csrf(client)).status_code == 200
    assert "refresh_token" not in client.cookies

    actions = [a for (a,) in sql(db, "SELECT action FROM audit_log ORDER BY created_at")]
    assert actions[:2] == ["user.registered", "user.email_verified"]
    # Nothing secret in the audit trail.
    assert not sql(db, "SELECT 1 FROM audit_log WHERE payload::text ILIKE %s", f"%{PASSWORD}%")


def test_forgot_and_reset_password(env):
    client, outbox, db = env
    email = "reset.me@example.com"
    verified_user(client, outbox, email)
    old_session = login(client, email)
    assert old_session.status_code == 200

    r = client.post("/api/auth/forgot-password", json={"email": email})
    assert r.status_code == 202
    _, subject, text_body, _ = outbox.last_to(email)
    assert "Reset" in subject and "/reset-password#token=" in text_body

    r = client.post("/api/auth/reset-password", json={"token": outbox.token_for(email), "new_password": NEW_PASSWORD})
    assert r.status_code == 200, r.text
    assert login(client, email).status_code == 401
    assert login(client, email, NEW_PASSWORD).status_code == 200
    assert "password was changed" in outbox.last_to(email)[1]


def test_reset_ends_existing_sessions(env):
    client, outbox, db = env
    email = "sessions@example.com"
    verified_user(client, outbox, email)
    assert login(client, email).status_code == 200
    stolen_cookies = dict(client.cookies)

    client.post("/api/auth/forgot-password", json={"email": email})
    client.post("/api/auth/reset-password", json={"token": outbox.token_for(email), "new_password": NEW_PASSWORD})

    # The refresh cookie from before the reset no longer works.
    client.cookies.clear()
    for k, v in stolen_cookies.items():
        client.cookies.set(k, v)
    r = client.post("/api/auth/refresh", headers=csrf(client))
    assert r.status_code == 401


def test_change_password(env):
    client, outbox, db = env
    email = "changer@example.com"
    verified_user(client, outbox, email)
    r = login(client, email)

    wrong = client.post("/api/auth/change-password", headers=bearer(r),
                        json={"current_password": "not my password!!", "new_password": NEW_PASSWORD})
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "wrong_password"

    ok = client.post("/api/auth/change-password", headers=bearer(r),
                     json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert ok.status_code == 200
    # This device keeps a working session (new cookie, new token_version).
    assert client.post("/api/auth/refresh", headers=csrf(client)).status_code == 200
    assert login(client, email).status_code == 401
    assert login(client, email, NEW_PASSWORD).status_code == 200
    [(changed_at,)] = sql(db, "SELECT password_changed_at FROM auth_users WHERE email = %s", email)
    assert changed_at is not None


# ------------------------------------------------------------ one-time links

def test_verification_link_is_single_use(env):
    client, outbox, db = env
    signup(client, outbox, "once@example.com")
    token = outbox.token_for("once@example.com")
    assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 200
    r = client.post("/api/auth/verify-email", json={"token": token})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_token"


def test_reset_link_is_single_use(env):
    client, outbox, db = env
    email = "reuse@example.com"
    verified_user(client, outbox, email)
    client.post("/api/auth/forgot-password", json={"email": email})
    token = outbox.token_for(email)
    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}).status_code == 200
    again = client.post("/api/auth/reset-password", json={"token": token, "new_password": "yet another passphrase"})
    assert again.status_code == 400 and again.json()["error"]["code"] == "invalid_token"
    assert login(client, email, NEW_PASSWORD).status_code == 200


def test_expired_links_are_refused(env):
    client, outbox, db = env
    email = "slow@example.com"
    signup(client, outbox, email)
    verify_token = outbox.token_for(email)
    sql(db, "UPDATE auth_tokens SET expires_at = now() - interval '1 second'")
    assert client.post("/api/auth/verify-email", json={"token": verify_token}).status_code == 400

    # Confirm via a fresh link (cooldown passed), then expire a reset link.
    sql(db, "UPDATE auth_tokens SET created_at = now() - interval '2 minutes'")
    client.post("/api/auth/resend-verification", json={"email": email})
    assert client.post("/api/auth/verify-email", json={"token": outbox.token_for(email)}).status_code == 200
    client.post("/api/auth/forgot-password", json={"email": email})
    reset_token = outbox.token_for(email)
    sql(db, "UPDATE auth_tokens SET expires_at = now() - interval '1 second' WHERE purpose = 'reset_password'")
    r = client.post("/api/auth/reset-password", json={"token": reset_token, "new_password": NEW_PASSWORD})
    assert r.status_code == 400
    assert login(client, email).status_code == 200


def test_new_link_cancels_the_old_one(env):
    client, outbox, db = env
    email = "twice@example.com"
    verified_user(client, outbox, email)
    client.post("/api/auth/forgot-password", json={"email": email})
    first = outbox.token_for(email)
    sql(db, "UPDATE auth_tokens SET created_at = now() - interval '2 minutes'")
    client.post("/api/auth/forgot-password", json={"email": email})
    second = outbox.token_for(email)
    assert first != second
    assert client.post("/api/auth/reset-password", json={"token": first, "new_password": NEW_PASSWORD}).status_code == 400
    assert client.post("/api/auth/reset-password", json={"token": second, "new_password": NEW_PASSWORD}).status_code == 200


def test_resend_is_throttled(env):
    client, outbox, db = env
    signup(client, outbox, "impatient@example.com")
    for _ in range(3):
        client.post("/api/auth/resend-verification", json={"email": "impatient@example.com"})
    assert len([m for m in outbox.sent if m[0] == "impatient@example.com"]) == 1


def test_weak_password_does_not_use_up_the_reset_link(env):
    client, outbox, db = env
    email = "careful@example.com"
    verified_user(client, outbox, email)
    client.post("/api/auth/forgot-password", json={"email": email})
    token = outbox.token_for(email)
    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": "short"}).status_code == 400
    r = client.post("/api/auth/reset-password", json={"token": token, "new_password": "careful@example.com is mine"})
    assert r.status_code == 400
    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}).status_code == 200


# ------------------------------------------------------------ lockout

def test_lockout_after_repeated_wrong_passwords(env):
    client, outbox, db = env
    email = "target@example.com"
    verified_user(client, outbox, email)
    codes = [login(client, email, f"wrong password {i}").status_code for i in range(5)]
    assert codes == [401, 401, 401, 401, 429]
    # Locked: even the right password is refused.
    r = login(client, email)
    assert r.status_code == 429 and r.json()["error"]["code"] == "account_locked"
    assert sql(db, "SELECT action FROM audit_log WHERE action = 'user.locked_out'")

    # When the lock runs out, the right password works and resets the count.
    sql(db, "UPDATE auth_login_attempts SET locked_until = now() - interval '1 second'")
    assert login(client, email).status_code == 200
    assert sql(db, "SELECT count(*) FROM auth_login_attempts") == [(0,)]


def test_password_reset_clears_the_lockout(env):
    client, outbox, db = env
    email = "locked.out@example.com"
    verified_user(client, outbox, email)
    for i in range(5):
        login(client, email, f"wrong password {i}")
    assert login(client, email).status_code == 429
    client.post("/api/auth/forgot-password", json={"email": email})
    client.post("/api/auth/reset-password", json={"token": outbox.token_for(email), "new_password": NEW_PASSWORD})
    assert login(client, email, NEW_PASSWORD).status_code == 200


def test_unknown_addresses_lock_the_same_way(env):
    # Otherwise "locked" vs "invalid" would reveal which addresses exist.
    client, outbox, db = env
    codes = [login(client, "ghost@example.com", f"guess {i}").status_code for i in range(6)]
    assert codes == [401, 401, 401, 401, 429, 429]


def test_failures_in_parallel_all_count(env):
    import concurrent.futures
    client, outbox, db = env
    email = "parallel@example.com"
    verified_user(client, outbox, email)
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda i: login(client, email, f"wrong {i}"), range(8)))
    assert login(client, email).status_code == 429


# ------------------------------------------------------------ no account enumeration

def test_signup_answer_is_the_same_for_existing_accounts(env):
    client, outbox, db = env
    verified_user(client, outbox, "taken@example.com")
    new = signup(client, outbox, "fresh@example.com")
    dup = signup(client, outbox, "Taken@Example.com", "some other passphrase")
    assert new.json() == dup.json()
    # The owner gets an "already have an account" email, not a new account.
    assert "already" in outbox.last_to("taken@example.com")[1].lower() + outbox.last_to("taken@example.com")[2].lower()
    assert sql(db, "SELECT count(*) FROM auth_users WHERE email = 'taken@example.com'") == [(1,)]
    # ...and their password was not replaced.
    assert login(client, "taken@example.com").status_code == 200


def test_forgot_password_answer_is_the_same_for_unknown_addresses(env):
    client, outbox, db = env
    verified_user(client, outbox, "known@example.com")
    known = client.post("/api/auth/forgot-password", json={"email": "known@example.com"})
    unknown = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert not [m for m in outbox.sent if m[0] == "nobody@example.com"]


def test_wrong_email_and_wrong_password_look_the_same(env):
    client, outbox, db = env
    verified_user(client, outbox, "someone@example.com")
    a = login(client, "someone@example.com", "not the password")
    b = login(client, "no-such-user@example.com", "not the password")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_passwords_never_come_back_in_responses(env):
    client, outbox, db = env
    signup(client, outbox, "echo@example.com")
    responses = [
        client.post("/api/auth/register", json={"password": PASSWORD}),  # missing email → 422
        client.post("/api/auth/login", json={"email": "echo@example.com", "password": PASSWORD}),
        client.post("/api/auth/register", json={"email": "not-an-email", "password": PASSWORD}),
    ]
    for r in responses:
        assert PASSWORD not in r.text


# ------------------------------------------------------------ roles / admin

def test_admin_changes_role_and_disables_account(env):
    client, outbox, db = env
    verified_user(client, outbox, "boss@example.com")
    sql(db, "UPDATE auth_users SET role = 'admin' WHERE email = 'boss@example.com'")
    verified_user(client, outbox, "worker@example.com")
    boss = bearer(login(client, "boss@example.com"))
    [(worker_id,)] = sql(db, "SELECT id::text FROM auth_users WHERE email = 'worker@example.com'")

    worker_login = login(client, "worker@example.com")
    assert client.get("/api/auth/users", headers=bearer(worker_login)).status_code == 403

    users = client.get("/api/auth/users", headers=boss).json()["data"]
    assert {u["email"] for u in users} == {"boss@example.com", "worker@example.com"}
    assert all("hashed_password" not in u for u in users)

    r = client.patch(f"/api/auth/users/{worker_id}", headers=boss, json={"role": "approver"})
    assert r.status_code == 200 and r.json()["data"]["role"] == "approver"
    # The worker's old session (role "requester") can't be refreshed.
    client.cookies.clear()
    worker_login = login(client, "worker@example.com")
    assert client.get("/api/auth/me", headers=bearer(worker_login)).json()["data"]["role"] == "approver"

    client.patch(f"/api/auth/users/{worker_id}", headers=boss, json={"is_active": False})
    r = login(client, "worker@example.com")
    assert r.status_code == 403 and r.json()["error"]["code"] == "account_disabled"
    assert client.post("/api/auth/refresh", headers=csrf(client)).status_code == 401

    # Invalid role is rejected by the schema and by the DB constraint.
    assert client.patch(f"/api/auth/users/{worker_id}", headers=boss, json={"role": "superuser"}).status_code == 422
    with pytest.raises(psycopg2.errors.CheckViolation):
        sql(db, "UPDATE auth_users SET role = 'superuser' WHERE email = 'worker@example.com'")


def test_admin_cannot_demote_themselves(env):
    client, outbox, db = env
    verified_user(client, outbox, "only.admin@example.com")
    sql(db, "UPDATE auth_users SET role = 'admin' WHERE email = 'only.admin@example.com'")
    r = login(client, "only.admin@example.com")
    [(my_id,)] = sql(db, "SELECT id::text FROM auth_users")
    assert client.patch(f"/api/auth/users/{my_id}", headers=bearer(r), json={"role": "requester"}).status_code == 400
    assert client.patch(f"/api/auth/users/{my_id}", headers=bearer(r), json={"is_active": False}).status_code == 400


def test_legacy_bcrypt_hash_upgrades_on_login(env):
    import bcrypt
    client, outbox, db = env
    verified_user(client, outbox, "old.timer@example.com")
    legacy = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(12)).decode()
    sql(db, "UPDATE auth_users SET hashed_password = %s WHERE email = 'old.timer@example.com'", legacy)
    assert login(client, "old.timer@example.com").status_code == 200
    [(hashed,)] = sql(db, "SELECT hashed_password FROM auth_users WHERE email = 'old.timer@example.com'")
    assert hashed.startswith("$argon2id$")


def test_email_is_unique_regardless_of_case_in_the_database(env):
    client, outbox, db = env
    signup(client, outbox, "unique@example.com")
    with pytest.raises(psycopg2.errors.IntegrityError):
        sql(db, "INSERT INTO auth_users (email, hashed_password, role) VALUES ('UNIQUE@example.com', 'x', 'requester')")
