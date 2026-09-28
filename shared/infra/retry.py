import asyncio
import logging
from typing import TypeVar, Callable, Awaitable, Any

logger = logging.getLogger(__name__)

T = TypeVar('T')

async def with_retry(
    func: Callable[[], Awaitable[T]],
    max_attempts: int = 30,
    delay_seconds: float = 2.0,
    name: str = "operation"
) -> T:
    """
    Retries an async operation with a fixed delay.
    """
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await func()
        except Exception as e:
            last_error = e
            logger.info(f"{name} failed (attempt {attempt}/{max_attempts}): {e}")
            if attempt < max_attempts:
                await asyncio.sleep(delay_seconds)
    
    logger.error(f"{name} failed after {max_attempts} attempts. Last error: {last_error}")
    raise last_error
