"""FR-14: vendors are screened against the consolidated sanctions list;
near-matches are flagged, unrelated companies aren't, a match is a hard
override until finance clears it with a reason."""
import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from app.services import sanctions  # noqa: E402

# A slice in the same format as OpenSanctions' targets.simple.csv.
CSV = '''id,schema,name,aliases,birth_date,countries,addresses,identifiers,sanctions,phones,emails,dataset,first_seen,last_seen,last_change
ofac-1,Company,Rosneft Oil Company,PJSC Rosneft;OAO NK Rosneft,,ru,,,,,,US OFAC SDN;EU FSF,,,
eu-2,Company,Bank Rossiya,AB Rossiya,,ru,,,,,,EU FSF,,,
un-3,Organization,Al Qadi Trading LLC,,,ae,,,,,,UN SC,,,
ofac-4,Person,Ivan Petrov,,1970-01-01,ru,,,,,,US OFAC SDN,,,
uk-5,LegalEntity,Sea Breeze Shipping Limited,,,ir,,,,,,UK HMT,,,
'''


@pytest.fixture
def index():
    built = sanctions.build_index(CSV, "test-v1")
    flat, owners = [], []
    for i, e in enumerate(built["entries"]):
        for n in e["names"]:
            flat.append(sanctions.normalise(n))
            owners.append((i, n))
    built["_flat"], built["_owners"] = flat, owners
    return built


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_normalise_drops_case_punctuation_and_legal_suffixes():
    assert sanctions.normalise("ROSNEFT OIL COMPANY, PJSC") == "rosneft oil"
    assert sanctions.normalise("HP India Sales Pvt. Ltd.") == "hp india sales"
    assert sanctions.normalise("Société Générale S.A.") == "societe generale"


def test_index_keeps_companies_and_organisations_only(index):
    names = {e["name"] for e in index["entries"]}
    assert names == {"Rosneft Oil Company", "Bank Rossiya", "Al Qadi Trading LLC", "Sea Breeze Shipping Limited"}
    assert "PJSC Rosneft" in next(e for e in index["entries"] if e["id"] == "ofac-1")["names"]


@pytest.mark.parametrize("vendor", ["Rosneft Oil Co", "ROSNEFT OIL COMPANY PJSC", "PJSC Rosneft", "Bank Rossiya JSC",
                                    "Al-Qadi Trading L.L.C.", "Sea Breeze Shipping Ltd"])
def test_near_matches_are_flagged(index, vendor):
    hits = sanctions.screen_name(vendor, index, cutoff=90)
    assert hits, f"{vendor} should be flagged"
    assert hits[0]["score"] >= 90 and hits[0]["lists"]


@pytest.mark.parametrize("vendor", ["HP India Sales Pvt Ltd", "Zoho Corporation", "Bank of Baroda", "Rossi Trading Co",
                                    "Sea Shell Logistics", "Ivan Petrov Consulting"])
def test_unrelated_companies_are_not_flagged(index, vendor):
    assert sanctions.screen_name(vendor, index, cutoff=90) == []


def test_override_input_follows_the_latest_screening():
    assert sanctions.sanctions_override_input(None) is None
    assert sanctions.sanctions_override_input(SimpleNamespace(status="potential_match")) is True
    assert sanctions.sanctions_override_input(SimpleNamespace(status="cleared")) is False
    assert sanctions.sanctions_override_input(SimpleNamespace(status="clear")) is False


def _db(previous_cleared=None):
    db = AsyncMock()
    db.add = MagicMock()
    res = MagicMock()
    res.scalars.return_value.first.return_value = previous_cleared
    db.execute.return_value = res
    return db


def test_screening_records_a_potential_match(index, monkeypatch):
    monkeypatch.setattr(sanctions, "threshold", lambda: 90.0)
    row = run(sanctions.screen_vendor(_db(), SimpleNamespace(id="v-1", name="Rosneft Oil Co"), index=index))
    assert row.status == "potential_match" and row.matches[0]["entity_id"] == "ofac-1"
    clean = run(sanctions.screen_vendor(_db(), SimpleNamespace(id="v-2", name="Zoho Corporation"), index=index))
    assert clean.status == "clear" and clean.matches == []


def test_a_cleared_match_stays_cleared_on_a_newer_list(index, monkeypatch):
    monkeypatch.setattr(sanctions, "threshold", lambda: 90.0)
    cleared = SimpleNamespace(matches=[{"entity_id": "ofac-1"}], screened_by="fin@x", justification="Different company, CIN checked")
    row = run(sanctions.screen_vendor(_db(cleared), SimpleNamespace(id="v-1", name="Rosneft Oil Co"), index=index))
    assert row.status == "cleared" and "fin@x" in row.justification


def test_clearing_needs_an_open_match():
    db = _db(None)
    with pytest.raises(ValueError):
        run(sanctions.clear_flag(db, "v-1", "fin@x", "A long enough justification text"))
    db = _db(SimpleNamespace(status="potential_match", list_version="v1", screened_name="X", matches=[{"entity_id": "e"}],
                             threshold=90))
    row = run(sanctions.clear_flag(db, "v-1", "fin@x", "  Different company — checked the CIN  "))
    assert row.status == "cleared" and row.justification == "Different company — checked the CIN"


def test_no_list_means_not_checked(tmp_path):
    assert sanctions.load_index(str(tmp_path / "missing.json.gz")) is None
