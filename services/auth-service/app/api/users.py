"""Admin user management: list accounts, change a role, disable/enable, change email.

Sign-up always creates a "requester"; an admin promotes people from here.
Changing a role, disabling an account, or changing an email bumps token_version,
so the person's existing sessions stop refreshing and the change applies within
one access-token lifetime (JWT_EXPIRY_MINUTES).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import account_tokens, audit, lockout
from app.database import get_db
from app.models import User
from app.schemas import AdminUserResponse, DataResponse, PersonResponse, UserUpdateRequest
from app.security import normalize_email
from shared.auth.middleware import CurrentUser, get_current_user, require_role

router = APIRouter()
# Mounted at /auth/people: any signed-in user, so pages can show a name
# where the data holds an email (requested_by, decided_by, ...).
people_router = APIRouter()


@people_router.get("", response_model=DataResponse)
async def list_people(_: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    users = (await db.execute(select(User).order_by(User.email))).scalars().all()
    return DataResponse(data=[PersonResponse.model_validate(u) for u in users])


@router.get("", response_model=DataResponse)
async def list_users(q: Optional[str] = Query(None, max_length=255), limit: int = Query(200, ge=1, le=500),
                     _: CurrentUser = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    stmt = select(User).order_by(User.created_at.desc()).limit(limit)
    if q:
        term = q.strip().lower()
        stmt = stmt.where(func.lower(User.email).contains(term, autoescape=True)
                          | func.lower(func.coalesce(User.display_name, "")).contains(term, autoescape=True))
    users = (await db.execute(stmt)).scalars().all()
    return DataResponse(data=[AdminUserResponse.model_validate(u) for u in users])


@router.get("/{user_id}", response_model=DataResponse)
async def get_user(user_id: str, _: CurrentUser = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.id == user_id))).scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return DataResponse(data=AdminUserResponse.model_validate(user))


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
    if data.email is not None:
        new_email = normalize_email(str(data.email))
        if new_email != user.email:
            existing = (await db.execute(select(User).where(func.lower(User.email) == new_email))).scalars().first()
            if existing and existing.id != user.id:
                raise HTTPException(status_code=400, detail="A user with that email already exists.")
            old_email = user.email
            changes["email"] = {"from": old_email, "to": new_email}
            user.email = new_email
            await account_tokens.revoke_all(db, user.id, account_tokens.VERIFY_EMAIL)
            await account_tokens.revoke_all(db, user.id, account_tokens.RESET_PASSWORD)
            await lockout.clear(db, old_email)
            await lockout.clear(db, new_email)

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
