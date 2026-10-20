from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.database import init_db
from app.api import health, chat
import asyncio
from app.auto_embed import auto_embed_loop

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="Chatbot Agent", lifespan=lifespan)
@app.on_event("startup")
async def startup_event():
    # Fire and forget the background watcher
    asyncio.create_task(auto_embed_loop())
app.include_router(health.router)
app.include_router(chat.router, prefix="/chat", tags=["Chat"])
