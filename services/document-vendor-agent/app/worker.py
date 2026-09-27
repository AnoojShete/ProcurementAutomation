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
from app.database import async_session_factory, init_db
from app.kafka.producer import KafkaEventProducer
from app.kafka.consumer import start_consumer
from app.services.storage import ensure_bucket


from shared.eventing import kafka_sender, run_relay
from shared.infra.retry import with_retry

async def main():
    # This process (not the API container) is where app/services/pipeline.py
    # actually runs, so the custom metrics in app/metrics.py only ever get
    # updated here. There's no FastAPI/Instrumentator app in this process,
    # so start_http_server spins up a minimal metrics-only HTTP server
    # instead — infra/prometheus/prometheus.yml scrapes it as its own job
    # (document-vendor-agent-worker:9100), separate from the API's
    # document-vendor-agent:8001 job.
    try:
        start_http_server(9100)
    except Exception as e:
        logging.warning(f"Metrics server on port 9100 already running or failed: {e}")

    await with_retry(init_db, name="Postgres init")
    await with_retry(ensure_bucket, name="MinIO bucket init")

    producer = KafkaEventProducer(settings.kafka_bootstrap_servers)
    await with_retry(producer.start, name="Kafka producer")
    # The pipeline commits its events to the outbox; this relay sends them.
    relay_task = asyncio.create_task(run_relay(
        async_session_factory, producer.service_name, kafka_sender(producer.producer),
    ))
    try:
        await start_consumer(producer)
    finally:
        relay_task.cancel()
        await producer.stop()


def _run_with_graceful_shutdown() -> None:
    """On SIGTERM (docker stop / redeploy) cancel the main task so the
    consumer finishes in-flight documents and leaves its Kafka group.
    Without this Python exits immediately, and the broker waits the full
    session timeout (60 s) before giving the partitions to a new worker."""
    import signal

    async def runner():
        task = asyncio.current_task()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, task.cancel)
        try:
            await main()
        except asyncio.CancelledError:
            logging.getLogger(__name__).info("Worker stopped")

    asyncio.run(runner())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _run_with_graceful_shutdown()
