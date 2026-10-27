import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
import redis.asyncio as redis
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import settings
from shared.logging.configure import configure_logging
from shared.http.correlation import CorrelationMiddleware
configure_logging(settings.service_name)
from app.database import async_session_factory, init_db, get_db
from shared.eventing import kafka_sender, run_relay
from app.kafka.producer import KafkaEventProducer
from app.kafka.consumer import start_consumer
from app.api import health, contracts, vendors, webhooks, ops, obligations, rulesets, mandates, internal, admin
from app.services.docusign_client import run_status_poller
from app.services.reminder_sweep import run_reminder_sweeps
from app.models import AuditLog
from shared.http.error_handlers import register_error_handlers
from shared.auth import get_current_user, require_role
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
    # Publishes events committed to the outbox (shared/eventing/outbox.py).
    relay_task = asyncio.create_task(run_relay(
        async_session_factory, app.state.kafka_producer.service_name,
        kafka_sender(app.state.kafka_producer.producer),
    ))

    # Marks contracts signed when their DocuSign envelope completes (no-op
    # unless DocuSign is configured).
    docusign_task = asyncio.create_task(run_status_poller(async_session_factory, app.state.kafka_producer))
    # FR-03: reminder.due for contracts waiting too long for signature.
    reminder_task = asyncio.create_task(run_reminder_sweeps(async_session_factory, app.state.kafka_producer))
    # BR-7: re-score vendors after a delivery so on-time rate stays current.
    from app.services.risk_service import run_delivery_rescore
    rescore_task = asyncio.create_task(run_delivery_rescore(async_session_factory, app.state.kafka_producer))
    # FR-14: refresh a downloaded sanctions list daily (never downloads first).
    from app.services.sanctions import run_daily_refresh
    sanctions_task = asyncio.create_task(run_daily_refresh())
    from app.services.breach_catalogue import run_daily_breach_refresh
    breach_task = asyncio.create_task(run_daily_breach_refresh(async_session_factory))
    # Phase 2: read signed contracts' obligations; reminders and licence limits.
    from app.services.obligation_service import run_obligation_sweeps
    obligation_task = asyncio.create_task(run_obligation_sweeps(async_session_factory, app.state.kafka_producer))
    # Phase 3c: vendor scorecards, refreshed nightly (and on each vendor page view).
    from app.services.performance_scorecard import run_nightly
    scorecard_task = asyncio.create_task(run_nightly(async_session_factory))
    # FR-13: load the Legal-BERT clause model now (~6 s) rather than on the
    # first contract; without a downloaded model this just logs a warning.
    from app.services import clause_model
    app.state.clause_model_warmup = asyncio.create_task(asyncio.to_thread(clause_model.available))

    yield

    for task in (consumer_task, relay_task, docusign_task, reminder_task, rescore_task, sanctions_task, breach_task, obligation_task, scorecard_task):
        task.cancel()
        try:
            await task
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
# One correlation id per request (from nginx's X-Correlation-ID) + a JSON access line.
app.add_middleware(CorrelationMiddleware)

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
app.include_router(ops.router, prefix="/contracts/ops", tags=["Operations"])
# Phase 2 obligations, also before contracts.router (same reason as above).
app.include_router(
    obligations.router, prefix="/contracts", tags=["Contract Obligations"], dependencies=[Depends(get_current_user)]
)
app.include_router(
    mandates.router, prefix="", dependencies=[Depends(get_current_user)]
)
app.include_router(
    contracts.router, prefix="/contracts", tags=["Contracts"], dependencies=[Depends(get_current_user)]
)
app.include_router(
    vendors.router, prefix="/vendors", tags=["Vendor Risk"], dependencies=[Depends(get_current_user)]
)
app.include_router(
    rulesets.router, prefix="/admin/risk-rulesets", tags=["Ruleset Governance"],
    # Staff only (merge review G5); writes are admin-only on each route.
    dependencies=[Depends(require_role("approver", "finance", "admin"))]
)
# Not JWT-gated: the e-sign provider has no platform login. Trust comes
# from the HMAC signature verified inside the handler instead.
app.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])
# Not JWT-gated either: called by other services (no user), authenticated by
# the X-Internal-Service-Token header. The gateway has no route to /internal/.
app.include_router(internal.router, prefix="/internal", tags=["Internal"])
