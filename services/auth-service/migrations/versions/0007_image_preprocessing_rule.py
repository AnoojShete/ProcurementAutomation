"""Business rule document.image_preprocessing (BR-2): deskew and a capped
upscale before OCR on photos / scans. On by default because it measurably
raised field accuracy (docs/results/extraction.md). Insert-only, idempotent."""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text(
        "INSERT INTO business_rules (id, rule_key, category, display_name, description, value_type, "
        "current_value, default_value, min_value, max_value) VALUES (gen_random_uuid(), "
        "'document.image_preprocessing', 'vendor_verification', 'Clean Up Scans Before OCR', "
        "'Straighten and enlarge photographed / scanned documents before reading them', 'bool', "
        "'true'::jsonb, 'true'::jsonb, NULL, NULL) "
        "ON CONFLICT (rule_key) DO NOTHING"
    ))


def downgrade():
    op.execute(sa.text("DELETE FROM business_rule_history WHERE rule_key = 'document.image_preprocessing'"))
    op.execute(sa.text("DELETE FROM business_rules WHERE rule_key = 'document.image_preprocessing'"))
