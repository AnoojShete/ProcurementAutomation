"""Background worker process: consumes document.ingested and runs the
extraction pipeline (OCR/classification/field extraction/vendor
matching/duplicate detection). Run as its own container
(`python -m app.worker`), separate from the API process, same pattern as
the other two services' app/worker.py.
"""
import asyncio
import logging

from app.config import settings
from app.database import init_db
from app.kafka.producer import KafkaEventProducer
from app.kafka.consumer import start_consumer
from app.services.storage import ensure_bucket


async def main():
    await init_db()
    await ensure_bucket()

    producer = KafkaEventProducer(settings.kafka_bootstrap_servers)
    await producer.start()
    try:
        await start_consumer(producer)
    finally:
        await producer.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
