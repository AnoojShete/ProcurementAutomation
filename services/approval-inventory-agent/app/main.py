from contextlib import asynccontextmanager
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
import redis.asyncio as redis
import asyncio

from app.config import settings
from app.database import init_db
from app.kafka.producer import KafkaEventProducer
from app.kafka.consumer import start_consumer
from app.usage_scanner import run_usage_scanner
from app.api import health, requests, inventory, inbox

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    
    # Redis
    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
    
    # Kafka Producer (shared across the app)
    app.state.kafka_producer = KafkaEventProducer(settings.kafka_bootstrap_servers)
    await app.state.kafka_producer.start()
    
    # Kafka Consumer — subscribes to document.classified and contract.signed.
    # NOTE: We do NOT consume license.usage.updated because we publish it.
    # The usage_scanner below is the correct input source (raw SSO log data).
    consumer_task = asyncio.create_task(start_consumer(app))
    
    # Usage Scanner — reads raw SSO login data periodically, updates
    # the license_usage table, and publishes license.usage.updated events.
    # This is the correct data flow:
    #   SSO logs → [scanner] → license_usage table → license.usage.updated (Kafka)
    scanner_task = asyncio.create_task(
        run_usage_scanner(app.state.kafka_producer)
    )
    
    yield
    
    # Shutdown — cancel background tasks gracefully
    for task in (consumer_task, scanner_task):
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

# Prometheus metrics
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

# Include routers
app.include_router(health.router)
app.include_router(requests.router, prefix="/requests", tags=["Purchase Requests"])
app.include_router(inventory.router, prefix="/inventory", tags=["Inventory"])
app.include_router(inbox.router, prefix="/inbox", tags=["Approver Inbox"])
