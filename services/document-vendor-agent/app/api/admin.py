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

@router.get("/model-routing-log")
async def get_model_routing_log(limit: int = 30, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(text(
        # NUMERIC columns would serialize as strings ("1.000"); cast so clients get numbers.
        "SELECT id, document_id, route_name, model_used, fallback_triggered, fallback_reason, "
        "confidence::float AS confidence, duration_ms::float AS duration_ms, created_at "
        "FROM model_routing_log ORDER BY created_at DESC LIMIT :limit"
    ), {"limit": limit})).mappings().all()
    return DataResponse(data=[dict(r) for r in rows])

KNOWN_CONSUMER_GROUPS = [
    "approval-inventory-agent",
    "contract-risk-agent",
    "document-vendor-agent",
    "notification-agent",
]

@router.get("/kafka-lag")
async def get_kafka_lag():
    import httpx
    group_lags = {g: 0 for g in KNOWN_CONSUMER_GROUPS}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                "http://prometheus:9090/api/v1/query",
                params={"query": "sum by (consumergroup, group) (kafka_consumergroup_lag)"},
            )
            if resp.status_code == 200:
                data = resp.json()
                for result in data.get("data", {}).get("result", []):
                    metric = result.get("metric", {})
                    group = metric.get("consumergroup") or metric.get("group")
                    if group:
                        try:
                            val = int(float(result.get("value", [0, "0"])[1]))
                            group_lags[group] = max(val, 0)
                        except (ValueError, TypeError, IndexError):
                            pass
    except Exception:
        pass
    results = [{"group": g, "lag": lag} for g, lag in sorted(group_lags.items())]
    return DataResponse(data=results)