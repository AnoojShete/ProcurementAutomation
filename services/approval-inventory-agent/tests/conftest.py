import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import redis.asyncio as aioredis

@pytest.fixture(scope='session')
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def mock_db_session():
    """Mock async database session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session

@pytest.fixture
def mock_kafka_producer():
    """Mock Kafka producer."""
    producer = AsyncMock()
    producer.publish = AsyncMock()
    producer.publish_approval_requested = AsyncMock()
    producer.publish_approval_decided = AsyncMock()
    # publish_license_usage_updated now accepts anomaly_score, top_factors,
    # model_version in the license_data dict (all optional, default-safe).
    producer.publish_license_usage_updated = AsyncMock()
    return producer

@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    client = AsyncMock(spec=aioredis.Redis)
    client.set = AsyncMock(return_value=True)
    client.get = AsyncMock(return_value=None)
    client.delete = AsyncMock(return_value=1)
    client.eval = AsyncMock(return_value=1)
    client.exists = AsyncMock(return_value=0)
    return client

@pytest.fixture
def sample_purchase_request():
    """Sample purchase request data."""
    return {
        "request_type": "hardware",
        "requested_by": "john.doe@company.com",
        "department": "Engineering",
        "vendor_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
        "amount": 250000.00,
        "currency": "INR",
        "items": [
            {"sku": "LAPTOP-DELL-5540", "name": "Dell Latitude 5540", "quantity": 3, "unit_price": 85000.00}
        ]
    }

@pytest.fixture
def sample_license_usage_data():
    """Sample license usage data for testing."""
    return {
        "license_id": "11111111-1111-1111-1111-111111111111",
        "vendor_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "app_name": "Microsoft 365 E3",
        "total_seats": 500,
        "active_users": [
            {"email": f"user{i}@company.com", "last_login_days_ago": i * 3}
            for i in range(1, 51)  # 50 users with varying login recency
        ]
    }
