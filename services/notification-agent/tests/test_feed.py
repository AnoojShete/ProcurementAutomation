"""The in-app feed and its unread badge, against a real Postgres: only
important notifications count, reading one lowers the count, read state
is per person and survives a new session.

Needs NOTIFICATION_TEST_DATABASE_URL (scripts/test-service.sh sets it to a
throwaway notification_test database when the stack is running);
otherwise skipped."""
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from shared.db.sql_runner import split_sql

TEST_DB_URL = os.environ.get("NOTIFICATION_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason="NOTIFICATION_TEST_DATABASE_URL not set (needs Postgres)")

MIGRATION = os.path.join(os.path.dirname(__file__), "..", "migrations", "0001_notification_tables.sql")
MAILBOX = "dept_manager@users.procurement.local"


@pytest.fixture(scope="module")
def database():
    base, _, name = TEST_DB_URL.rpartition("/")
    assert name.endswith("_test"), "refusing to recreate a database whose name doesn't end in _test"
    admin = psycopg2.connect(f"{base}/postgres")
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
        cur.execute(f'CREATE DATABASE "{name}"')
    conn = psycopg2.connect(TEST_DB_URL)
    conn.autocommit = True
    with conn.cursor() as cur, open(MIGRATION) as f:
        for statement in split_sql(f.read()):
            cur.execute(statement)
    yield conn
    conn.close()
    with admin.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    admin.close()


_minutes = iter(range(10_000))


def notify(conn, recipient, *, priority="urgent", status="sent", event_type="approval.decided"):
    nid = str(uuid.uuid4())
    created = datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(minutes=next(_minutes))
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO notification_log (id, recipient, event_type, priority, status, subject, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (nid, recipient, event_type, priority, status, f"{event_type} for {recipient}", created))
    return nid


@pytest.fixture
def env(database):
    from app.api import notifications
    from app.database import get_db
    from shared.auth import get_current_user
    from shared.auth.middleware import CurrentUser
    from shared.http.error_handlers import register_error_handlers

    with database.cursor() as cur:
        cur.execute("TRUNCATE notification_log CASCADE")
    engine = create_async_engine(TEST_DB_URL.replace("postgresql://", "postgresql+asyncpg://"), poolclass=NullPool)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def db():
        async with sessions() as session:
            yield session

    def client_for(email, role, user_id=None):
        app = FastAPI()
        register_error_handlers(app)
        app.include_router(notifications.router, prefix="/notifications")
        app.dependency_overrides[get_db] = db
        user = CurrentUser(id=user_id or str(uuid.uuid5(uuid.NAMESPACE_DNS, email)), email=email, role=role)
        app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    yield client_for, database


def unread(client):
    return client.get("/notifications/unread-count").json()["data"]["unread"]


def test_badge_counts_only_important_unread_notifications(env):
    client_for, db = env
    mine = notify(db, "anooj@acme.test")
    notify(db, "anooj@acme.test", priority="digest", status="queued_digest", event_type="document.classified")
    notify(db, "anooj@acme.test", priority="digest", event_type="digest.flush")
    notify(db, "anooj@acme.test", priority="digest", event_type="license.usage.updated")
    notify(db, "anooj@acme.test", event_type="contract.signed")
    notify(db, "someone.else@acme.test")
    me = client_for("anooj@acme.test", "requester")

    assert unread(me) == 1
    feed = me.get("/notifications/feed").json()
    assert [n["id"] for n in feed["data"]] == [mine] and feed["data"][0]["read"] is False
    assert feed["meta"]["unread"] == 1
    # The full history still has the routine ones.
    assert len(me.get("/notifications/feed?scope=all").json()["data"]) == 5


def test_reading_lowers_the_count_and_it_stays_read_next_session(env):
    client_for, db = env
    first, second = notify(db, "anooj@acme.test"), notify(db, "anooj@acme.test")
    me = client_for("anooj@acme.test", "requester")
    assert unread(me) == 2

    r = me.post(f"/notifications/{first}/read")
    assert r.status_code == 200 and r.json()["data"]["unread"] == 1
    assert me.post(f"/notifications/{first}/read").json()["data"]["unread"] == 1  # reading twice is harmless

    # A new session (new client, same person) sees the same state.
    again = client_for("anooj@acme.test", "requester")
    assert unread(again) == 1
    assert {n["id"]: n["read"] for n in again.get("/notifications/feed").json()["data"]} == {first: True, second: False}
    assert again.get("/notifications/feed?unread_only=true").json()["data"][0]["id"] == second

    assert again.post("/notifications/read-all").json()["data"] == {"marked": 1, "unread": 0}
    assert unread(me) == 0


def test_role_mailbox_is_read_separately_by_each_person(env):
    client_for, db = env
    nid = notify(db, MAILBOX, event_type="approval.requested")
    vaidehi = client_for("vaidehi@acme.test", "approver")
    other = client_for("approver2@acme.test", "approver")
    requester = client_for("anooj@acme.test", "requester")
    assert unread(vaidehi) == 1 and unread(other) == 1 and unread(requester) == 0

    vaidehi.post(f"/notifications/{nid}/read")
    assert unread(vaidehi) == 0 and unread(other) == 1


def test_cannot_mark_someone_elses_notification(env):
    client_for, db = env
    theirs = notify(db, "someone.else@acme.test")
    me = client_for("anooj@acme.test", "requester")
    assert me.post(f"/notifications/{theirs}/read").status_code == 404
    assert me.post(f"/notifications/{uuid.uuid4()}/read").status_code == 404
    assert me.post("/notifications/not-a-uuid/read").status_code == 422
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM notification_reads")
        assert cur.fetchone()[0] == 0
