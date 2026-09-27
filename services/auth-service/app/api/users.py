"""Admin user management: list accounts, change a role, disable/enable.

Sign-up always creates a "requester"; an admin promotes people from here.
Changing a role or disabling an account bumps token_version, so the
person's existing sessions stop refreshing and the change applies within
one access-token lifetime (JWT_EXPIRY_MINUTES).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.database import get_db
from app.models import User
from app.schemas import AdminUserResponse, DataResponse, UserUpdateRequest
from shared.auth.middleware import CurrentUser, require_role

router = APIRouter()


@router.get("", response_model=DataResponse)
async def list_users(q: Optional[str] = Query(None, max_length=255), limit: int = Query(200, ge=1, le=500),
                     _: CurrentUser = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    stmt = select(User).order_by(User.created_at.desc()).limit(limit)
    if q:
        stmt = stmt.where(func.lower(User.email).contains(q.strip().lower(), autoescape=True))
    users = (await db.execute(stmt)).scalars().all()
    return DataResponse(data=[AdminUserResponse.model_validate(u) for u in users])


@router.patch("/{user_id}", response_model=DataResponse)
async def update_user(user_id: str, data: UserUpdateRequest, admin: CurrentUser = Depends(require_role("admin")),
                      db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.id == user_id))).scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    if user.id == admin.id and (data.role not in (None, user.role) or data.is_active is False):
        # Stops the last admin from locking everyone out of administration.
        raise HTTPException(status_code=400, detail="You can't change your own role or disable your own account.")

    changes = {}
    if data.role is not None and data.role != user.role:
        changes["role"] = {"from": user.role, "to": data.role}
        user.role = data.role
    if data.is_active is not None and data.is_active != user.is_active:
        changes["is_active"] = {"from": user.is_active, "to": data.is_active}
        user.is_active = data.is_active
    if changes:
        user.token_version += 1
        await audit.record(db, user.id, "user.updated_by_admin", performed_by=admin.email, **changes)
        await db.commit()
    return DataResponse(data=AdminUserResponse.model_validate(user))
