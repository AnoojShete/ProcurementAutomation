"""Read-only query helper for the ONE shared `audit_log` table
(shared/db/init.sql), written by document-vendor-agent, approval-inventory-
agent, and contract-risk-agent via each service's own AuditLog ORM model
and write_audit_log() helper.

Column names differ slightly between services' own migrations
(document-vendor-agent / contract-risk-agent use `payload`;
approval-inventory-agent uses `performed_by`/`details` — see each
service's migrations/0001_schema_extensions.sql), so this helper takes
the caller's own model class rather than hardcoding one.
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

MAX_LIMIT = 500


async def list_audit_log(
    db: AsyncSession,
    model,
    *,
    entity_types: Optional[List[str]] = None,
    entity_id: Optional[str] = None,
    action: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = 100,
) -> list:
    stmt = select(model).order_by(model.created_at.desc()).limit(min(limit, MAX_LIMIT))
    if entity_types:
        stmt = stmt.where(model.entity_type.in_(entity_types))
    if entity_id:
        stmt = stmt.where(model.entity_id == entity_id)
    if action:
        stmt = stmt.where(model.action == action)
    if since:
        stmt = stmt.where(model.created_at >= since)
    if until:
        stmt = stmt.where(model.created_at <= until)
    result = await db.execute(stmt)
    return list(result.scalars().all())
