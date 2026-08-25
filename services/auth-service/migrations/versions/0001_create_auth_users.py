"""Create auth_users table

Revision ID: 0001
Revises:
Create Date: 2026-08-25
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_users (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          email VARCHAR(255) NOT NULL UNIQUE,
          hashed_password VARCHAR(255) NOT NULL,
          role VARCHAR(20) NOT NULL,
          created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS auth_users")
