"""Temporary lockout after repeated wrong passwords.

After MAX_FAILURES wrong passwords for one email address within WINDOW,
that address can't log in for LOCK_DURATION — even with the right
password. This stops online password guessing against one account; the
gateway's per-IP rate limit (infra/nginx/nginx.conf) slows guessing
across many accounts.

Counted per email address, whether or not an account exists: otherwise
"locked" vs "wrong password" would reveal which addresses are registered.
A successful login or a password reset clears the counter.
"""
import os
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MAX_FAILURES = int(os.environ.get("AUTH_LOCKOUT_THRESHOLD", "5"))
WINDOW = timedelta(minutes=int(os.environ.get("AUTH_LOCKOUT_WINDOW_MINUTES", "15")))
LOCK_DURATION = timedelta(minutes=int(os.environ.get("AUTH_LOCKOUT_MINUTES", "15")))

LOCKED_MESSAGE = ("Too many failed sign-in attempts. Try again in a few minutes, "
                  "or reset your password.")


async def locked_until(db: AsyncSession, email: str) -> Optional[datetime]:
    row = (await db.execute(
        text("SELECT locked_until FROM auth_login_attempts WHERE email = :e AND locked_until > now()"),
        {"e": email},
    )).first()
    return row[0] if row else None


# One atomic statement, so parallel guesses can't slip past the counter.
# The count starts over when the window has passed or a lock has expired.
_RECORD_FAILURE = text("""
    INSERT INTO auth_login_attempts AS a (email, failed_count, window_started_at, updated_at)
    VALUES (:e, 1, now(), now())
    ON CONFLICT (email) DO UPDATE SET
      failed_count = CASE WHEN a.window_started_at < now() - make_interval(secs => :window)
                           OR a.locked_until <= now()
                          THEN 1 ELSE a.failed_count + 1 END,
      window_started_at = CASE WHEN a.window_started_at < now() - make_interval(secs => :window)
                                OR a.locked_until <= now()
                               THEN now() ELSE a.window_started_at END,
      locked_until = CASE WHEN a.locked_until <= now() THEN NULL ELSE a.locked_until END,
      updated_at = now()
    RETURNING failed_count
""")


async def record_failure(db: AsyncSession, email: str) -> bool:
    """Counts one failure; returns True when this failure locks the address.
    The caller commits."""
    count = (await db.execute(_RECORD_FAILURE, {"e": email, "window": WINDOW.total_seconds()})).scalar_one()
    if count >= MAX_FAILURES:
        await db.execute(
            text("UPDATE auth_login_attempts SET locked_until = now() + make_interval(secs => :lock) WHERE email = :e"),
            {"e": email, "lock": LOCK_DURATION.total_seconds()},
        )
        return True
    return False


async def clear(db: AsyncSession, email: str) -> None:
    await db.execute(text("DELETE FROM auth_login_attempts WHERE email = :e"), {"e": email})
