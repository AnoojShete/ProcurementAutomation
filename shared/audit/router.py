"""Reusable read-only `GET /audit` endpoint factory, mounted by any service
that writes into the shared `audit_log` table (see shared/db/init.sql and
shared/audit/queries.py). Admin-only.

Usage in a service's main.py — mounts as GET /documents/audit alongside
the existing GET /documents/... routes, no nginx changes needed since it
falls under the gateway's existing /api/documents/ prefix location:

    from shared.audit import build_audit_router
    from app.database import get_db
    from app.models import AuditLog

    app.include_router(
        build_audit_router(AuditLog, get_db, entity_types=["document", "vendor"]),
        prefix="/documents", tags=["Audit"], dependencies=[Depends(get_current_user)],
    )
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.audit.queries import list_audit_log
from shared.auth import require_role


def build_audit_router(
    model,
    get_db,
    entity_types: Optional[List[str]] = None,
    detail_field: str = "payload",
) -> APIRouter:
    router = APIRouter()

    @router.get("/audit", dependencies=[Depends(require_role("admin"))])
    async def get_audit_log(
        entity_id: Optional[str] = None,
        action: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = Query(100, le=500),
        db: AsyncSession = Depends(get_db),
    ):
        rows = await list_audit_log(
            db, model, entity_types=entity_types, entity_id=entity_id,
            action=action, since=since, until=until, limit=limit,
        )
        data = [
            {
                "id": r.id,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "action": r.action,
                "detail": getattr(r, detail_field, None),
                "created_at": r.created_at,
            }
            for r in rows
        ]
        return {"data": data, "meta": {"count": len(data)}}

    return router
