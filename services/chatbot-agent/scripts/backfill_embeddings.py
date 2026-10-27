"""Builds (or brings up to date) the assistant's retrieval index now,
instead of waiting for the chatbot's background sweep:

    docker compose exec chatbot-agent python scripts/backfill_embeddings.py
"""
import asyncio

from app.database import async_session_factory, init_db
from app.services.indexer import sync


async def main():
    await init_db()
    result = await sync(async_session_factory)
    print(f"RAG sync complete: {result}")


if __name__ == "__main__":
    asyncio.run(main())
