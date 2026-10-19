"""Revoked refresh tokens: logout ends that session for good.

Until now /auth/logout only cleared the browser's cookie, so a copied
refresh token kept working for its 7 days (QA-06). Logout now records the
token's `jti` here and /auth/refresh refuses any recorded one. A row is
only useful until the token would have expired anyway, so rows past
`expires_at` are deleted on the next logout.

Non-destructive: a new table.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-19
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth_revoked_refresh_tokens (
            jti         VARCHAR(64) PRIMARY KEY,
            user_id     UUID NOT NULL,
            expires_at  TIMESTAMPTZ NOT NULL,
            revoked_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_auth_revoked_refresh_tokens_expires_at "
               "ON auth_revoked_refresh_tokens (expires_at)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS auth_revoked_refresh_tokens")
