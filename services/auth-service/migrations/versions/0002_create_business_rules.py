"""Create business_rules and business_rule_history tables, and seed initial rules.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-25
"""
import json
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SEED_RULES = [
    # Approval
    {
        "rule_key": "approval.spend_tiers",
        "category": "approval",
        "display_name": "Spend Tiers",
        "description": "Approval tiers with amount limits and required roles",
        "value_type": "json",
        "current_value": [
            {"tier_name": "auto", "min_amount": 0, "max_amount": 500, "required_roles": []},
            {"tier_name": "manager", "min_amount": 500, "max_amount": 5000, "required_roles": ["dept_manager"]},
            {"tier_name": "manager+finance", "min_amount": 5000, "max_amount": None, "required_roles": ["dept_manager", "finance_head"]}
        ],
        "default_value": [
            {"tier_name": "auto", "min_amount": 0, "max_amount": 500, "required_roles": []},
            {"tier_name": "manager", "min_amount": 500, "max_amount": 5000, "required_roles": ["dept_manager"]},
            {"tier_name": "manager+finance", "min_amount": 5000, "max_amount": None, "required_roles": ["dept_manager", "finance_head"]}
        ],
        "min_value": None,
        "max_value": None,
    },
    {
        "rule_key": "approval.sla_escalation_hours",
        "category": "approval",
        "display_name": "SLA Escalation Hours",
        "description": "Hours before an unapproved request escalates",
        "value_type": "int",
        "current_value": 48,
        "default_value": 48,
        "min_value": 1,
        "max_value": 168,
    },
    # Budget
    {
        "rule_key": "budget.fiscal_period_type",
        "category": "budget",
        "display_name": "Fiscal Period Type",
        "description": "Fiscal period division type ('quarterly' or 'annual')",
        "value_type": "json",
        "current_value": "quarterly",
        "default_value": "quarterly",
        "min_value": None,
        "max_value": None,
    },
    {
        "rule_key": "budget.over_budget_requires_finance_approval",
        "category": "budget",
        "display_name": "Over-Budget Requires Finance Approval",
        "description": "Require finance approval when purchase exceeds remaining budget",
        "value_type": "bool",
        "current_value": True,
        "default_value": True,
        "min_value": None,
        "max_value": None,
    },
    # Vendor Verification
    {
        "rule_key": "vendor.petty_tier_max_amount",
        "category": "vendor_verification",
        "display_name": "Petty Tier Max Amount",
        "description": "Maximum threshold for petty spend tier",
        "value_type": "decimal",
        "current_value": 5000,
        "default_value": 5000,
        "min_value": 0,
        "max_value": None,
    },
    {
        "rule_key": "vendor.standard_tier_max_amount",
        "category": "vendor_verification",
        "display_name": "Standard Tier Max Amount",
        "description": "Maximum threshold for standard spend tier",
        "value_type": "decimal",
        "current_value": 50000,
        "default_value": 50000,
        "min_value": 0,
        "max_value": None,
    },
    {
        "rule_key": "vendor.structuring_detection_window_days",
        "category": "vendor_verification",
        "display_name": "Structuring Detection Window Days",
        "description": "Lookback window in days to detect invoice structuring",
        "value_type": "int",
        "current_value": 90,
        "default_value": 90,
        "min_value": 1,
        "max_value": None,
    },
    {
        "rule_key": "document.invoice_po_match_tolerance_pct",
        "category": "vendor_verification",
        "display_name": "Invoice-PO Match Tolerance Pct",
        "description": "Tolerance percentage for matching invoice amounts to PO totals",
        "value_type": "float",
        "current_value": 0.05,
        "default_value": 0.05,
        "min_value": 0,
        "max_value": 0.5,
    },
    {
        "rule_key": "document.duplicate_invoice_amount_tolerance_pct",
        "category": "vendor_verification",
        "display_name": "Duplicate Invoice Amount Tolerance Pct",
        "description": "Tolerance percentage for duplicate invoice detection",
        "value_type": "float",
        "current_value": 0.02,
        "default_value": 0.02,
        "min_value": 0,
        "max_value": 0.5,
    },
    {
        "rule_key": "document.duplicate_invoice_date_window_days",
        "category": "vendor_verification",
        "display_name": "Duplicate Invoice Date Window Days",
        "description": "Date window in days for duplicate invoice detection",
        "value_type": "int",
        "current_value": 7,
        "default_value": 7,
        "min_value": 1,
        "max_value": None,
    },
    {
        "rule_key": "document.confidence_review_threshold",
        "category": "vendor_verification",
        "display_name": "Confidence Review Threshold",
        "description": "Extraction confidence score threshold below which human review is triggered",
        "value_type": "float",
        "current_value": 0.8,
        "default_value": 0.8,
        "min_value": 0,
        "max_value": 1,
    },
    {
        "rule_key": "document.extraction_fallback_confidence_threshold",
        "category": "vendor_verification",
        "display_name": "Extraction Fallback Confidence Threshold",
        "description": "Confidence threshold to trigger layout/OCR fallback models",
        "value_type": "float",
        "current_value": 0.5,
        "default_value": 0.5,
        "min_value": 0,
        "max_value": 1,
    },
    {
        "rule_key": "contract.clause_extraction_fallback_threshold",
        "category": "vendor_verification",
        "display_name": "Clause Extraction Fallback Threshold",
        "description": "Confidence threshold to fallback during contract clause extraction",
        "value_type": "float",
        "current_value": 0.4,
        "default_value": 0.4,
        "min_value": 0,
        "max_value": 1,
    },
    # License Usage
    {
        "rule_key": "license.anomaly_watch_threshold",
        "category": "license_usage",
        "display_name": "Anomaly Watch Threshold",
        "description": "Threshold score for placing a license on watch status",
        "value_type": "float",
        "current_value": 0.5,
        "default_value": 0.5,
        "min_value": 0,
        "max_value": 1,
    },
    {
        "rule_key": "license.anomaly_anomalous_threshold",
        "category": "license_usage",
        "display_name": "Anomaly Anomalous Threshold",
        "description": "Threshold score for flagging a license as anomalous for reclamation",
        "value_type": "float",
        "current_value": 0.75,
        "default_value": 0.75,
        "min_value": 0,
        "max_value": 1,
    },
    {
        "rule_key": "license.reclaim_cooldown_days",
        "category": "license_usage",
        "display_name": "Reclaim Cooldown Days",
        "description": "Days to wait before attempting reclamation again after decline",
        "value_type": "int",
        "current_value": 45,
        "default_value": 45,
        "min_value": 1,
        "max_value": None,
    },
    {
        "rule_key": "license.grace_period_days",
        "category": "license_usage",
        "display_name": "Grace Period Days",
        "description": "Days allowed before pending reclamation completes",
        "value_type": "int",
        "current_value": 7,
        "default_value": 7,
        "min_value": 1,
        "max_value": None,
    },
    {
        "rule_key": "license.false_positive_decline_count",
        "category": "license_usage",
        "display_name": "False Positive Decline Count",
        "description": "Number of declines within window to mark model as false positive",
        "value_type": "int",
        "current_value": 2,
        "default_value": 2,
        "min_value": 1,
        "max_value": None,
    },
    {
        "rule_key": "license.false_positive_window_months",
        "category": "license_usage",
        "display_name": "False Positive Window Months",
        "description": "Window in months to count license reclaim declines",
        "value_type": "int",
        "current_value": 6,
        "default_value": 6,
        "min_value": 1,
        "max_value": None,
    },
    {
        "rule_key": "license.minimum_history_days",
        "category": "license_usage",
        "display_name": "Minimum History Days",
        "description": "Minimum active days before evaluating license usage anomaly",
        "value_type": "int",
        "current_value": 30,
        "default_value": 30,
        "min_value": 1,
        "max_value": None,
    },
    # Risk & Compliance
    {
        "rule_key": "risk.sanctions_match_threshold_pct",
        "category": "risk_compliance",
        "display_name": "Sanctions Match Threshold Pct",
        "description": "Match score percentage to flag vendor sanctions match",
        "value_type": "float",
        "current_value": 90.0,
        "default_value": 90.0,
        "min_value": 50,
        "max_value": 100,
    },
    {
        "rule_key": "risk.adverse_media_negative_confidence",
        "category": "risk_compliance",
        "display_name": "Adverse Media Negative Confidence",
        "description": "Sentiment confidence threshold for adverse media detection",
        "value_type": "float",
        "current_value": 0.7,
        "default_value": 0.7,
        "min_value": 0,
        "max_value": 1,
    },
    {
        "rule_key": "risk.adverse_media_article_count_threshold",
        "category": "risk_compliance",
        "display_name": "Adverse Media Article Count Threshold",
        "description": "Number of negative articles needed to trigger adverse media risk alert",
        "value_type": "int",
        "current_value": 2,
        "default_value": 2,
        "min_value": 1,
        "max_value": None,
    },
    {
        "rule_key": "risk.adverse_media_lookback_days",
        "category": "risk_compliance",
        "display_name": "Adverse Media Lookback Days",
        "description": "Lookback window in days for adverse media search",
        "value_type": "int",
        "current_value": 90,
        "default_value": 90,
        "min_value": 1,
        "max_value": None,
    },
    {
        "rule_key": "risk.psi_moderate_threshold",
        "category": "risk_compliance",
        "display_name": "PSI Moderate Threshold",
        "description": "Population Stability Index threshold for moderate risk drift",
        "value_type": "float",
        "current_value": 0.1,
        "default_value": 0.1,
        "min_value": 0,
        "max_value": None,
    },
    {
        "rule_key": "risk.psi_significant_threshold",
        "category": "risk_compliance",
        "display_name": "PSI Significant Threshold",
        "description": "Population Stability Index threshold for significant risk drift",
        "value_type": "float",
        "current_value": 0.2,
        "default_value": 0.2,
        "min_value": 0,
        "max_value": 1,
    },
    {
        "rule_key": "risk.contract_renewal_milestones_days",
        "category": "risk_compliance",
        "display_name": "Contract Renewal Milestones Days",
        "description": "Days before renewal to trigger notification alerts",
        "value_type": "json",
        "current_value": [60, 30, 15],
        "default_value": [60, 30, 15],
        "min_value": None,
        "max_value": None,
    },
]


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS business_rules (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          rule_key VARCHAR(255) NOT NULL UNIQUE,
          category VARCHAR(50) NOT NULL,
          display_name VARCHAR(255) NOT NULL,
          description TEXT NOT NULL,
          value_type VARCHAR(20) NOT NULL,
          current_value JSONB NOT NULL,
          default_value JSONB NOT NULL,
          min_value NUMERIC NULL,
          max_value NUMERIC NULL,
          updated_by UUID NULL,
          updated_at TIMESTAMPTZ NULL
        );

        CREATE TABLE IF NOT EXISTS business_rule_history (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          rule_key VARCHAR(255) NOT NULL,
          old_value JSONB NULL,
          new_value JSONB NOT NULL,
          changed_by VARCHAR(255) NULL,
          changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          justification TEXT NOT NULL
        );
        """
    )

    business_rules_table = sa.table(
        "business_rules",
        sa.column("id", sa.String),
        sa.column("rule_key", sa.String),
        sa.column("category", sa.String),
        sa.column("display_name", sa.String),
        sa.column("description", sa.String),
        sa.column("value_type", sa.String),
        sa.column("current_value", JSONB),
        sa.column("default_value", JSONB),
        sa.column("min_value", sa.Numeric),
        sa.column("max_value", sa.Numeric),
    )

    rows = []
    for r in SEED_RULES:
        rows.append({
            "id": str(uuid.uuid4()),
            "rule_key": r["rule_key"],
            "category": r["category"],
            "display_name": r["display_name"],
            "description": r["description"],
            "value_type": r["value_type"],
            "current_value": r["current_value"],
            "default_value": r["default_value"],
            "min_value": r["min_value"],
            "max_value": r["max_value"],
        })

    op.bulk_insert(business_rules_table, rows)


def downgrade():
    op.execute("DROP TABLE IF EXISTS business_rule_history")
    op.execute("DROP TABLE IF EXISTS business_rules")
