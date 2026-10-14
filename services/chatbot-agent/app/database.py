import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

MIGRATIONS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations", "0001_chat_tables.sql")

async def get_db():
    async with async_session_factory() as session:
        yield session

async def init_db():
    if os.path.exists(MIGRATIONS_PATH):
        with open(MIGRATIONS_PATH) as f:
            sql = "\n".join(line for line in f.read().splitlines() if not line.strip().startswith("--"))
        async with engine.begin() as conn:
            for stmt in sql.split(";"):
                if stmt.strip():
                    await conn.execute(text(stmt.strip()))