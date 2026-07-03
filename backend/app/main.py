"""FastAPI application entry point."""
from __future__ import annotations

import time
from collections.abc import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import BaseHTTPMiddleware

from .database import Base, engine, test_connection
from .routers import vendor_router
from .utils.exceptions import DuplicateVendorError
from .utils.logger import configure_logging

logger = configure_logging()

app = FastAPI(
    title="Procurement Workflow Automation Platform",
    description="FastAPI backend for vendor management and procurement workflows.",
    version="1.0.0",
)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        start_time = time.perf_counter()
        logger.info("Incoming request %s %s", request.method, request.url.path)
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            "Response %s %s -> %s in %.2fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


app.add_middleware(RequestLoggingMiddleware)
app.include_router(vendor_router)


@app.exception_handler(DuplicateVendorError)
async def duplicate_vendor_exception_handler(request: Request, exc: DuplicateVendorError):
    return JSONResponse(
        status_code=409,
        content={
            "success": False,
            "error": {
                "code": 409,
                "message": str(exc),
            },
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": exc.status_code,
                "message": exc.detail,
            },
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": {
                "code": 422,
                "message": "Validation error",
                "details": exc.errors(),
            },
        },
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    logger.exception("Database error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {
                "code": 500,
                "message": "Database error",
            },
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {
                "code": 500,
                "message": "Internal server error",
            },
        },
    )


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Procurement API Running"}


@app.on_event("startup")
def startup_event() -> None:
    retries = 5
    for attempt in range(1, retries + 1):
        try:
            test_connection()
            Base.metadata.create_all(bind=engine)
            logger.info("Database connection verified and tables ready")
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("Database connection attempt %s/%s failed: %s", attempt, retries, exc)
            if attempt == retries:
                raise
            time.sleep(2)
