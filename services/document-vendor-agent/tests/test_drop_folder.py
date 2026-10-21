"""Drop folder (app/services/inbox_watcher.py) and the control panel's Kafka
event log (app/services/event_monitor.py)."""
import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from app.api.control_panel import drop_stage
from app.services import inbox_watcher
from app.services.event_monitor import EventMonitor, summarize
from app.services.inbox_watcher import InboxFolder, ingest_file, settle
from app.services.upload_service import InvalidUploadError, MalwareDetectedError, ScanUnavailableError
from shared.drop_folder import INBOX_UPLOADER

def run(coro):
    """Own event loop, so the suite's other tests keep the default one."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


PDF = b"%PDF-1.4 quote"


@pytest.fixture
def inbox(tmp_path):
    folder = InboxFolder(tmp_path)
    folder.ensure()
    return folder


class TestInboxFolder:
    def test_file_is_ready_only_once_its_size_stops_changing(self, inbox):
        f = inbox.input / "quote.pdf"
        f.write_bytes(PDF)
        assert inbox.ready() == []  # first sighting: may still be copying
        assert inbox.ready() == [f]
        f.write_bytes(PDF + b" more")  # still being written
        assert inbox.ready() == []

    def test_readme_hidden_and_partial_files_are_ignored(self, inbox):
        for name in ("README.md", ".DS_Store", "quote.pdf.part", "x.crdownload"):
            (inbox.input / name).write_bytes(b"x")
        inbox.ready()
        assert inbox.ready() == []

    def test_claim_moves_the_file_and_a_second_claim_gets_nothing(self, inbox):
        f = inbox.input / "quote.pdf"
        f.write_bytes(PDF)
        claimed = inbox.claim(f)
        assert claimed == inbox.processing / "quote.pdf" and claimed.exists()
        assert inbox.claim(f) is None

    def test_recover_returns_files_left_mid_upload(self, inbox):
        (inbox.processing / "quote.pdf").write_bytes(PDF)
        inbox.recover()
        assert (inbox.input / "quote.pdf").exists()
        assert not any(inbox.processing.iterdir())

    def test_recover_keeps_uploaded_files_waiting_on_the_pipeline(self, inbox):
        held = inbox.processing / "doc-1"
        held.mkdir()
        (held / "quote.pdf").write_bytes(PDF)
        inbox.recover()
        assert inbox.held() == [("doc-1", held / "quote.pdf")]
        assert not any(inbox.input.iterdir())

    def test_files_dropped_in_the_old_place_move_to_input(self, inbox):
        (inbox.root / "quote.pdf").write_bytes(PDF)
        (inbox.root / "README.md").write_text("instructions")
        inbox.recover()
        assert (inbox.input / "quote.pdf").exists()
        assert (inbox.root / "README.md").exists()  # the folder's own instructions stay


def _session_factory():
    db = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=db)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory, db


class TestIngestFile:
    def _claimed(self, inbox, data=PDF):
        f = inbox.input / "quote.pdf"
        f.write_bytes(data)
        return inbox.claim(f)

    def test_clean_file_is_uploaded_as_the_drop_folder_and_held_for_the_pipeline(self, inbox, monkeypatch):
        monkeypatch.setattr(inbox_watcher, "scan_upload", AsyncMock())
        store = AsyncMock(return_value=SimpleNamespace(id="0b0e5a4c-1111-2222-3333-444455556666"))
        monkeypatch.setattr(inbox_watcher, "store_and_record_upload", store)
        factory, _ = _session_factory()

        result = run(ingest_file(factory, "producer", inbox, self._claimed(inbox)))

        assert result == "uploaded"
        args = store.await_args.args
        assert args[2] == PDF and args[3] == "quote.pdf" and args[4] == "application/pdf"
        assert args[5] == INBOX_UPLOADER
        assert inbox.held() == [("0b0e5a4c-1111-2222-3333-444455556666",
                                 inbox.processing / "0b0e5a4c-1111-2222-3333-444455556666" / "quote.pdf")]
        assert not any(inbox.processed.iterdir())  # not until the pipeline finishes

    def test_malware_goes_to_failed_with_the_reason(self, inbox, monkeypatch):
        monkeypatch.setattr(inbox_watcher, "scan_upload", AsyncMock(side_effect=MalwareDetectedError("Eicar-Test")))
        store = AsyncMock()
        monkeypatch.setattr(inbox_watcher, "store_and_record_upload", store)
        factory, db = _session_factory()

        assert run(ingest_file(factory, "producer", inbox, self._claimed(inbox))) == "failed"
        store.assert_not_awaited()
        db.commit.assert_awaited()  # the audit row is kept
        reason = next(inbox.failed.glob("*.error.txt")).read_text()
        assert "Eicar-Test" in reason

    def test_unsupported_file_goes_to_failed(self, inbox, monkeypatch):
        monkeypatch.setattr(inbox_watcher, "scan_upload", AsyncMock())
        monkeypatch.setattr(
            inbox_watcher, "store_and_record_upload",
            AsyncMock(side_effect=InvalidUploadError("unsupported file type — upload a PDF, PNG or JPEG")),
        )
        factory, _ = _session_factory()
        assert run(ingest_file(factory, "producer", inbox, self._claimed(inbox))) == "failed"
        assert "unsupported" in next(inbox.failed.glob("*.error.txt")).read_text()

    def test_scanner_down_puts_the_file_back_for_a_retry(self, inbox, monkeypatch):
        monkeypatch.setattr(inbox_watcher, "scan_upload", AsyncMock(side_effect=ScanUnavailableError("down")))
        factory, _ = _session_factory()
        assert run(ingest_file(factory, "producer", inbox, self._claimed(inbox))) == "retry"
        assert (inbox.input / "quote.pdf").exists()
        assert not any(inbox.failed.iterdir())

    def test_oversized_file_is_rejected_before_scanning(self, inbox, monkeypatch):
        scan = AsyncMock()
        monkeypatch.setattr(inbox_watcher, "scan_upload", scan)
        monkeypatch.setattr(inbox_watcher.settings, "max_upload_bytes", 4)
        factory, _ = _session_factory()
        assert run(ingest_file(factory, "producer", inbox, self._claimed(inbox))) == "failed"
        scan.assert_not_awaited()


def _held(inbox, document_id):
    directory = inbox.processing / document_id
    directory.mkdir()
    (directory / "quote.pdf").write_bytes(PDF)


def _status_factory(rows):
    """Session factory whose documents lookup answers from {id: row | None}."""
    factory, db = _session_factory()

    async def execute(_query, params):
        return SimpleNamespace(first=lambda: rows.get(params["id"]))

    db.execute = execute
    return factory


class TestSettle:
    def test_classified_document_moves_to_processed(self, inbox):
        _held(inbox, "0b0e5a4c-aaaa")
        factory = _status_factory({"0b0e5a4c-aaaa": SimpleNamespace(status="classified", error_message=None)})
        assert run(settle(factory, inbox)) == {"0b0e5a4c-aaaa": "processed"}
        [done] = inbox.processed.iterdir()
        assert done.name.endswith("_0b0e5a4c_quote.pdf")
        assert not any(inbox.processing.iterdir())

    def test_failed_pipeline_moves_to_failed_with_its_error(self, inbox):
        _held(inbox, "77aa0000-bbbb")
        factory = _status_factory({"77aa0000-bbbb": SimpleNamespace(status="failed",
                                                                     error_message="couldn't read any text")})
        assert run(settle(factory, inbox)) == {"77aa0000-bbbb": "failed"}
        log = next(inbox.failed.glob("*.error.txt")).read_text()
        assert "reason:   couldn't read any text" in log and "document: 77aa0000-bbbb" in log
        assert not any(inbox.processed.iterdir())

    def test_document_still_processing_stays_held(self, inbox):
        _held(inbox, "doc-busy")
        factory = _status_factory({"doc-busy": SimpleNamespace(status="processing", error_message=None)})
        assert run(settle(factory, inbox)) == {}
        assert len(inbox.held()) == 1

    def test_missing_document_record_is_a_failure(self, inbox):
        _held(inbox, "doc-gone")
        assert run(settle(_status_factory({}), inbox)) == {"doc-gone": "failed"}
        assert "no document record" in next(inbox.failed.glob("*.error.txt")).read_text()


class TestEventLog:
    def test_bank_details_and_extracted_fields_never_reach_the_log(self):
        raw = (
            b'{"event_type": "document.classified", "source_service": "document-vendor-agent",'
            b' "timestamp": "2026-10-10T10:00:00+00:00", "correlation_id": "c1",'
            b' "payload": {"document_id": "d1234567-x", "document_type": "quote", "needs_review": false,'
            b' "extracted_fields": {"bank_account_number": "123456789012", "total": 400},'
            b' "bank_account_number": "123456789012"}}'
        )
        entry = summarize("document.classified", 0, 7, None, raw)
        assert entry["fields"] == {"document_id": "d1234567-x", "document_type": "quote", "needs_review": False}
        assert "123456789012" not in str(entry)
        assert entry["message"] == "Document d1234567 classified as quote"

    def test_unreadable_message_is_still_listed(self):
        entry = summarize("document.ingested", 2, 9, 1760090400000, b"not json")
        assert entry["event_type"] == "document.ingested" and entry["timestamp"].startswith("2025-10-10")

    def test_since_returns_only_newer_events_up_to_the_limit(self):
        monitor = EventMonitor("broker", maxlen=3)
        for i in range(5):
            monitor.add({"topic": "t", "message": str(i)})
        assert [e["seq"] for e in monitor.events] == [3, 4, 5]
        assert [e["seq"] for e in monitor.since(3, 10)] == [4, 5]
        assert [e["seq"] for e in monitor.since(0, 1)] == [5]


def _drop(**overrides):
    row = dict(
        document_status="classified", document_type="quote", needs_review=False, is_likely_duplicate=False,
        error_message=None, request_id=None, request_status=None, spend_tier=None, contract_id=None,
        contract_status=None, esign_provider_ref=None, esign_action=None, esign_payload=None,
    )
    row.update(overrides)
    return row


class TestDropStage:
    @pytest.mark.parametrize("row, stage", [
        (_drop(document_status="processing"), "processing"),
        (_drop(document_status="failed", error_message="couldn't read any text"), "failed"),
        (_drop(needs_review=True), "review"),
        (_drop(document_type="invoice"), "stopped"),
        (_drop(is_likely_duplicate=True), "stopped"),
        (_drop(request_id="r", request_status="pending_approval", spend_tier="manager"), "approval"),
        (_drop(request_id="r", request_status="rejected"), "rejected"),
        (_drop(request_id="r", request_status="approved", contract_id="c", contract_status="pending_signature"), "signature"),
        (_drop(request_id="r", request_status="fulfilled", contract_id="c", contract_status="signed"), "signed"),
    ])
    def test_stage(self, row, stage):
        assert drop_stage(row)[0] == stage

    def test_says_emailed_only_for_a_real_provider(self):
        sent = dict(request_id="r", request_status="approved", contract_id="c", contract_status="pending_signature")
        assert "emailed" in drop_stage(_drop(**sent, esign_provider_ref="docusign-env-1"))[1]
        assert "simulated" in drop_stage(_drop(**sent, esign_provider_ref="docusign-ref-1"))[1]

    def test_unsent_contract_says_why(self):
        stage, label = drop_stage(_drop(
            request_id="r", request_status="approved", contract_id="c", contract_status="draft",
            esign_action="auto_send_skipped", esign_payload={"reason": "no signer email"},
        ))
        assert stage == "contract" and label.endswith("no signer email")
