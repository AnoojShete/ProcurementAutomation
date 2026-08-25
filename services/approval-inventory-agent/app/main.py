from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
import redis.asyncio as redis
import asyncio

from app.config import settings
from app.database import init_db
from app.kafka.producer import KafkaEventProducer
from app.kafka.consumer import start_consumer
from app.api import health, requests, inventory, inbox
from shared.http.error_handlers import register_error_handlers
from shared.auth import get_current_user

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    
    # Redis
    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
    
    # Kafka Producer
    app.state.kafka_producer = KafkaEventProducer(settings.kafka_bootstrap_servers)
    await app.state.kafka_producer.start()
    
    # Kafka Consumer (background task)
    consumer_task = asyncio.create_task(start_consumer(app))
    
    yield
    
    # Shutdown
    consumer_task.cancel()
    try:
        await consumer_task
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

# Prometheus metrics
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

# Include routers — /health and /metrics are the only unauthenticated
# routes; every other router requires a valid JWT. Role restrictions on
# individual write endpoints (approve/reject) are applied inline in
# app/api/requests.py.
app.include_router(health.router)
app.include_router(
    requests.router, prefix="/requests", tags=["Purchase Requests"], dependencies=[Depends(get_current_user)]
)
app.include_router(
    inventory.router, prefix="/inventory", tags=["Inventory"], dependencies=[Depends(get_current_user)]
)
app.include_router(
    inbox.router, prefix="/inbox", tags=["Approver Inbox"], dependencies=[Depends(get_current_user)]
)
