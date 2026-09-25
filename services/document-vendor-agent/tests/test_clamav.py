"""Malware-scanning governance control. No live ClamAV daemon in the test
environment, so these use a fake clamd client — clamav_client.scan_bytes
accepts an injected `client` for exactly this reason. What's under test is
OUR fail-closed/fail-open handling of clamd's response, not clamd itself.
"""
import pytest

from app.services.clamav_client import scan_bytes, ClamAVUnavailableError

# The standard, harmless EICAR antivirus test string — not real malware,
# every AV engine (including ClamAV) is designed to flag it.
EICAR_STRING = (
    r"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
).encode()


class _FakeClamdFound:
    def instream(self, _stream):
        return {"stream": ("FOUND", "Eicar-Test-Signature")}


class _FakeClamdClean:
    def instream(self, _stream):
        return {"stream": ("OK", None)}


class _FakeClamdUnreachable:
    def instream(self, _stream):
        raise ConnectionRefusedError("clamd not reachable")


class TestClamAVScanning:
    def test_eicar_string_is_flagged(self):
        result = scan_bytes(EICAR_STRING, client=_FakeClamdFound())
        assert result.clean is False
        assert "Eicar" in result.signature

    def test_clean_file_passes(self):
        result = scan_bytes(b"just a normal pdf's worth of bytes", client=_FakeClamdClean())
        assert result.clean is True

    def test_unreachable_clamav_fails_closed_not_silently_clean(self):
        """If ClamAV can't be reached, the caller must reject the upload
        (503) — never treat 'couldn't scan' as 'scanned clean'."""
        with pytest.raises(ClamAVUnavailableError):
            scan_bytes(EICAR_STRING, client=_FakeClamdUnreachable())
