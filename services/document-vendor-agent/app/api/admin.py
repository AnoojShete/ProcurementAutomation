from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.database import get_db
from app.schemas import DataResponse
from shared.auth import require_role

router = APIRouter(dependencies=[Depends(require_role("admin"))])

class LiveModeUpdate(BaseModel):
    enabled: bool

async def _quota_status(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(text(
        "SELECT api_name, calls_used, calls_limit FROM api_quota_usage ORDER BY api_name"
    ))).mappings().all()
    return [
        {"api_name": row["api_name"], "calls_used": row["calls_used"],
         "calls_limit": row["calls_limit"], "remaining": max(row["calls_limit"] - row["calls_used"], 0)}
        for row in rows
    ]


async def _apply_safety_cutoff(db: AsyncSession) -> bool:
    rows = (await db.execute(text(
        "SELECT api_name, calls_used, calls_limit FROM api_quota_usage"
    ))).mappings().all()
    crossed = any(
        row["calls_used"] >= (15 if row["api_name"] == "gstin_live" else row["calls_limit"] * 0.8)
        for row in rows
    )
    if crossed:
        await db.execute(text("UPDATE system_settings SET live_verification_enabled = false WHERE id = 1"))
    return crossed


async def _status(db: AsyncSession) -> dict:
    cutoff = await _apply_safety_cutoff(db)
    enabled = (await db.execute(text(
        "SELECT live_verification_enabled FROM system_settings WHERE id = 1"
    ))).scalar_one_or_none() or False
    await db.commit()
    result = {"enabled": bool(enabled), "quotas": await _quota_status(db)}
    if cutoff:
        result["message"] = "Auto-safety cutoff triggered. Live mode disabled."
    return result

@router.get("/live-mode")
async def get_live_mode(db: AsyncSession = Depends(get_db)):
    return DataResponse(data=await _status(db))

@router.patch("/live-mode")
async def update_live_mode(req: LiveModeUpdate, db: AsyncSession = Depends(get_db)):
    if req.enabled and await _apply_safety_cutoff(db):
        return DataResponse(data=await _status(db))
    await db.execute(text(
        "UPDATE system_settings SET live_verification_enabled = :enabled, enabled_at = now() WHERE id = 1"
    ), {"enabled": req.enabled})
    return DataResponse(data=await _status(db))