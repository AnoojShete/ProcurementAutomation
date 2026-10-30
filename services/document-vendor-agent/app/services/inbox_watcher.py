"""Drop folder: files put in ./inbox/input are ingested with no clicks.

Runs inside document-vendor-agent-worker (./inbox is mounted at /inbox).
The three folders a person sees:

    inbox/input/      drop files here
    inbox/processed/  read successfully (the pipeline finished)
    inbox/failed/     rejected or failed, each with a .error.txt saying why

Every few seconds the watcher looks at input/; a file whose size hasn't
changed since the last look (so it's finished copying) is

    1. claimed: renamed into inbox/.processing/ (an atomic rename, so two
       workers never take the same file),
    2. uploaded exactly like a UI upload: ClamAV scan, MinIO, a documents
       row and document.ingested through the outbox, with
       uploaded_by = INBOX_UPLOADER (shared/drop_folder.py),
    3. held in inbox/.processing/<document id>/ while the pipeline reads it,
    4. moved to processed/ once the document is classified, or to failed/
       when the pipeline fails (the document's error message goes into the
       .error.txt). A file rejected at upload (malware, not a PDF/image,
       too big) goes straight to failed/. If ClamAV or MinIO is down the
       file goes back into input/ and is retried on a later pass.

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

from sqlalchemy import text

from app.config import settings
from app.services.upload_service import (
    InvalidUploadError, MalwareDetectedError, ScanUnavailableError, StorageUnavailableError,
    safe_filename, scan_upload, store_and_record_upload,
)
from shared.drop_folder import INBOX_UPLOADER

logger = logging.getLogger(__name__)
mimetypes.add_type("image/webp", ".webp")  # Python < 3.13 doesn't know it

INPUT, PROCESSING, PROCESSED, FAILED = "input", ".processing", "processed", "failed"
# Partial downloads / editor temp files are never picked up.
_SKIP_SUFFIXES = (".part", ".tmp", ".crdownload", ".download", ".error.txt")
_SKIP_NAMES = {"README.md"}  # the folder's own instructions


class InboxFolder:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.input = self.root / INPUT
        self.processing = self.root / PROCESSING
        self.processed = self.root / PROCESSED
        self.failed = self.root / FAILED
        # name -> (size, mtime) seen on the previous pass
        self._last_seen: dict[str, tuple[int, float]] = {}

    def ensure(self) -> None:
        for d in (self.root, self.input, self.processing, self.processed, self.failed):
            d.mkdir(parents=True, exist_ok=True)

    def recover(self) -> None:
        """Files left in .processing by a worker that died mid-upload go
        back into input/. The upload commits atomically, so at worst a
        file that had already been recorded is ingested again — and the
        pipeline's duplicate detection flags it. Files already uploaded
        (held under .processing/<document id>/) stay to be settled.
        Files dropped straight into ./inbox (the old place) move to input/."""
        for f in self.processing.iterdir():
            if f.is_file():
                os.replace(f, self.input / f.name)
                logger.warning(f"[inbox] {f.name} was left mid-upload; queued again")
        for f in self._files(self.root):
            os.replace(f, self.input / f.name)
            logger.info(f"[inbox] {f.name} was dropped in ./inbox; moved to ./inbox/input")

    @staticmethod
    def _files(directory: Path) -> list[Path]:
        return sorted(
            (f for f in directory.iterdir()
             if f.is_file() and not f.name.startswith(".") and f.name not in _SKIP_NAMES
             and not f.name.endswith(_SKIP_SUFFIXES)),
            key=lambda f: f.stat().st_mtime,
        )

    def waiting(self) -> list[Path]:
        return self._files(self.input)

    def held(self) -> list[tuple[str, Path]]:
        """(document id, file) for uploaded files waiting on the pipeline."""
        return [
            (d.name, f)
            for d in sorted(self.processing.iterdir()) if d.is_dir()
            for f in d.iterdir() if f.is_file()
        ]

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

    def hold(self, f: Path, document_id: str) -> Path:
        """Uploaded: keep it under .processing/<document id>/ until the
        pipeline says how it went."""
        directory = self.processing / document_id
        directory.mkdir(exist_ok=True)
        dest = directory / f.name
        os.replace(f, dest)
        return dest

    def done(self, f: Path, document_id: str) -> Path:
        dest = self._stamped(self.processed, f.name, document_id[:8])
        shutil.move(str(f), dest)
        self._drop_hold_dir(f)
        return dest

    def fail(self, f: Path, reason: str, document_id: str = "") -> Path:
        dest = self._stamped(self.failed, f.name, document_id[:8])
        shutil.move(str(f), dest)
        self._drop_hold_dir(f)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        log = [f"file:     {f.name}", f"failed:   {stamp}"]
        if document_id:
            log.append(f"document: {document_id}")
        log.append(f"reason:   {reason}")
        dest.with_name(dest.name + ".error.txt").write_text("\n".join(log) + "\n")
        return dest

    def _drop_hold_dir(self, f: Path) -> None:
        if f.parent.parent == self.processing:
            try:
                f.parent.rmdir()
            except OSError:
                pass

    def release(self, f: Path) -> None:
        os.replace(f, self.input / f.name)


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

    inbox.hold(path, str(doc.id))
    logger.info(f"[inbox] {name} -> document {doc.id} ({safe_filename(name)} stored in MinIO, document.ingested queued)")
    return "uploaded"


_DOCUMENT_STATUS = text("SELECT status, error_message FROM documents WHERE id = CAST(:id AS uuid)")


async def settle(session_factory, inbox: InboxFolder) -> dict[str, str]:
    """Moves each held file to processed/ or failed/ once its document's
    pipeline has finished. Returns {document id: "processed" | "failed"}
    for the files moved on this pass."""
    held = inbox.held()
    if not held:
        return {}
    moved = {}
    async with session_factory() as db:
        for document_id, f in held:
            row = (await db.execute(_DOCUMENT_STATUS, {"id": document_id})).first()
            if row is None:
                inbox.fail(f, "no document record (the upload was rolled back)", document_id)
                moved[document_id] = "failed"
            elif row.status == "failed":
                inbox.fail(f, row.error_message or "processing failed", document_id)
                moved[document_id] = "failed"
                logger.warning(f"[inbox] {f.name} -> failed/: {row.error_message}")
            elif row.status == "classified":
                inbox.done(f, document_id)
                moved[document_id] = "processed"
                logger.info(f"[inbox] {f.name} -> processed/")
    return moved


async def run_inbox_watcher(session_factory, kafka_producer) -> None:
    inbox = InboxFolder(settings.inbox_dir)
    try:
        inbox.ensure()
        inbox.recover()
    except OSError as e:
        logger.error(f"[inbox] drop folder {settings.inbox_dir} is not usable ({e}); watcher not started")
        return
    logger.info(f"[inbox] watching {inbox.input} every {settings.inbox_poll_seconds}s")
    while True:
        try:
            await settle(session_factory, inbox)
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
