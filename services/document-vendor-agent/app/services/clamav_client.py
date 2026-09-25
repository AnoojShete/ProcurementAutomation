"""ClamAV malware scanning, streamed in-memory before anything is written
to MinIO (governance control B — see the team's addendum).

Fail-closed: if ClamAV can't be reached, callers must treat that as a
scan failure (503, "scanning unavailable") and refuse the upload — never
silently skip scanning. `scan_bytes` raises ClamAVUnavailableError for
that case rather than returning a "clean" result, so a caller can't
accidentally treat "couldn't check" as "checked, and it's fine".
"""
import hashlib
import logging
from dataclasses import dataclass
from typing import Optional

import clamd

from app.config import settings

logger = logging.getLogger(__name__)


class ClamAVUnavailableError(Exception):
    """Raised when ClamAV cannot be reached or errors out — callers must
    fail the upload closed (503), never skip scanning silently."""


@dataclass
class ScanResult:
    clean: bool
    signature: Optional[str] = None  # e.g. "Eicar-Test-Signature" when clean=False


def get_clamd_client():
    """Separate factory (rather than a module-level singleton) so tests can
    monkeypatch app.services.clamav_client.get_clamd_client to inject a
    fake client without a live ClamAV daemon."""
    return clamd.ClamdNetworkSocket(
        host=settings.clamav_host, port=settings.clamav_port, timeout=settings.clamav_timeout_seconds,
    )


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def scan_bytes(data: bytes, client=None) -> ScanResult:
    """Streams `data` through ClamAV's INSTREAM command. Never writes the
    file to disk to do this. Raises ClamAVUnavailableError on any
    connectivity/protocol failure so the caller fails closed."""
    if client is None:
        client = get_clamd_client()
    try:
        result = client.instream(_as_stream(data))
    except Exception as e:
        raise ClamAVUnavailableError(f"ClamAV scan failed: {e}") from e

    # python-clamd's instream() returns {"stream": (status, reason)}
    status, reason = result.get("stream", ("ERROR", "no result from clamd"))
    if status == "ERROR":
        raise ClamAVUnavailableError(f"ClamAV returned an error status: {reason}")
    if status == "FOUND":
        logger.warning(f"ClamAV flagged upload (sha256={sha256_hex(data)}): {reason}")
        return ScanResult(clean=False, signature=reason)
    return ScanResult(clean=True)


def _as_stream(data: bytes):
    import io
    return io.BytesIO(data)
