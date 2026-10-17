"""Tests for Contract Signing Controls (Prompt 8 Part C).

Tests:
1. Signer identity: rejects free-text signer email not present in authorized signatories.
2. Simulated signing gating: POST /contracts/{id}/sign-simulated returns 403 unless ENABLE_SIGN_SIMULATED=true.
"""
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app as cra_app
from app.models import Contract
from app.services.contract_service import (
    ContractGenerationError,
    get_authorized_signatories,
    send_for_signature,
)


@pytest.mark.asyncio
async def test_authorized_signatories_lookup():
    db_mock = AsyncMock()
    exec_res = MagicMock()
    exec_res.all.return_value = [("finance@demo.example.com",), ("admin@demo.example.com",)]
    db_mock.execute.return_value = exec_res

    signatories = await get_authorized_signatories(db_mock)
    assert "finance@demo.example.com" in signatories
    assert "admin@demo.example.com" in signatories
    assert "attacker@outside.com" not in signatories


@pytest.mark.asyncio
async def test_send_for_signature_rejects_unauthorized_signer():
    db_mock = AsyncMock()
    contract = Contract(id="c-test-1", status="draft", purchase_request_id="pr-1", vendor_id="v-1")
    db_mock.get.return_value = contract

    exec_res = MagicMock()
    exec_res.all.return_value = [("authorized@company.com",)]
    db_mock.execute.return_value = exec_res

    with pytest.raises(ContractGenerationError, match="not an authorized signatory"):
        await send_for_signature(
            db=db_mock,
            kafka_producer=MagicMock(),
            contract_id="c-test-1",
            signer_email="attacker@personal.com",
        )


@pytest.mark.asyncio
async def test_sign_simulated_disabled_by_default(monkeypatch):
    monkeypatch.setenv("ENABLE_SIGN_SIMULATED", "false")
    monkeypatch.setenv("APP_ENABLE_SIGN_SIMULATED", "false")

    transport = ASGITransport(app=cra_app)
    from shared.auth.jwt_tokens import create_access_token
    token = create_access_token("user-1", "admin@demo.example.com", "admin")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/contracts/contract-123/sign-simulated",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403
        assert "Simulated signing is disabled" in r.text
