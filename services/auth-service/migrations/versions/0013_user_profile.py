"""User profile: a display name and a theme preference.

auth_users gains:
  display_name   shown instead of the email address wherever a person is
                 named (requests, approvals, activity); NULL falls back to
                 the email
  theme          light | dark | system, saved per account so the choice
                 follows the person across sessions and devices

Non-destructive: both columns are new, existing rows get NULL / 'system'.
Demo accounts get their names from seed_demo_users.py, not from here.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-18
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS display_name VARCHAR(100)")
    op.execute("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS theme VARCHAR(10) NOT NULL DEFAULT 'system'")
    op.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_auth_users_theme') THEN
            ALTER TABLE auth_users ADD CONSTRAINT ck_auth_users_theme
              CHECK (theme IN ('light', 'dark', 'system'));
          END IF;
        END $$
    """)


def downgrade():
    op.execute("ALTER TABLE auth_users DROP CONSTRAINT IF EXISTS ck_auth_users_theme")
    op.execute("ALTER TABLE auth_users DROP COLUMN IF EXISTS theme")
    op.execute("ALTER TABLE auth_users DROP COLUMN IF EXISTS display_name")
