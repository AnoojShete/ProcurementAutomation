from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import settings
from shared.logging.configure import configure_logging
configure_logging(settings.service_name)
from app.database import init_db
from app.api import health, auth, business_rules
from app.kafka_producer import start_kafka_producer, stop_kafka_producer
from shared.http.error_handlers import register_error_handlers


from shared.infra.retry import with_retry

@asynccontextmanager
async def lifespan(app: FastAPI):
    await with_retry(init_db, name="Postgres init")
    await start_kafka_producer()
    try:
        yield
    finally:
        await stop_kafka_producer()


app = FastAPI(
    title="Auth Service",
    description="Login, refresh, token issuance and business rules parameter engine for the IT Procurement Intelligence Platform.",
    version="1.0.0",
    lifespan=lifespan,
)

register_error_handlers(app)

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

app.include_router(health.router)
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(business_rules.admin_router)
app.include_router(business_rules.internal_router)
