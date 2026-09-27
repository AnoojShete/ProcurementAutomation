"""Account events in the shared audit_log table (entity_type "user").

Records who did what to which account — never passwords, hashes or
tokens. Written in the caller's transaction, so an event is recorded
exactly when the change it describes is committed."""
import json
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def record(db: AsyncSession, user_id: str, action: str, performed_by: Optional[str] = None,
                 **details) -> None:
    await db.execute(
        text("INSERT INTO audit_log (entity_id, entity_type, action, performed_by, payload) "
             "VALUES (:id, 'user', :action, :by, CAST(:payload AS jsonb))"),
        {"id": user_id, "action": action, "by": performed_by, "payload": json.dumps(details, default=str)},
    )
