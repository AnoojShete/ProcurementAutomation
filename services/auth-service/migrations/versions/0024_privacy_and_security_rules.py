"""Prompt 12B & 12C: Business rules for Privacy (minimisation, retention, DSR, cross-border)
and Security (OWASP Top 10 rate limiting, sensitive flow daily caps).

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-02
"""
import json
from alembic import op
import sqlalchemy as sa

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

RULES = [
    # Privacy rules (Prompt 12B)
    ("privacy.store_email_bodies", "privacy", "Store Email Bodies in Log",
     "When false, only metadata, recipient, timestamps and variable hash are stored, never the body",
     "bool", json.dumps(False), None, None),
    ("privacy.retention_notification_log_months", "privacy", "Notification Log Retention (months)",
     "Months to retain delivery records in notification_log before automated purge",
     "int", json.dumps(12), 1, 60),
    ("privacy.retention_email_action_records_months", "privacy", "Email Action Token Retention (months)",
     "Months to retain email approval action token logs before anonymization",
     "int", json.dumps(12), 1, 60),
    ("privacy.retention_ip_user_agent_months", "privacy", "IP & User-Agent Retention (months)",
     "Months before client IP is truncated to /24 subnet and user-agent string is purged",
     "int", json.dumps(12), 1, 60),
    ("privacy.retention_rating_comment_months", "privacy", "Rating & Comment Retention (months)",
     "Months to retain vendor scorecard reviews and approval comments before scrub",
     "int", json.dumps(36), 6, 120),
    ("privacy.retention_raw_response_months", "privacy", "Raw API Response Retention (months)",
     "Months to retain raw external API responses (GST registrant details) before deletion",
     "int", json.dumps(24), 1, 60),
    ("privacy.audit_retention_months", "privacy", "Statutory Audit Log Retention (months)",
     "Months to retain statutory financial and transaction audit records (legal/finance mandate)",
     "int", json.dumps(84), 12, 120),
    ("privacy.no_personal_data_in_subject", "privacy", "Block Personal Data from Email Subjects",
     "When true, personal data placeholders and names/emails are blocked from email subjects",
     "bool", json.dumps(True), None, None),
    ("privacy.dsr_days", "privacy", "Data Subject Request Deadline (days)",
     "Statutory days allowed to fulfill a Data Subject Request (GDPR/DPDP default 30 days)",
     "int", json.dumps(30), 7, 90),
    ("privacy.allowed_processor_regions", "privacy", "Allowed Data Processor Regions",
     "Permitted geographical regions for external sub-processors and cloud mail relays",
     "json", json.dumps(["EU", "EEA", "UK", "IN", "US"]), None, None),
    ("privacy.eu_contacts_require_region_check", "privacy", "Enforce EU Cross-Border Processor Check",
     "When true, non-essential emails to EU/EEA/UK recipients are blocked if processor region is unallowed",
     "bool", json.dumps(True), None, None),
    ("privacy.regime_by_country", "privacy", "Privacy Legal Regime Mapping by Country",
     "Maps ISO country codes to applicable privacy regimes (notice wording and statutory timers)",
     "json", json.dumps({
         "IN": "DPDP", "GB": "UK_GDPR", "US": "US_CANSPAM", "CA": "CASL", "AU": "SPAM_ACT",
         "DE": "EU_GDPR", "FR": "EU_GDPR", "IE": "EU_GDPR", "NL": "EU_GDPR", "IT": "EU_GDPR", "ES": "EU_GDPR"
     }), None, None),
    ("privacy.max_recipients_per_message", "privacy", "Max Recipients Per Email Message",
     "Maximum total recipients (primary + CC) allowed on an operational email",
     "int", json.dumps(10), 1, 50),
    ("privacy.promotional_words_blocklist", "privacy", "Promotional Vocabulary Blocklist",
     "List of words forbidden in email templates to prevent accidental marketing content",
     "json", json.dumps([
         "discount", "deal", "promo", "special offer", "newsletter", "marketing",
         "free trial", "subscribe now", "buy now", "limited time offer"
     ]), None, None),
    ("privacy.internal_cc_domain_allowlist", "privacy", "Internal CC Domain Allowlist",
     "Domain allowlist for free-text CC on internal-audience notification templates",
     "json", json.dumps(["procurement.local", "company.com"]), None, None),

    # Security rules (Prompt 12C - OWASP Top 10)
    ("security.rate_limit_anonymous_per_min", "security", "Anonymous Rate Limit (req/min/IP)",
     "Rate limit for unauthenticated endpoints per client IP (hard minimum: 10)",
     "int", json.dumps(30), 10, 100),
    ("security.rate_limit_read_per_min", "security", "Standard Read Rate Limit (req/min/user)",
     "Rate limit for standard read operations per authenticated user (hard minimum: 50)",
     "int", json.dumps(300), 50, 1000),
    ("security.rate_limit_write_per_min", "security", "Standard Write Rate Limit (req/min/user)",
     "Rate limit for state-modifying write operations per user (hard minimum: 10)",
     "int", json.dumps(60), 10, 300),
    ("security.rate_limit_expensive_per_min", "security", "Expensive Operation Rate Limit (req/min)",
     "Rate limit for heavy computation (recompute, what-if, export, batch upload) per user",
     "int", json.dumps(10), 2, 50),
    ("security.concurrent_expensive_per_user", "security", "Max Concurrent Expensive Operations",
     "Maximum concurrent expensive requests running simultaneously per user",
     "int", json.dumps(2), 1, 10),
    ("security.rate_limit_recompute_per_vendor_min", "security", "Vendor Recompute Rate Limit (req/min)",
     "Maximum score recalculations allowed per individual vendor per minute",
     "int", json.dumps(1), 1, 10),
    ("security.sensitive_flow_daily_cap_bulk_approval", "security", "Daily Cap: Bulk Approvals",
     "Maximum bulk approval requests one user can execute per calendar day",
     "int", json.dumps(50), 5, 500),
    ("security.sensitive_flow_daily_cap_vendor_onboard", "security", "Daily Cap: Vendor Onboarding",
     "Maximum vendor onboarding submissions allowed per user per day",
     "int", json.dumps(50), 5, 500),
    ("security.sensitive_flow_daily_cap_email_actions", "security", "Daily Cap: Email Actions",
     "Maximum email decision link clicks allowed per user per day",
     "int", json.dumps(100), 10, 1000),
    ("security.sensitive_flow_daily_cap_bank_change", "security", "Daily Cap: Bank Changes",
     "Maximum vendor bank account updates allowed per user per day",
     "int", json.dumps(20), 2, 100),
    ("security.sensitive_flow_alert_threshold_multiplier", "security", "Sensitive Flow Velocity Alert Multiplier",
     "Velocity multiplier above normal rate that triggers automated security alert",
     "float", json.dumps(3.0), 1.5, 10.0),
    ("security.ip_block_violation_threshold", "security", "IP Temporary Block Violation Threshold",
     "Number of rate limit breaches within window before client IP is temporarily blocked",
     "int", json.dumps(20), 5, 100),
    ("security.ip_block_window_minutes", "security", "IP Violation Window (minutes)",
     "Time window in minutes to accumulate rate limit violations",
     "int", json.dumps(10), 1, 60),
    ("security.ip_block_duration_minutes", "security", "IP Block Duration (minutes)",
     "Duration in minutes that an offending IP address remains blocked in Redis",
     "int", json.dumps(15), 5, 1440),
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
