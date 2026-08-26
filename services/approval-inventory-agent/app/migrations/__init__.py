"""Migration runner — executes all migration scripts in order."""
import asyncio
import logging
from app.migrations.migration_001_extend_schema import run_migration

async def run_all():
    await run_migration()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_all())
