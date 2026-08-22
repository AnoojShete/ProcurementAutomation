import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    """Dependency for providing a database session."""
    async with async_session_factory() as session:
        yield session

async def init_db():
    """Test the database connection."""
    try:
        async with engine.begin() as conn:
            # Just test the connection
            pass
        print("Database connection successful")
    except Exception as e:
        print(f"Database connection failed: {e}")
        raise
