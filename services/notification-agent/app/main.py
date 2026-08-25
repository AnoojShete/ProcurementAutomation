import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import settings, digest_flush_interval_seconds
from app.database import init_db, async_session_factory
from app.kafka.consumer import start_consumer
from app.services.digest_service import flush_due_digests
from app.api import health, notifications
from shared.http.error_handlers import register_error_handlers

# Uvicorn only configures its own (uvicorn.*) loggers; the root logger has
# no handler by default, so plain `logging.getLogger(__name__).info(...)`
# calls elsewhere in this service (kafka/consumer.py, services/*) would be
# silently dropped without this — only WARNING+ would reach stderr via
# Python's logging "handler of last resort". Explicit config here makes the
# consumer/digest-loop lifecycle actually observable in `docker logs`.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def _digest_flush_loop():
    """Periodic background task (a plain asyncio loop, not APScheduler —
    kept deliberately minimal per the brief) that batches queued digest
    events into one email per recipient. Interval is config-driven
    (config.yaml: digest_flush_interval_seconds) — shortened for demo
    purposes from what would be a ~daily cadence in production."""
    interval = digest_flush_interval_seconds()
    while True:
        try:
            await asyncio.sleep(interval)
            async with async_session_factory() as db:
                sent = await flush_due_digests(db)
                if sent:
                    logger.info(f"Digest flush sent {sent} batched email(s)")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Digest flush loop error: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    consumer_task = asyncio.create_task(start_consumer(app))
    digest_task = asyncio.create_task(_digest_flush_loop())

    yield

    for task in (consumer_task, digest_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Notification Agent",
    description="Consumes platform events, renders Jinja2 email templates, and sends via SMTP (Mailpit in dev).",
    version="1.0.0",
    lifespan=lifespan,
)

register_error_handlers(app)

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

app.include_router(health.router)
app.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])
