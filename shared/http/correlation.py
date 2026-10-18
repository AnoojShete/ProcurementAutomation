"""Correlation id per HTTP request, and one JSON access line (FR-07).

nginx gives every API request an X-Correlation-ID ($request_id); a call
without one (a service calling another directly) gets a fresh id. The id
is set on CorrelationContext for the whole request, so the service's log
lines and the events it publishes carry it, and Kafka consumers carry it
on to the next service — one id follows an upload through every agent.
The id is echoed back in the response header.

Pure ASGI (not BaseHTTPMiddleware) so streaming responses are untouched.
"""
import logging
import re
import time
import uuid

from shared.logging.context import CorrelationContext

HEADER = b"x-correlation-id"
QUIET_PATHS = ("/health", "/metrics")  # polled constantly; not worth a line each
_VALID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")

logger = logging.getLogger("access")


def pick_correlation_id(headers: list[tuple[bytes, bytes]]) -> str:
    """The incoming id if it looks like one, otherwise a new UUID."""
    for name, value in headers:
        if name.lower() == HEADER:
            candidate = value.decode("latin-1").strip()
            if _VALID.match(candidate):
                return candidate
    return str(uuid.uuid4())


class CorrelationMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        correlation_id = pick_correlation_id(scope.get("headers") or [])
        token = CorrelationContext.set(correlation_id)
        started = time.perf_counter()
        status = {"code": 500}

        async def send_with_header(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + [(HEADER, correlation_id.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            path = scope.get("path", "")
            if not path.startswith(QUIET_PATHS):
                logger.info(
                    f"{scope.get('method')} {path} {status['code']} "
                    f"{(time.perf_counter() - started) * 1000:.0f}ms"
                )
            CorrelationContext.reset(token)
