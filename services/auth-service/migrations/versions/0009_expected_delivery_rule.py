"""Business rule vendor.expected_delivery_days (BR-7): an order delivered
within this many days of its contract being signed counts as on time in
the vendor's risk score. Insert-only, idempotent."""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text(
        "INSERT INTO business_rules (id, rule_key, category, display_name, description, value_type, "
        "current_value, default_value, min_value, max_value) VALUES (gen_random_uuid(), "
        "'vendor.expected_delivery_days', 'vendor_verification', 'On-Time Delivery Window (days)', "
        "'An order received within this many days of signing counts as on time in vendor risk', 'int', "
        "'14'::jsonb, '14'::jsonb, 1, 365) "
        "ON CONFLICT (rule_key) DO NOTHING"
    ))


def downgrade():
    op.execute(sa.text("DELETE FROM business_rule_history WHERE rule_key = 'vendor.expected_delivery_days'"))
    op.execute(sa.text("DELETE FROM business_rules WHERE rule_key = 'vendor.expected_delivery_days'"))
