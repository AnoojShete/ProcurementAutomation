from contextlib import asynccontextmanager
from fastapi import FastAPI
import asyncio
from app.database import init_db, async_session_factory
from app.api import health, chat
from app.services.indexer import run_sweeps

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # RAG index: built on start-up, then kept current every minute.
    index_task = asyncio.create_task(run_sweeps(async_session_factory))
    yield
    index_task.cancel()

app = FastAPI(title="Chatbot Agent", lifespan=lifespan)
app.include_router(health.router)
app.include_router(chat.router, prefix="/chat", tags=["Chat"])