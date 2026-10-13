from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.database import init_db
from app.api import health, chat

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="Chatbot Agent", lifespan=lifespan)
app.include_router(health.router)
app.include_router(chat.router, prefix="/chat", tags=["Chat"])