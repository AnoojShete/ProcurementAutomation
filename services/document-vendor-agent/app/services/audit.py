import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import AuditLog


async def write_audit_log(db: AsyncSession, entity_type: str, entity_id: str, action: str, payload: dict):
    """Append an audit_log row using only the columns shared/db/init.sql
    already defines (entity_id, entity_type, action, payload, created_at) —
    no migration needed since these columns pre-date this service. Any
    extra detail (verifier, channel, filename hash, ...) goes inside
    `payload`, per the platform convention (see contract-risk-agent's
    app/services/audit.py)."""
    entry = AuditLog(
        id=str(uuid.uuid4()),
        entity_id=str(entity_id) if entity_id else None,
        entity_type=entity_type,
        action=action,
        payload=payload,
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    await db.flush()
