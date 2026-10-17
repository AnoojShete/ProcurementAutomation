from fastapi import APIRouter
from fastapi.responses import JSONResponse
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

    from app.kafka.consumer import CONSUMER_STATE
    dependencies["kafka_consumer"] = CONSUMER_STATE["status"]

    body = {"status": "ok", "service": "notification-agent", "dependencies": dependencies,
            "consumer": dict(CONSUMER_STATE)}
    if CONSUMER_STATE["status"] == "stopped":
        # Unhealthy: Docker's healthcheck (curl -f) and System Health see it.
        body["status"] = "unhealthy"
        return JSONResponse(status_code=503, content=body)
    if dependencies["database"] != "up":
        body["status"] = "degraded"
    return body
