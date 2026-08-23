"""
Tests for the contract.signed Kafka consumer handler.

When a contract.signed event arrives:
  1. The linked purchase_request status must become 'fulfilled'.
  2. For license/saas request types, the corresponding License row
     must be activated (status = 'active').

These are the exact behaviours documented as a missing scope item in Prompt 2.
"""
import pytest
import asyncio
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.kafka.consumer import _handle_contract_signed, _activate_license_for_request


class FakePurchaseRequest:
    def __init__(self, id, request_type, vendor_id, items=None, status="approved"):
        self.id = id
        self.request_type = request_type
        self.vendor_id = vendor_id
        self.items = items or []
        self.status = status


class FakeContract:
    def __init__(self, id, purchase_request_id, vendor_id):
        self.id = id
        self.purchase_request_id = purchase_request_id
        self.vendor_id = vendor_id


class FakeLicense:
    def __init__(self, id, app_name, vendor_id, status="inactive"):
        self.id = id
        self.app_name = app_name
        self.vendor_id = vendor_id
        self.status = status


@pytest.mark.asyncio
class TestContractSignedHandler:
    """Tests for the contract.signed Kafka event handler."""

    async def test_purchase_request_marked_fulfilled(self):
        """When contract.signed arrives, the linked purchase_request must become 'fulfilled'."""
        req = FakePurchaseRequest(
            id="req-001",
            request_type="hardware",   # hardware: no license to activate
            vendor_id="vendor-001",
        )
        contract = FakeContract(
            id="contract-001",
            purchase_request_id="req-001",
            vendor_id="vendor-001",
        )

        mock_session = AsyncMock()

        # First execute → fetch contract
        # Second execute → fetch purchase_request
        mock_session.execute = AsyncMock(side_effect=[
            _make_scalar_result(contract),
            _make_scalar_result(req),
        ])
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        with patch("app.kafka.consumer.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            payload = {
                "contract_id": "contract-001",
                "signed_by": "manager@company.com",
                "signed_at": "2026-08-23T12:00:00Z",
                "esign_provider_ref": "documenso-ref-001",
            }
            await _handle_contract_signed(payload, {"event_type": "contract.signed"})

        assert req.status == "fulfilled"

    async def test_license_activated_for_license_request(self):
        """For a license-type request, the corresponding license row must be activated."""
        lic = FakeLicense(
            id="lic-001",
            app_name="Microsoft 365 E3",
            vendor_id="vendor-001",
            status="inactive",
        )
        req = FakePurchaseRequest(
            id="req-002",
            request_type="license",
            vendor_id="vendor-001",
            items=[{"license_id": "lic-001", "app_name": "Microsoft 365 E3"}],
        )
        contract = FakeContract(
            id="contract-002",
            purchase_request_id="req-002",
            vendor_id="vendor-001",
        )

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[
            _make_scalar_result(contract),
            _make_scalar_result(req),
            _make_scalar_result(lic),   # license lookup by license_id in items
        ])
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        with patch("app.kafka.consumer.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            payload = {
                "contract_id": "contract-002",
                "signed_by": "finance@company.com",
                "signed_at": "2026-08-23T12:00:00Z",
                "esign_provider_ref": "documenso-ref-002",
            }
            await _handle_contract_signed(payload, {"event_type": "contract.signed"})

        assert req.status == "fulfilled"
        assert lic.status == "active"

    async def test_saas_license_activated_by_vendor_fallback(self):
        """For a saas request without explicit license_id in items, activate by vendor match."""
        lic = FakeLicense(
            id="lic-002",
            app_name="Slack Enterprise",
            vendor_id="vendor-002",
            status="inactive",
        )
        req = FakePurchaseRequest(
            id="req-003",
            request_type="saas",
            vendor_id="vendor-002",
            items=[],  # no explicit license_id — must fall back to vendor match
        )
        contract = FakeContract(
            id="contract-003",
            purchase_request_id="req-003",
            vendor_id="vendor-002",
        )

        mock_session = AsyncMock()
        # Provide the vendor-based license lookup result
        mock_scalars = MagicMock()
        mock_scalars.first = MagicMock(return_value=lic)
        mock_scalars_result = MagicMock()
        mock_scalars_result.scalars = MagicMock(return_value=mock_scalars)

        mock_session.execute = AsyncMock(side_effect=[
            _make_scalar_result(contract),
            _make_scalar_result(req),
            mock_scalars_result,   # vendor-match license query
        ])
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        with patch("app.kafka.consumer.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            payload = {
                "contract_id": "contract-003",
                "signed_by": "cto@company.com",
                "signed_at": "2026-08-23T12:00:00Z",
                "esign_provider_ref": "documenso-ref-003",
            }
            await _handle_contract_signed(payload, {"event_type": "contract.signed"})

        assert req.status == "fulfilled"

    async def test_hardware_request_no_license_activation(self):
        """Hardware requests should be marked fulfilled but no license activation needed."""
        req = FakePurchaseRequest(
            id="req-004",
            request_type="hardware",
            vendor_id="vendor-003",
        )
        contract = FakeContract(
            id="contract-004",
            purchase_request_id="req-004",
            vendor_id="vendor-003",
        )

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[
            _make_scalar_result(contract),
            _make_scalar_result(req),
            # No license lookup expected for hardware
        ])
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        with patch("app.kafka.consumer.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            payload = {
                "contract_id": "contract-004",
                "signed_by": "procurement@company.com",
                "signed_at": "2026-08-23T12:00:00Z",
                "esign_provider_ref": "documenso-ref-004",
            }
            await _handle_contract_signed(payload, {"event_type": "contract.signed"})

        assert req.status == "fulfilled"
        # No license lookup should have been triggered — exactly 2 DB calls
        assert mock_session.execute.call_count == 2

    async def test_missing_contract_is_a_noop(self):
        """If no contract found in DB, the handler should not raise and do nothing."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=_make_scalar_result(None))
        mock_session.commit = AsyncMock()

        with patch("app.kafka.consumer.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            payload = {
                "contract_id": "nonexistent-contract",
                "signed_by": "someone",
                "signed_at": "2026-08-23T12:00:00Z",
                "esign_provider_ref": "ref-000",
            }
            # Should not raise
            await _handle_contract_signed(payload, {"event_type": "contract.signed"})

        mock_session.commit.assert_not_called()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_scalar_result(value):
    """Build a mock that mimics SQLAlchemy's scalar_one_or_none() pattern."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=value)
    return mock_result
