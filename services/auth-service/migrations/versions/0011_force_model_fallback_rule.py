"""Business rule dev.force_model_fallback (FR-08): routers whose primary
model is treated as failed so the fallback can be shown on demand.
Honoured only with APP_ENV=development. Insert-only, idempotent."""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text(
        "INSERT INTO business_rules (id, rule_key, category, display_name, description, value_type, "
        "current_value, default_value, min_value, max_value) VALUES (gen_random_uuid(), "
        "'dev.force_model_fallback', 'risk_compliance', 'Force Model Fallback (demo)', "
        "'Development only: routers whose primary model is treated as failed — \"extraction\", \"clauses\"', "
        "'json', '[]'::jsonb, '[]'::jsonb, NULL, NULL) "
        "ON CONFLICT (rule_key) DO NOTHING"
    ))


def downgrade():
    op.execute(sa.text("DELETE FROM business_rule_history WHERE rule_key = 'dev.force_model_fallback'"))
    op.execute(sa.text("DELETE FROM business_rules WHERE rule_key = 'dev.force_model_fallback'"))
