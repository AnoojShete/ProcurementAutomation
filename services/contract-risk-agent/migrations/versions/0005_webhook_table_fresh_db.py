"""processed_webhook_events: make the legacy init.sql columns optional.

On a fresh database, shared/db/init.sql creates processed_webhook_events
with `event_id TEXT NOT NULL` and `source TEXT NOT NULL`; migration 0002
then only adds the columns this service uses (provider_event_id,
contract_id). The ProcessedWebhookEvent model never sets event_id/source,
so every e-sign webhook failed with a NOT NULL violation (500) on a fresh
install. Databases created before init.sql had the table don't have these
columns, which is why it went unnoticed. Found by the fresh-clone audit,
Sep 27.

Non-destructive: only drops NOT NULL, and only where the columns exist.

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_name = 'processed_webhook_events' AND column_name = 'event_id') THEN
            ALTER TABLE processed_webhook_events ALTER COLUMN event_id DROP NOT NULL;
          END IF;
          IF EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_name = 'processed_webhook_events' AND column_name = 'source') THEN
            ALTER TABLE processed_webhook_events ALTER COLUMN source DROP NOT NULL;
          END IF;
        END $$
    """)


def downgrade():
    # Re-adding NOT NULL would fail on rows the service has written since.
    pass
