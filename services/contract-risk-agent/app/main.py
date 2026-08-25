import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import settings
from app.database import init_db
from app.kafka.producer import KafkaEventProducer
from app.kafka.consumer import start_consumer
from app.api import health, contracts, vendors
from shared.http.error_handlers import register_error_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    app.state.kafka_producer = KafkaEventProducer(settings.kafka_bootstrap_servers)
    await app.state.kafka_producer.start()

    consumer_task = asyncio.create_task(start_consumer(app))

    yield

    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

    await app.state.kafka_producer.stop()


app = FastAPI(
    title="Contract & Risk Analysis Agent",
    description="Contract generation, e-signature routing, clause extraction, and vendor risk scoring",
    version="1.0.0",
    lifespan=lifespan,
)

register_error_handlers(app)

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

app.include_router(health.router)
app.include_router(contracts.router, prefix="/contracts", tags=["Contracts"])
app.include_router(vendors.router, prefix="/vendors", tags=["Vendor Risk"])
