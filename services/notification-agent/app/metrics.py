"""Custom business metrics, registered to prometheus_client's default
registry alongside prometheus-fastapi-instrumentator's generic HTTP
metrics (see app/main.py). notification-agent has no separate worker
container (its Kafka consumer and digest-flush loop both run inside this
same API process's lifespan), so these show up on the existing /metrics
endpoint with no extra wiring.
"""
from prometheus_client import Counter

notification_sent_total = Counter(
    "notification_sent_total",
    "Notifications dispatched",
    ["channel", "status"],
)
