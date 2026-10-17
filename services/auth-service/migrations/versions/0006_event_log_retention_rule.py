"""Business rule monitor.event_log_retention_days (FR-06): how long the
Control Panel's Kafka log keeps events. Insert-only, idempotent."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text(
        "INSERT INTO business_rules (id, rule_key, category, display_name, description, value_type, "
        "current_value, default_value, min_value, max_value) VALUES (gen_random_uuid(), "
        "'monitor.event_log_retention_days', 'risk_compliance', 'Kafka Log Retention (days)', "
        "'How long the Control Panel keeps Kafka events (summaries only)', 'int', '14'::jsonb, '14'::jsonb, 1, 365) "
        "ON CONFLICT (rule_key) DO NOTHING"
    ))


def downgrade():
    op.execute(sa.text("DELETE FROM business_rule_history WHERE rule_key = 'monitor.event_log_retention_days'"))
    op.execute(sa.text("DELETE FROM business_rules WHERE rule_key = 'monitor.event_log_retention_days'"))
