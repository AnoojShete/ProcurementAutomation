"""QA audit (Oct 17): list endpoints passed `limit` straight to SQL, so
?limit=-1 was a 500 ("LIMIT must not be negative") and a huge value read
the whole table. Now 1..1000, else 422. (docs/quality-audit-report.md QA-05)"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import admin, documents, vendors
from app.database import get_db
from app.services import document_service
from shared.auth import get_current_user
from shared.auth.middleware import CurrentUser


def _client():
    app = FastAPI()
    app.include_router(documents.router, prefix="/documents")
    app.include_router(vendors.router, prefix="/vendors")
    app.include_router(admin.router, prefix="/admin")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u1", email="a@acme.test", role="admin")
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    return TestClient(app)


@pytest.mark.parametrize("path", ["/documents/", "/documents/review-queue", "/vendors/", "/admin/model-routing-log"])
@pytest.mark.parametrize("limit", [-1, 0, 1001])
def test_out_of_range_limit_is_a_422(path, limit):
    assert _client().get(f"{path}?limit={limit}").status_code == 422


def test_in_range_limit_reaches_the_query():
    with patch.object(document_service, "list_all_documents", AsyncMock(return_value=[])) as list_docs:
        assert _client().get("/documents/?limit=1000").status_code == 200
    assert list_docs.await_args.kwargs["limit"] == 1000
