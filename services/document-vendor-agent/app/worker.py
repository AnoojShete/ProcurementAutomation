"""Background worker process: consumes document.ingested and runs the
extraction pipeline (OCR/classification/field extraction/vendor
matching/duplicate detection). Run as its own container
(`python -m app.worker`), separate from the API process, same pattern as
the other two services' app/worker.py.
"""
import asyncio
import logging

from prometheus_client import start_http_server

from app.config import settings
from app.database import init_db
from app.kafka.producer import KafkaEventProducer
from app.kafka.consumer import start_consumer
from app.services.storage import ensure_bucket


async def main():
    # This process (not the API container) is where app/services/pipeline.py
    # actually runs, so the custom metrics in app/metrics.py only ever get
    # updated here. There's no FastAPI/Instrumentator app in this process,
    # so start_http_server spins up a minimal metrics-only HTTP server
    # instead — infra/prometheus/prometheus.yml scrapes it as its own job
    # (document-vendor-agent-worker:9100), separate from the API's
    # document-vendor-agent:8001 job.
    start_http_server(9100)

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
