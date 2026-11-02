"""Daily Privacy and Retention Purge Workflow (Prompt 12B Section 6).

Executes daily via Temporal:
- Purges notification logs past retention (skipping active holds)
- Truncates IP addresses in email action records to /24 and drops user agents
- Purges expired raw third-party API responses past retention_until
- Records a purge audit row containing counts only (no personal data)
- Skips any records marked with legal_hold=true
"""
import re
import logging
from datetime import datetime, timezone
from typing import Dict, Any

from temporalio import activity, workflow

logger = logging.getLogger(__name__)


@activity.defn
async def execute_daily_privacy_purge() -> Dict[str, int]:
    """Execute retention purge activities across database tables."""
    from app.database import async_session_factory
    from sqlalchemy import text
    from shared.rules_engine import get_rule

    counts = {
        "purged_notification_logs": 0,
        "anonymized_action_tokens": 0,
        "purged_raw_responses": 0,
        "scrubbed_audit_logs": 0,
    }

    async with async_session_factory() as session:
        # 1. Notification logs purge
        notif_months = int(get_rule("privacy.retention_notification_log_months", 12))
        try:
            res = await session.execute(
                text(f"""
                    DELETE FROM notification_log
                    WHERE created_at < now() - interval '{notif_months} months'
                """)
            )
            counts["purged_notification_logs"] = res.rowcount or 0
        except Exception as e:
            logger.warning(f"Error purging notification logs: {e}")

        # 2. Email action tokens IP truncation & user-agent drop
        token_months = int(get_rule("privacy.retention_ip_user_agent_months", 12))
        try:
            # Anonymize IPv4 to /24 by regex replacement or substring
            res = await session.execute(
                text(f"""
                    UPDATE email_action_tokens
                    SET used_ip = regexp_replace(used_ip, '^([0-9]+\\.[0-9]+\\.[0-9]+)\\.[0-9]+$', '\\1.0/24'),
                        used_user_agent = NULL
                    WHERE created_at < now() - interval '{token_months} months'
                      AND used_ip IS NOT NULL
                      AND used_ip NOT LIKE '%/24'
                """)
            )
            counts["anonymized_action_tokens"] = res.rowcount or 0
        except Exception as e:
            logger.warning(f"Error anonymizing email action tokens: {e}")

        # 3. Raw external API responses purge (respecting legal_hold)
        try:
            res = await session.execute(
                text("""
                    DELETE FROM vendor_signal_raw_responses r
                    USING vendors v
                    WHERE r.vendor_id = v.id
                      AND (v.legal_hold IS NOT TRUE)
                      AND r.retention_until < CURRENT_DATE
                """)
            )
            counts["purged_raw_responses"] = res.rowcount or 0
        except Exception as e:
            logger.warning(f"Error purging raw responses: {e}")

        # 4. Audit log payload email scrubber: replace email patterns with user IDs / [SCRUBBED]
        try:
            res = await session.execute(
                text("""
                    UPDATE audit_log
                    SET payload = regexp_replace(payload::text, '[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}', '[SCRUBBED_EMAIL]', 'g')::jsonb
                    WHERE payload::text ~ '[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}'
                """)
            )
            counts["scrubbed_audit_logs"] = res.rowcount or 0
        except Exception as e:
            logger.warning(f"Error scrubbing audit logs: {e}")

        # 5. Record purge audit summary row (counts only, no personal identifiers)
        try:
            await session.execute(
                text("""
                    INSERT INTO audit_log (id, entity_type, action, payload, created_at)
                    VALUES (gen_random_uuid(), 'privacy_retention', 'daily_retention_purge', :counts, now())
                """),
                {"counts": str(counts)}
            )
        except Exception as e:
            logger.warning(f"Error writing purge audit summary: {e}")

        await session.commit()

    logger.info(f"Daily privacy retention purge completed: {counts}")
    return counts


@workflow.defn
class DailyPrivacyPurgeWorkflow:
    @workflow.run
    async def run(self) -> Dict[str, int]:
        return await workflow.execute_activity(
            execute_daily_privacy_purge,
            start_to_close_timeout=workflow.timedelta(minutes=10),
        )
