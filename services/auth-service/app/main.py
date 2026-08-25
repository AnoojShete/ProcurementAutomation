from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.database import init_db
from app.api import health, auth
from shared.http.error_handlers import register_error_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Auth Service",
    description="Login, refresh, and token issuance for the IT Procurement Intelligence Platform. DEMO ONLY.",
    version="1.0.0",
    lifespan=lifespan,
)

register_error_handlers(app)

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

app.include_router(health.router)
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
