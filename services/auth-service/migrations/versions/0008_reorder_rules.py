"""Business rules for reorder suggestions (BR-5): the default reorder point
and reorder quantity, as a % of an item's total stock, used when the item
has no value of its own. Insert-only, idempotent."""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

RULES = [
    ("inventory.reorder_point_pct", "Default Reorder Point (% of stock)",
     "Reorder when the stock left after backorders falls to this share of the item's total", 20),
    ("inventory.reorder_quantity_pct", "Default Reorder Quantity (% of stock)",
     "How much to order on top of what is owed, as a share of the item's total", 25),
]


def upgrade():
    for key, name, description, value in RULES:
        op.execute(sa.text(
            "INSERT INTO business_rules (id, rule_key, category, display_name, description, value_type, "
            "current_value, default_value, min_value, max_value) VALUES (gen_random_uuid(), "
            ":key, 'budget', :name, :description, 'int', CAST(:value AS jsonb), CAST(:value AS jsonb), 1, 100) "
            "ON CONFLICT (rule_key) DO NOTHING"
        ).bindparams(key=key, name=name, description=description, value=str(value)))


def downgrade():
    for key, *_ in RULES:
        op.execute(sa.text("DELETE FROM business_rule_history WHERE rule_key = :key").bindparams(key=key))
        op.execute(sa.text("DELETE FROM business_rules WHERE rule_key = :key").bindparams(key=key))
