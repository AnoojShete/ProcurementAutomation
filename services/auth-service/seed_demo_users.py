#!/usr/bin/env python3
"""Seeds demo users, one per role. Idempotent (skips existing emails).

    DEMO ONLY / NOT FOR PRODUCTION USE — these are throwaway credentials
    for running the platform locally and for the end-to-end test. Never
    reuse this password scheme, or these accounts, outside a local demo.

Run inside the container:
    python seed_demo_users.py
"""
import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import async_session_factory
from app.models import User
from app.security import hash_password

DEMO_PASSWORD = "DemoPass123!"  # noqa: S105 — intentionally shared demo credential, see docstring

DEMO_USERS = [
    ("requester@demo.example.com", "requester"),
    ("approver@demo.example.com", "approver"),
    ("finance@demo.example.com", "finance"),
    ("admin@demo.example.com", "admin"),
    ("approver2@demo.example.com", "approver"),
]


async def seed():
    async with async_session_factory() as db:
        for email, role in DEMO_USERS:
            existing = (await db.execute(select(User).where(User.email == email))).scalars().first()
            if existing:
                print(f"  already exists: {email} ({role})")
                continue
            db.add(
                User(
                    id=str(uuid.uuid4()),
                    email=email,
                    hashed_password=hash_password(DEMO_PASSWORD),
                    role=role,
                    created_at=datetime.now(timezone.utc),
                )
            )
            print(f"  created: {email} ({role})")
        await db.commit()

    print("\nDEMO ONLY credentials (all use the same password):")
    for email, role in DEMO_USERS:
        print(f"  {email:28s} role={role:10s} password={DEMO_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(seed())
