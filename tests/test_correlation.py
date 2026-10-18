"""shared/http/correlation.py (FR-07): one correlation id per request,
visible to the service's logs/events, echoed back, one access line."""
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.http.correlation import CorrelationMiddleware, pick_correlation_id
from shared.logging.context import CorrelationContext


def _app():
    app = FastAPI()
    app.add_middleware(CorrelationMiddleware)

    @app.get("/thing")
    def thing():
        return {"seen": CorrelationContext.get()}

    @app.get("/health")
    def health():
        return {"ok": True}
    return app


def test_incoming_id_is_used_everywhere_and_echoed():
    r = TestClient(_app()).get("/thing", headers={"X-Correlation-ID": "abc12345-req"})
    assert r.json()["seen"] == "abc12345-req"
    assert r.headers["x-correlation-id"] == "abc12345-req"


def test_missing_or_bad_id_gets_a_fresh_one():
    client = TestClient(_app())
    r = client.get("/thing")
    assert len(r.headers["x-correlation-id"]) == 36 and r.json()["seen"] == r.headers["x-correlation-id"]
    bad = client.get("/thing", headers={"X-Correlation-ID": "x\"; drop"})
    assert bad.headers["x-correlation-id"] != "x\"; drop"


def test_context_is_cleared_after_the_request():
    TestClient(_app()).get("/thing", headers={"X-Correlation-ID": "abc12345-req"})
    assert CorrelationContext.get() in (None, "")


def test_one_access_line_per_request_but_not_for_health(caplog):
    client = TestClient(_app())
    with caplog.at_level(logging.INFO, logger="access"):
        client.get("/thing")
        client.get("/health")
    lines = [r.getMessage() for r in caplog.records if r.name == "access"]
    assert len(lines) == 1 and lines[0].startswith("GET /thing 200")


def test_pick_correlation_id():
    assert pick_correlation_id([(b"x-correlation-id", b"0123456789abcdef")]) == "0123456789abcdef"
    assert pick_correlation_id([]) != pick_correlation_id([])
