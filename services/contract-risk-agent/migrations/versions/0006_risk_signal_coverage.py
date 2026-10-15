"""risk_scores: how many of the model's signals a score was based on, and
which hard overrides were checked / applied (FR-04). Additive and
nullable — scores written before this have no coverage recorded."""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS signals_used INTEGER")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS signals_total INTEGER")
    op.execute("ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS overrides JSONB")


def downgrade():
    op.execute("ALTER TABLE risk_scores DROP COLUMN IF EXISTS overrides")
    op.execute("ALTER TABLE risk_scores DROP COLUMN IF EXISTS signals_total")
    op.execute("ALTER TABLE risk_scores DROP COLUMN IF EXISTS signals_used")
