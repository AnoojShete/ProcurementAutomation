"""FR-32: licence-anomaly thresholds chosen from the evaluation
(docs/results/licence-anomaly.md — watch: highest score with recall >= 0.90,
anomalous: lowest score with precision >= 0.90, on validation data).
Updates the defaults, and the current value only where an admin hasn't
changed it from the old default."""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

CHANGES = [("license.anomaly_watch_threshold", 0.5, 0.34),
           ("license.anomaly_anomalous_threshold", 0.75, 0.39)]


def _apply(pairs):
    for key, old, new in pairs:
        op.execute(sa.text(
            "UPDATE business_rules SET current_value = CAST(:new AS jsonb) "
            "WHERE rule_key = :key AND current_value = CAST(:old AS jsonb)"
        ).bindparams(key=key, old=str(old), new=str(new)))
        op.execute(sa.text(
            "UPDATE business_rules SET default_value = CAST(:new AS jsonb) WHERE rule_key = :key"
        ).bindparams(key=key, new=str(new)))


def upgrade():
    _apply(CHANGES)


def downgrade():
    _apply([(key, new, old) for key, old, new in CHANGES])
