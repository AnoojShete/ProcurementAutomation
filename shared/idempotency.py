"""Idempotency-Key support, backed by Redis, for POST endpoints that
create a resource. Usage in an endpoint:

    from fastapi import Header
    from shared.idempotency import get_cached_response, store_response

    @router.post("/generate")
    async def generate_contract(
        data: GenerateContractRequest, request: Request,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
        db: AsyncSession = Depends(get_db),
    ):
        if idempotency_key:
            cached = await get_cached_response(request.app.state.redis, "contract-risk-agent", idempotency_key)
            if cached is not None:
                return cached
        ...
        result = DataResponse(data=...)
        if idempotency_key:
            await store_response(request.app.state.redis, "contract-risk-agent", idempotency_key, result.model_dump(mode="json"))
        return result

If the same key arrives twice, the second call returns the first call's
response instead of creating a duplicate resource.
"""
import json
from typing import Any, Optional

IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60  # 24h — long enough to cover client retries, short enough not to leak forever


def _redis_key(service_name: str, idempotency_key: str) -> str:
    return f"idempotency:{service_name}:{idempotency_key}"


async def get_cached_response(redis_client, service_name: str, idempotency_key: str) -> Optional[Any]:
    if redis_client is None:
        return None
    raw = await redis_client.get(_redis_key(service_name, idempotency_key))
    if raw is None:
        return None
    return json.loads(raw)


async def store_response(redis_client, service_name: str, idempotency_key: str, response: Any) -> None:
    if redis_client is None:
        return
    await redis_client.set(
        _redis_key(service_name, idempotency_key),
        json.dumps(response),
        ex=IDEMPOTENCY_TTL_SECONDS,
    )
