"""Drop folder: files put in ./inbox are ingested with no clicks.

Runs inside document-vendor-agent-worker (./inbox is mounted at /inbox).
Every few seconds it looks at the folder; a file whose size hasn't changed
since the last look (so it's finished copying) is

    1. claimed: renamed into inbox/.processing/ (an atomic rename, so two
       workers never take the same file),
    2. uploaded exactly like a UI upload: ClamAV scan, MinIO, a documents
       row and document.ingested through the outbox, with
       uploaded_by = INBOX_UPLOADER (shared/drop_folder.py),
    3. moved to inbox/processed/ — or to inbox/failed/ with a .error.txt
       next to it when the file is rejected (malware, not a PDF/image, too
       big). If ClamAV or MinIO is down the file goes back into the inbox
       and is retried on a later pass.

From document.ingested on, it's the normal pipeline; the rest of the
automation (purchase request -> approval -> contract -> e-signature) is
described in shared/drop_folder.py.
"""
import asyncio
import logging
import mimetypes
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.services.upload_service import (
    InvalidUploadError, MalwareDetectedError, ScanUnavailableError, StorageUnavailableError,
    safe_filename, scan_upload, store_and_record_upload,
)
from shared.drop_folder import INBOX_UPLOADER

logger = logging.getLogger(__name__)

PROCESSING, PROCESSED, FAILED = ".processing", "processed", "failed"
# Partial downloads / editor temp files are never picked up.
_SKIP_SUFFIXES = (".part", ".tmp", ".crdownload", ".download", ".error.txt")
_SKIP_NAMES = {"README.md"}  # the folder's own instructions


class InboxFolder:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.processing = self.root / PROCESSING
        self.processed = self.root / PROCESSED
        self.failed = self.root / FAILED
        # name -> (size, mtime) seen on the previous pass
        self._last_seen: dict[str, tuple[int, float]] = {}

    def ensure(self) -> None:
        for d in (self.root, self.processing, self.processed, self.failed):
            d.mkdir(parents=True, exist_ok=True)

    def recover(self) -> None:
        """Files left in .processing by a worker that died mid-upload go
        back into the inbox. The upload commits atomically, so at worst a
        file that had already been recorded is ingested again — and the
        pipeline's duplicate detection flags it."""
        for f in self.processing.iterdir():
            if f.is_file():
                os.replace(f, self.root / f.name)
                logger.warning(f"[inbox] {f.name} was left mid-upload; queued again")

    def waiting(self) -> list[Path]:
        return sorted(
            (f for f in self.root.iterdir()
             if f.is_file() and not f.name.startswith(".") and f.name not in _SKIP_NAMES
             and not f.name.endswith(_SKIP_SUFFIXES)),
            key=lambda f: f.stat().st_mtime,
        )

    def ready(self) -> list[Path]:
        """Waiting files whose size and mtime didn't change since the last
        call — a file still being copied in is left for the next pass."""
        current = {}
        ready = []
        for f in self.waiting():
            st = f.stat()
            current[f.name] = (st.st_size, st.st_mtime)
            if st.st_size > 0 and self._last_seen.get(f.name) == current[f.name]:
                ready.append(f)
        self._last_seen = current
        return ready

    def claim(self, f: Path) -> Path | None:
        target = self.processing / f.name
        try:
            os.replace(f, target)
        except FileNotFoundError:
            return None  # another worker took it
        self._last_seen.pop(f.name, None)
        return target

    def _stamped(self, directory: Path, name: str, tag: str = "") -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return directory / f"{stamp}{'_' + tag if tag else ''}_{name}"

    def done(self, f: Path, document_id: str) -> Path:
        dest = self._stamped(self.processed, f.name, document_id[:8])
        shutil.move(str(f), dest)
        return dest

    def fail(self, f: Path, reason: str) -> Path:
        dest = self._stamped(self.failed, f.name)
        shutil.move(str(f), dest)
        dest.with_name(dest.name + ".error.txt").write_text(reason + "\n")
        return dest

    def release(self, f: Path) -> None:
        os.replace(f, self.root / f.name)


async def ingest_file(session_factory, kafka_producer, inbox: InboxFolder, path: Path) -> str:
    """Uploads one claimed file. Returns "processed", "failed" or "retry"."""
    name = path.name
    data = path.read_bytes()
    if len(data) > settings.max_upload_bytes:
        inbox.fail(path, f"file is larger than {settings.max_upload_bytes // (1024 * 1024)} MB")
        logger.warning(f"[inbox] {name} rejected: too large ({len(data)} bytes)")
        return "failed"

    async with session_factory() as db:
        try:
            await scan_upload(data, db, name)
        except MalwareDetectedError as e:
            await db.commit()  # keep the audit row
            inbox.fail(path, f"malware detected: {e.signature}")
            logger.warning(f"[inbox] {name} rejected: malware ({e.signature})")
            return "failed"
        except ScanUnavailableError as e:
            await db.commit()
            inbox.release(path)
            logger.warning(f"[inbox] {name}: virus scanner unavailable ({e}); will retry")
            return "retry"

        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        try:
            doc = await store_and_record_upload(db, kafka_producer, data, name, content_type, INBOX_UPLOADER,
                                                source="folder")
        except InvalidUploadError as e:
            await db.rollback()
            inbox.fail(path, str(e))
            logger.warning(f"[inbox] {name} rejected: {e}")
            return "failed"
        except StorageUnavailableError as e:
            await db.rollback()
            inbox.release(path)
            logger.warning(f"[inbox] {name}: MinIO unavailable ({e}); will retry")
            return "retry"

    inbox.done(path, doc.id)
    logger.info(f"[inbox] {name} -> document {doc.id} ({safe_filename(name)} stored in MinIO, document.ingested queued)")
    return "processed"


async def run_inbox_watcher(session_factory, kafka_producer) -> None:
    inbox = InboxFolder(settings.inbox_dir)
    try:
        inbox.ensure()
        inbox.recover()
    except OSError as e:
        logger.error(f"[inbox] drop folder {settings.inbox_dir} is not usable ({e}); watcher not started")
        return
    logger.info(f"[inbox] watching {settings.inbox_dir} every {settings.inbox_poll_seconds}s")
    while True:
        try:
            for f in inbox.ready():
                claimed = inbox.claim(f)
                if claimed is None:
                    continue
                logger.info(f"[inbox] picked up {f.name}")
                try:
                    await ingest_file(session_factory, kafka_producer, inbox, claimed)
                except Exception as e:
                    # Unexpected: keep the file for another try rather than lose it.
                    logger.error(f"[inbox] {f.name} failed unexpectedly, will retry: {e}", exc_info=True)
                    if claimed.exists():
                        inbox.release(claimed)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[inbox] pass failed: {e}", exc_info=True)
        await asyncio.sleep(settings.inbox_poll_seconds)
