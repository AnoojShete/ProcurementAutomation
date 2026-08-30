"""Custom business metrics, registered to prometheus_client's default
registry alongside prometheus-fastapi-instrumentator's generic HTTP
metrics — but the extraction pipeline that updates these only ever runs in
app/worker.py (a separate container from the API process, see
app/main.py's lifespan comment), which has no FastAPI/Instrumentator
/metrics endpoint of its own. app/worker.py's main() calls
prometheus_client.start_http_server(9100) so these are still scrapeable
(infra/prometheus/prometheus.yml scrapes document-vendor-agent-worker:9100
as its own job, separate from the API's document-vendor-agent:8001 job).
"""
from prometheus_client import Counter, Histogram

document_processing_total = Counter(
    "document_processing_total",
    "Documents that finished the extraction pipeline",
    ["status"],
)

document_pipeline_stage_duration_seconds = Histogram(
    "document_pipeline_stage_duration_seconds",
    "Duration of each document-pipeline stage",
    ["stage"],
)

extraction_confidence = Histogram(
    "extraction_confidence",
    "Overall confidence score of a processed document",
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

vendor_matching_total = Counter(
    "vendor_matching_total",
    "Vendor-matching outcomes",
    ["match_type"],
)
