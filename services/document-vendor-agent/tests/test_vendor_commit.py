"""A vendor created from a document is committed straight away, in its own
transaction: approval-inventory-agent's invoice ledger references it
(fk_invoice_matches_vendor) before the document's transaction commits, and
can't see uncommitted rows. Before the fix every invoice from a new vendor
failed with a 500 and retried, creating a new vendor each time."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.vendor_matching import find_or_create_vendor


def _db(existing_vendors):
    db = AsyncMock()
    db.add = MagicMock()
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = existing_vendors
    db.execute.return_value = rows
    db.get.side_effect = lambda model, vendor_id: SimpleNamespace(id=vendor_id, name="loaded")
    return db


def _factory():
    session = AsyncMock()
    session.add = MagicMock()
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    return factory, session


@pytest.mark.asyncio
async def test_new_vendor_committed_in_its_own_transaction():
    db = _db([])
    factory, vendor_session = _factory()

    match = await find_or_create_vendor(db, "Brand New Supplies Ltd", session_factory=factory)

    assert match.match_type == "new"
    created = vendor_session.add.call_args.args[0]
    assert created.name == "Brand New Supplies Ltd"
    vendor_session.commit.assert_awaited_once()
    db.add.assert_not_called()  # not left in the caller's open transaction
    assert match.vendor.id == created.id  # and loaded into the caller's session


@pytest.mark.asyncio
async def test_existing_vendor_creates_nothing():
    existing = SimpleNamespace(id="v1", name="Dell Technologies", normalized_name="dell technologies")
    db = _db([existing])
    factory, vendor_session = _factory()

    match = await find_or_create_vendor(db, "Dell Technologies", session_factory=factory)

    assert match.match_type == "existing" and match.vendor is existing
    factory.assert_not_called()
