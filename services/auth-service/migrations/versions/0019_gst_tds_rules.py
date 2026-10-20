"""Feature expansion Phase 4: GST and TDS compliance (document-vendor-agent's
tax_check.py, approval-inventory-agent's tds_service.py). Insert-only,
idempotent.

Values are the ones current in October 2026 and must be confirmed by the
finance team or a chartered accountant. Defaults change no existing flow:
an invoice without a GST breakdown is only noted (gst.require_breakdown
off), and the e-invoice rule only applies to vendors whose turnover finance
has entered.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

SECTIONS = '{"hardware": "194Q", "software": "194J(b)", "saas": "194J(a)", "services": "194J(a)"}'

# (key, category, name, description, type, value, min, max)
RULES = [
    ("gst.buyer_gstin", "tax", "Our GSTIN",
     "The buyer's GSTIN: invoices must be addressed to it (input tax credit), and it decides whether a supply is "
     "within the state (CGST + SGST) or between states (IGST)", "json", '"29AAACA1234B1ZE"', None, None),
    ("gst.tax_tolerance_inr", "tax", "GST Rounding Tolerance",
     "How far, in rupees, GST amounts and totals may be off before the invoice's tax check fails", "float", "1",
     0, 1000),
    ("gst.require_breakdown", "tax", "Require a GST Breakdown",
     "An Indian invoice that shows no CGST, SGST or IGST amounts goes to review (off: it is only noted)",
     "bool", "false", None, None),
    ("gst.einvoice_required_turnover_inr", "tax", "E-invoice Turnover Threshold",
     "A vendor whose yearly turnover (entered on its tax profile) is above this must send e-invoices with a signed "
     "QR code; an invoice without one goes to review", "float", "50000000", 0, 10000000000),
    ("tds.category_sections", "tax", "TDS Section per Category",
     "The TDS section used for each purchase category (hardware, software, saas, services) when the vendor's tax "
     "profile names none", "json", SECTIONS, None, None),
    ("msme.payment_days", "tax", "MSME Payment Deadline (days)",
     "A micro or small enterprise's invoice must be paid within this many days of acceptance (Income-tax Act "
     "s. 43B(h): 45 at most)", "int", "45", 1, 45),
    ("msme.warning_days", "tax", "MSME Deadline Warning (days)",
     "An unpaid MSME invoice is shown as due soon this many days before its deadline", "int", "7", 0, 45),
]


def upgrade():
    for key, category, name, description, vtype, value, lo, hi in RULES:
        op.execute(sa.text(
            "INSERT INTO business_rules (id, rule_key, category, display_name, description, value_type, "
            "current_value, default_value, min_value, max_value) VALUES (gen_random_uuid(), "
            ":key, :category, :name, :description, :vtype, CAST(:value AS jsonb), CAST(:value AS jsonb), :lo, :hi) "
            "ON CONFLICT (rule_key) DO NOTHING"
        ).bindparams(key=key, category=category, name=name, description=description, vtype=vtype,
                     value=value, lo=lo, hi=hi))


def downgrade():
    for key, *_ in RULES:
        op.execute(sa.text("DELETE FROM business_rule_history WHERE rule_key = :key").bindparams(key=key))
        op.execute(sa.text("DELETE FROM business_rules WHERE rule_key = :key").bindparams(key=key))
