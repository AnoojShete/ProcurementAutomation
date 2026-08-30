"""Custom business metrics, registered to prometheus_client's default
registry alongside prometheus-fastapi-instrumentator's generic HTTP
metrics (see app/main.py). Unlike document-vendor-agent and
approval-inventory-agent, both contract_service.py and risk_service.py run
entirely inside this API process (contract generation and risk scoring are
triggered by direct API calls or by the Kafka consumer started in this
same process's lifespan — see app/main.py — not by the separate Temporal
worker container, which only handles renewal/drift workflows), so these
show up on the existing /metrics endpoint with no extra wiring.
"""
from prometheus_client import Counter

contract_generation_total = Counter(
    "contract_generation_total",
    "Contracts generated",
    ["status"],
)

risk_assessment_total = Counter(
    "risk_assessment_total",
    "Vendor risk assessments completed",
    ["risk_band"],
)
