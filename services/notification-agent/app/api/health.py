from fastapi import APIRouter
from sqlalchemy import text

from app.database import async_session_factory

router = APIRouter()


@router.get("/health")
async def health_check():
    """LIVE vs READY/DEGRADED: the process being up doesn't mean its
    dependencies are — a DB ping is the one dependency check every service
    can make cheaply and reliably."""
    dependencies = {}
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        dependencies["database"] = "up"
    except Exception:
        dependencies["database"] = "down"

    status = "ok" if all(v == "up" for v in dependencies.values()) else "degraded"
    return {"status": status, "service": "notification-agent", "dependencies": dependencies}
