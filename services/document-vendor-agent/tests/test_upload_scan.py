"""scan_upload itself (the endpoint tests mock it out): clean files pass,
infected files and an unreachable ClamAV are refused. Uses a fake clamd
client, so no ClamAV daemon is needed."""
from unittest.mock import AsyncMock, patch

import pytest

from app.services import upload_service
from app.services.upload_service import MalwareDetectedError, ScanUnavailableError, scan_upload

PDF = b"%PDF-1.4\n%%EOF"


class FakeClamd:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def instream(self, _stream):
        if self.error:
            raise self.error
        return self.result


@pytest.fixture(autouse=True)
def no_audit():
    with patch.object(upload_service, "write_audit_log", AsyncMock()) as audit:
        yield audit


class TestScanUpload:
    @pytest.mark.asyncio
    async def test_clean_file_passes(self):
        await scan_upload(PDF, AsyncMock(), "inv.pdf", clamd_client=FakeClamd({"stream": ("OK", None)}))

    @pytest.mark.asyncio
    async def test_infected_file_is_rejected(self, no_audit):
        client = FakeClamd({"stream": ("FOUND", "Eicar-Test-Signature")})
        with pytest.raises(MalwareDetectedError):
            await scan_upload(PDF, AsyncMock(), "inv.pdf", clamd_client=client)
        assert no_audit.await_args.kwargs["action"] == "upload_rejected_malware"

    @pytest.mark.asyncio
    async def test_unreachable_clamav_fails_closed(self):
        client = FakeClamd(error=ConnectionRefusedError("no clamd"))
        with pytest.raises(ScanUnavailableError):
            await scan_upload(PDF, AsyncMock(), "inv.pdf", clamd_client=client)

    @pytest.mark.asyncio
    async def test_scan_skipped_when_disabled(self, monkeypatch):
        monkeypatch.setattr(upload_service.settings, "clamav_enabled", False)
        client = FakeClamd(error=AssertionError("should not be called"))
        await scan_upload(PDF, AsyncMock(), "inv.pdf", clamd_client=client)
