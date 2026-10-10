"""Admin control panel: the drop-folder automation end to end.

    GET /admin/control-panel/events   live Kafka event log (event_monitor.py)
    GET /admin/control-panel/inbox    drop folder + where each dropped file is now
    GET /admin/control-panel/storage  MinIO connection, bucket contents

DocuSign's status comes from contract-risk-agent (GET /contracts/esign/status),
which owns the e-sign integration.
"""
import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.schemas import DataResponse
from app.services.inbox_watcher import InboxFolder
from app.services.storage import get_minio_client
from shared.auth import require_role
from shared.drop_folder import INBOX_UPLOADER

router = APIRouter(dependencies=[Depends(require_role("admin"))])


@router.get("/events")
async def get_events(request: Request, after: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=500)):
    monitor = getattr(request.app.state, "event_monitor", None)
    if monitor is None:
        return DataResponse(data={"status": {"connected": False, "error": "event monitor is disabled"},
                                  "events": [], "latest_seq": 0})
    return DataResponse(data={"status": monitor.status(), "events": monitor.since(after, limit),
                              "latest_seq": monitor.seq})


_RECENT_DROPS = text("""
    SELECT d.id::text AS document_id, d.original_filename, d.status AS document_status,
           d.document_type, d.needs_review, d.is_likely_duplicate, d.error_message,
           d.uploaded_at, d.total::float AS total, d.currency, d.vendor_id::text AS vendor_id,
           pr.id::text AS request_id, pr.status AS request_status, pr.spend_tier,
           c.id::text AS contract_id, c.status AS contract_status, c.esign_provider_ref, c.signed_at,
           note.action AS esign_action, note.payload AS esign_payload
    FROM documents d
    LEFT JOIN LATERAL (
        SELECT id, status, spend_tier FROM purchase_requests
        WHERE document_id = d.id ORDER BY created_at LIMIT 1
    ) pr ON true
    LEFT JOIN LATERAL (
        SELECT id, status, esign_provider_ref, signed_at FROM contracts
        WHERE purchase_request_id = pr.id ORDER BY created_at DESC LIMIT 1
    ) c ON true
    LEFT JOIN LATERAL (
        SELECT action, payload FROM audit_log
        WHERE entity_id = c.id AND action IN ('sent_for_signature', 'auto_send_skipped', 'auto_send_failed')
        ORDER BY created_at DESC LIMIT 1
    ) note ON true
    WHERE d.uploaded_by = :uploader
    ORDER BY d.uploaded_at DESC
    LIMIT :limit
""")


def drop_stage(r: dict) -> tuple[str, str]:
    """(stage key, what's happening) for one dropped file, furthest step first."""
    if r["contract_status"] == "signed":
        return "signed", "Contract signed"
    if r["contract_status"] == "pending_signature":
        ref = r["esign_provider_ref"] or ""
        if ref.startswith(("docusign-env-", "documenso-doc-")):
            return "signature", "Out for signature — the signer was emailed"
        return "signature", "Out for signature (simulated — no e-sign provider configured, nothing emailed)"
    if r["contract_id"]:
        if r["esign_action"] in ("auto_send_skipped", "auto_send_failed"):
            reason = (r["esign_payload"] or {}).get("reason", "")
            return "contract", f"Contract ready, not sent: {reason}"
        return "contract", "Contract generated, sending for signature"
    if r["request_status"] == "rejected":
        return "rejected", "Purchase request rejected"
    if r["request_status"] == "pending_approval":
        return "approval", f"Waiting for approval ({r['spend_tier']})"
    if r["request_id"]:
        return "approval", "Approved, generating contract"
    if r["document_status"] == "failed":
        return "failed", r["error_message"] or "Processing failed"
    if r["document_status"] in ("pending", "processing"):
        return "processing", r["error_message"] or "Reading the document"
    if r["is_likely_duplicate"]:
        return "stopped", "Duplicate of an earlier document — no request created"
    if r["needs_review"]:
        return "review", "Needs review before a purchase request is created"
    if r["document_type"] != "quote":
        return "stopped", f"Classified as {r['document_type']} — only quotes start a purchase"
    return "processing", "Creating purchase request"


@router.get("/inbox")
async def get_inbox(limit: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    inbox = InboxFolder(settings.inbox_dir)
    folder = {"mounted": inbox.root.is_dir(), "waiting": [], "failed": []}
    if folder["mounted"]:
        folder["waiting"] = [f.name for f in inbox.waiting()]
        if inbox.processing.is_dir():
            folder["waiting"] += [f.name for f in inbox.processing.iterdir() if f.is_file()]
        if inbox.failed.is_dir():
            errors = sorted(inbox.failed.glob("*.error.txt"), key=lambda f: f.stat().st_mtime, reverse=True)[:10]
            folder["failed"] = [
                {"name": e.name.removesuffix(".error.txt"), "reason": e.read_text().strip()} for e in errors
            ]

    rows = (await db.execute(_RECENT_DROPS, {"uploader": INBOX_UPLOADER, "limit": limit})).mappings().all()
    drops = []
    for row in rows:
        r = dict(row)
        r["stage"], r["stage_label"] = drop_stage(r)
        r.pop("esign_payload", None)
        drops.append(r)
    return DataResponse(data={
        "enabled": settings.inbox_enabled,
        "host_path": "./inbox",
        "poll_seconds": settings.inbox_poll_seconds,
        "uploader": INBOX_UPLOADER,
        "folder": folder,
        "drops": drops,
    })


def _storage_status() -> dict:
    client = get_minio_client()
    buckets = [b.name for b in client.list_buckets()]
    bucket = settings.minio_bucket
    count = size = 0
    recent = []
    if bucket in buckets:
        for obj in client.list_objects(bucket, recursive=True):
            count += 1
            size += obj.size or 0
            recent.append(obj)
            if count >= 5000:
                break
        recent.sort(key=lambda o: o.last_modified, reverse=True)
    return {
        "buckets": buckets,
        "object_count": count,
        "total_bytes": size,
        "count_capped": count >= 5000,
        "recent": [
            {"key": o.object_name, "size": o.size,
             "last_modified": o.last_modified.isoformat() if o.last_modified else None}
            for o in recent[:8]
        ],
    }


@router.get("/storage")
async def get_storage():
    base = {"endpoint": settings.minio_endpoint, "bucket": settings.minio_bucket,
            "console_url": settings.minio_console_url}
    try:
        status = await asyncio.wait_for(asyncio.to_thread(_storage_status), timeout=10)
    except Exception as e:
        return DataResponse(data={**base, "connected": False, "error": f"{type(e).__name__}: {e}"})
    return DataResponse(data={**base, "connected": True, "error": None, **status})
