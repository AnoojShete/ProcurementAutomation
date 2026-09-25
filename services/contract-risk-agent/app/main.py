import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
import redis.asyncio as redis
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import settings
from shared.logging.configure import configure_logging
configure_logging(settings.service_name)
from app.database import init_db, get_db
from app.kafka.producer import KafkaEventProducer
from app.kafka.consumer import start_consumer
from app.api import health, contracts, vendors, webhooks
from app.models import AuditLog
from shared.http.error_handlers import register_error_handlers
from shared.auth import get_current_user
from shared.audit import build_audit_router


from shared.infra.retry import with_retry

@asynccontextmanager
async def lifespan(app: FastAPI):
    await with_retry(init_db, name="Postgres init")

    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
    await with_retry(app.state.redis.ping, name="Redis ping")

    app.state.kafka_producer = KafkaEventProducer(settings.kafka_bootstrap_servers)
    await with_retry(app.state.kafka_producer.start, name="Kafka producer")

    consumer_task = asyncio.create_task(start_consumer(app))

    yield

    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

    await app.state.kafka_producer.stop()
    await app.state.redis.aclose()


app = FastAPI(
    title="Contract & Risk Analysis Agent",
    description="Contract generation, e-signature routing, clause extraction, and vendor risk scoring",
    version="1.0.0",
    lifespan=lifespan,
)

register_error_handlers(app)

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

# /health and /metrics are the only unauthenticated routes. Every other
# router requires a valid JWT (shared.auth.get_current_user); role
# restrictions on individual write endpoints are applied via
# `Depends(require_role(...))` inline in app/api/contracts.py and
# app/api/vendors.py where they create/mutate state.
app.include_router(health.router)
# GET /contracts/audit is registered BEFORE contracts.router: it already
# has GET /contracts/{contract_id}, and Starlette matches routes in
# registration order — that catch-all would otherwise swallow
# "/contracts/audit" as contract_id="audit".
app.include_router(
    build_audit_router(AuditLog, get_db, entity_types=["contract", "vendor"]),
    prefix="/contracts", tags=["Audit"], dependencies=[Depends(get_current_user)],
)
app.include_router(
    contracts.router, prefix="/contracts", tags=["Contracts"], dependencies=[Depends(get_current_user)]
)
app.include_router(
    vendors.router, prefix="/vendors", tags=["Vendor Risk"], dependencies=[Depends(get_current_user)]
)
# Not JWT-gated: the e-sign provider has no platform login. Trust comes
# from the HMAC signature verified inside the handler instead.
app.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])
