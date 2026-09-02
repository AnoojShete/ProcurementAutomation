from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi import Depends, FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import select, func
import redis.asyncio as redis
import asyncio
import logging

from app.config import settings
from app.database import init_db, get_db, async_session_factory
from app.kafka.producer import KafkaEventProducer
from app.kafka.consumer import start_consumer
from app.api import health, requests, inventory, inbox
from app.schemas import ErrorResponse, ErrorDetail

# GAP-Auth1: import shared JWT auth dependency
from shared.auth.middleware import get_current_user, require_role

from app.models import AuditLog, PurchaseRequest
from app.metrics import approval_pending_total
from shared.http.error_handlers import register_error_handlers
from shared.auth import get_current_user
from shared.audit import build_audit_router

logger = logging.getLogger(__name__)


async def _refresh_approval_pending_gauge():
    """Recomputes approval_pending_total from the DB every 30s, rather
    than incrementing/decrementing it across code paths — request creation
    happens in this API process, but the terminal decision (approved/
    rejected) happens inside a Temporal activity in the separate
    approval-inventory-agent-worker container, so an incrementally
    maintained Gauge would be split across two processes' independent
    metric registries and never converge on the true count."""
    while True:
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    select(func.count()).select_from(PurchaseRequest).where(
                        PurchaseRequest.status == "pending_approval"
                    )
                )
                approval_pending_total.set(result.scalar_one())
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"approval_pending_total refresh failed: {e}", exc_info=True)
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()


    # Redis
    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)

    # Kafka Producer (shared across the app)

    # Kafka Producer
    app.state.kafka_producer = KafkaEventProducer(settings.kafka_bootstrap_servers)
    await app.state.kafka_producer.start()

    # Kafka Consumer — subscribes to document.classified and contract.signed.
    # NOTE: We do NOT consume license.usage.updated because we publish it.
    # The usage_scanner below is the correct input source (raw SSO log data).

    # Kafka Consumer (background task)
    consumer_task = asyncio.create_task(start_consumer(app))

    # Usage Scanner — reads raw SSO login data periodically, updates
    # the license_usage table, and publishes license.usage.updated events.
    # This is the correct data flow:
    #   SSO logs → [scanner] → license_usage table → license.usage.updated (Kafka)
    scanner_task = asyncio.create_task(
        run_usage_scanner(app.state.kafka_producer)
    )

    gauge_task = asyncio.create_task(_refresh_approval_pending_gauge())

    yield

    # Shutdown — cancel background tasks gracefully
    for task in (consumer_task, scanner_task):

    # Shutdown
    for task in (consumer_task, gauge_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


    await app.state.kafka_producer.stop()
    await app.state.redis.aclose()


app = FastAPI(
    title="Approval & Inventory Intelligence Agent",
    description="Handles purchase approvals, inventory management, and license utilisation tracking",
    version="1.0.0",
    lifespan=lifespan
)

register_error_handlers(app)

# ── Error handlers ────────────────────────────────────────────────────────────
# GAP-A9: Rewrite all HTTP exceptions to the shared error envelope format
# {"error": {"code": str, "message": str}} rather than FastAPI's {"detail": str}.

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    code_map = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 422: "VALIDATION_ERROR"}
    code = code_map.get(exc.status_code, "HTTP_ERROR")
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=ErrorDetail(code=code, message=str(exc.detail))
        ).model_dump()
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error=ErrorDetail(code="VALIDATION_ERROR", message=str(exc))
        ).model_dump()
    )


# Prometheus metrics — no auth required
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

# ── Routers ───────────────────────────────────────────────────────────────────
# GAP-Auth1: apply get_current_user to all business routers so every endpoint
# requires a valid JWT Bearer token.  /health and /metrics remain open.

# Include routers — /health and /metrics are the only unauthenticated
# routes; every other router requires a valid JWT. Role restrictions on
# individual write endpoints (approve/reject) are applied inline in
# app/api/requests.py.
app.include_router(health.router)

app.include_router(
    requests.router,
    prefix="/requests",
    tags=["Purchase Requests"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    inventory.router,
    prefix="/inventory",
    tags=["Inventory"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    inbox.router,
    prefix="/inbox",
    tags=["Approver Inbox"],
    dependencies=[Depends(get_current_user)],
)
# GET /requests/audit is registered BEFORE requests.router: it already has
# GET /requests/{request_id}, and Starlette matches routes in registration
# order — that catch-all would otherwise swallow "/requests/audit" as
# request_id="audit".
app.include_router(
    build_audit_router(AuditLog, get_db, entity_types=["purchase_request"], detail_field="details"),
    prefix="/requests", tags=["Audit"], dependencies=[Depends(get_current_user)],
)
app.include_router(
    requests.router, prefix="/requests", tags=["Purchase Requests"], dependencies=[Depends(get_current_user)]
)
app.include_router(
    inventory.router, prefix="/inventory", tags=["Inventory"], dependencies=[Depends(get_current_user)]
)
app.include_router(
    inbox.router, prefix="/inbox", tags=["Approver Inbox"], dependencies=[Depends(get_current_user)]
)
