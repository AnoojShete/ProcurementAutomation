"""One-time links for email verification and password reset.

The link holds a random 256-bit token. The database keeps only its SHA-256
hash, so someone who can read the database (or a backup) still can't use
a pending link. A token is:

  single-use   consume() marks it used in the same UPDATE that checks it,
               so two simultaneous clicks can't both succeed
  expiring     24 hours for verification, 30 minutes for a reset
  superseded   asking for a new link cancels the older unused ones
"""
import hashlib
import secrets
from datetime import timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

VERIFY_EMAIL = "verify_email"
RESET_PASSWORD = "reset_password"

TTL = {
    VERIFY_EMAIL: timedelta(hours=24),
    RESET_PASSWORD: timedelta(minutes=30),
}
# At most one new link per user and purpose in this window, so repeated
# "resend" / "forgot password" clicks can't flood someone's inbox.
RESEND_COOLDOWN = timedelta(seconds=60)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def issue(db: AsyncSession, user_id: str, purpose: str) -> Optional[str]:
    """Returns a new raw token (for the email link), or None when one was
    issued within the cooldown. The caller commits."""
    recent = await db.execute(
        text("SELECT 1 FROM auth_tokens WHERE user_id = :u AND purpose = :p "
             "AND created_at > now() - make_interval(secs => :cooldown) LIMIT 1"),
        {"u": user_id, "p": purpose, "cooldown": RESEND_COOLDOWN.total_seconds()},
    )
    if recent.first():
        return None
    await db.execute(
        text("UPDATE auth_tokens SET used_at = now() WHERE user_id = :u AND purpose = :p AND used_at IS NULL"),
        {"u": user_id, "p": purpose},
    )
    raw = secrets.token_urlsafe(32)
    await db.execute(
        text("INSERT INTO auth_tokens (user_id, purpose, token_hash, expires_at) "
             "VALUES (:u, :p, :h, now() + make_interval(secs => :ttl))"),
        {"u": user_id, "p": purpose, "h": hash_token(raw), "ttl": TTL[purpose].total_seconds()},
    )
    return raw


async def consume(db: AsyncSession, raw: str, purpose: str) -> Optional[str]:
    """Marks the token used and returns its user id — or None if it is
    unknown, expired, already used, or for another purpose. The caller
    commits (together with whatever the token authorised)."""
    if not raw or len(raw) > 200:
        return None
    row = await db.execute(
        text("UPDATE auth_tokens SET used_at = now() "
             "WHERE token_hash = :h AND purpose = :p AND used_at IS NULL AND expires_at > now() "
             "RETURNING user_id"),
        {"h": hash_token(raw), "p": purpose},
    )
    found = row.first()
    return str(found[0]) if found else None


async def revoke_all(db: AsyncSession, user_id: str, purpose: str) -> None:
    await db.execute(
        text("UPDATE auth_tokens SET used_at = now() WHERE user_id = :u AND purpose = :p AND used_at IS NULL"),
        {"u": user_id, "p": purpose},
    )
