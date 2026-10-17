"""Account lifecycle: email verification, password reset, lockout,
session invalidation.

auth_users gains:
  email_verified_at    login requires a confirmed address
  is_active            an admin can switch an account off
  token_version        bumped on password change/reset, deactivation or
                       role change; refresh tokens carry it, so older
                       sessions stop refreshing (sign-out everywhere)
  password_changed_at, last_login_at
auth_tokens            single-use, expiring verification/reset tokens —
                       only a SHA-256 of the token is stored
auth_login_attempts    failed logins per email address (lockout), kept for
                       unknown addresses too so lockout doesn't reveal
                       which accounts exist

Non-destructive: existing users are marked verified (they predate
verification; otherwise nobody could log in) and keep their passwords
(bcrypt hashes are upgraded to argon2id at their next login).

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ")
    op.execute("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true")
    op.execute("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ")
    op.execute("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ")
    op.execute("UPDATE auth_users SET email_verified_at = COALESCE(created_at, now()) WHERE email_verified_at IS NULL")
    op.execute("ALTER TABLE auth_users ALTER COLUMN created_at SET NOT NULL")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_auth_users_email_lower ON auth_users (lower(email))")
    op.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_auth_users_role') THEN
            ALTER TABLE auth_users ADD CONSTRAINT ck_auth_users_role
              CHECK (role IN ('requester', 'approver', 'finance', 'admin'));
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_auth_users_email_lower') THEN
            ALTER TABLE auth_users ADD CONSTRAINT ck_auth_users_email_lower CHECK (email = lower(email));
          END IF;
        END $$
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth_tokens (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
          purpose VARCHAR(20) NOT NULL CHECK (purpose IN ('verify_email', 'reset_password')),
          token_hash CHAR(64) NOT NULL UNIQUE,
          expires_at TIMESTAMPTZ NOT NULL,
          used_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_purpose ON auth_tokens (user_id, purpose)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth_login_attempts (
          email VARCHAR(255) PRIMARY KEY CHECK (email = lower(email)),
          failed_count INTEGER NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
          window_started_at TIMESTAMPTZ,
          locked_until TIMESTAMPTZ,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS auth_login_attempts")
    op.execute("DROP TABLE IF EXISTS auth_tokens")
    op.execute("DROP INDEX IF EXISTS uq_auth_users_email_lower")
    op.execute("ALTER TABLE auth_users DROP CONSTRAINT IF EXISTS ck_auth_users_role")
    op.execute("ALTER TABLE auth_users DROP CONSTRAINT IF EXISTS ck_auth_users_email_lower")
    for col in ("email_verified_at", "is_active", "token_version", "password_changed_at", "last_login_at"):
        op.execute(f"ALTER TABLE auth_users DROP COLUMN IF EXISTS {col}")
