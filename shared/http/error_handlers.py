"""Shared FastAPI exception handlers enforcing the platform's standard
error envelope: {"error": {"code": str, "message": str}}.

Import and register in each service's main.py:

    from shared.http.error_handlers import register_error_handlers
    register_error_handlers(app)

Every service should use this instead of ad-hoc HTTPException(detail=...)
handling, since FastAPI's default renders {"detail": ...} which doesn't
match the contract in shared/schemas/events.md.
"""
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

try:
    from sqlalchemy.exc import DBAPIError
except ImportError:  # a service without SQLAlchemy installed just won't hit this branch
    DBAPIError = None

_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_file_type",
    422: "validation_error",
    429: "rate_limited",
    503: "unavailable",
}


def _error_body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


logger = logging.getLogger(__name__)


def _log_unhandled(request: Request, exc: Exception) -> None:
    # The client only sees a generic 500; the traceback goes to the service
    # log so the failure can actually be diagnosed.
    logger.error(f"unhandled error on {request.method} {request.url.path}: {type(exc).__name__}: {exc}",
                 exc_info=exc)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        code = _STATUS_CODES.get(exc.status_code, "error")
        # detail={"code": ..., "message": ...} lets an endpoint give the
        # client a more specific code (e.g. "email_not_verified").
        if isinstance(exc.detail, dict) and "code" in exc.detail and "message" in exc.detail:
            code, message = str(exc.detail["code"]), str(exc.detail["message"])
        else:
            message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(status_code=exc.status_code, content=_error_body(code, message))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        # Only where and why — never the submitted value: pydantic's "input"
        # can be the whole request body, password included.
        errors = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(status_code=422, content=_error_body("validation_error", str(errors)))

    if DBAPIError is not None:
        @app.exception_handler(DBAPIError)
        async def dbapi_error_handler(request: Request, exc: DBAPIError):
            # A malformed path/query value (e.g. "2.1" where a UUID is
            # expected) reaches the database driver as a bad bind
            # parameter, not as a FastAPI/Pydantic validation error — left
            # unhandled this surfaces as a raw 500. Any error the driver
            # itself flags as bad *input* (vs. e.g. a connection failure)
            # is a client mistake, so it's a 400, not a 500.
            cause = str(getattr(exc, "orig", exc)).lower()
            if any(s in cause for s in ("invalid uuid", "invalid input syntax", "data error", "datatype mismatch")):
                return JSONResponse(status_code=400, content=_error_body("bad_request", "malformed identifier or field value"))
            _log_unhandled(request, exc)
            return JSONResponse(status_code=500, content=_error_body("internal_error", "an unexpected error occurred"))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        _log_unhandled(request, exc)
        return JSONResponse(status_code=500, content=_error_body("internal_error", "an unexpected error occurred"))
