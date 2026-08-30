from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import settings
from app.database import init_db, get_db
from app.kafka.producer import KafkaEventProducer
from app.api import health, documents, vendors
from app.models import AuditLog
from app.services.storage import ensure_bucket
from shared.http.error_handlers import register_error_handlers
from shared.auth import get_current_user
from shared.audit import build_audit_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await ensure_bucket()

    app.state.kafka_producer = KafkaEventProducer(settings.kafka_bootstrap_servers)
    await app.state.kafka_producer.start()

    # Note: the extraction pipeline itself runs in a SEPARATE worker
    # process (app/worker.py, its own container) that consumes
    # document.ingested — this API process only publishes it. Keeps the
    # request path (scan/store/publish) fast and independently scalable
    # from OCR/extraction work.

    yield

    await app.state.kafka_producer.stop()


app = FastAPI(
    title="Document & Vendor Intelligence Agent",
    description="Document intake/OCR/classification, vendor matching & dedup, and payment-detail governance",
    version="1.0.0",
    lifespan=lifespan,
)

register_error_handlers(app)

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

app.include_router(health.router)
# GET /documents/audit is registered BEFORE documents.router: Starlette
# matches routes in registration order, and documents.router already has
# GET /documents/{document_id} — registered first, that catch-all would
# swallow "/documents/audit" as document_id="audit" and this route would
# never be reached.
app.include_router(
    build_audit_router(AuditLog, get_db, entity_types=["document", "vendor"]),
    prefix="/documents", tags=["Audit"], dependencies=[Depends(get_current_user)],
)
app.include_router(
    documents.router, prefix="/documents", tags=["Documents"], dependencies=[Depends(get_current_user)]
)
app.include_router(
    vendors.router, prefix="/vendors", tags=["Vendors"], dependencies=[Depends(get_current_user)]
)
