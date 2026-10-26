"""Daily batch-approval digest email (DIGEST-1, Prompt 10 Section 1.5).

Once a day, from approval.bulk_digest_time_ist (IST), each approver gets one
email listing the pending requests they may approve in bulk, with one
batch-approval link (/email-action/batch/<token>). "May approve in bulk" is
bulk_eligibility, the same check as the inbox and the batch page, so the
link never offers more than the portal would.

  - approval.bulk_digest_enabled   off -> no digest
  - approval.bulk_email_enabled    off -> no digest (and the batch page refuses)
  - approval.bulk_digest_min_items fewer eligible requests -> no email for that approver
  - approval.bulk_approve_max_items  a digest lists at most this many (oldest first)

A new digest revokes the approver's earlier unused batch links. The day's
run is recorded in Redis (one replica runs it), and an approver who already
has a batch link minted today (IST) is skipped, so a restart never sends
the digest twice.
"""
import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from app.models import EmailBatchToken, PurchaseRequest
from app.services import email_action_token_service as tokens
from app.services.approval_authority import load_assignments, load_delegations
from app.services.bulk_service import approver_role_for, bulk_eligibility
from shared.eventing import staged
from shared.rules_engine import get_rule

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
CHECK_SECONDS = 60
DEFAULT_TIME = time(9, 0)


def digest_time() -> time:
    """approval.bulk_digest_time_ist as a time; a malformed value means 09:00."""
    raw = str(get_rule("approval.bulk_digest_time_ist", fallback="09:00")).strip()
    try:
        hours, minutes = raw.split(":")
        return time(int(hours), int(minutes))
    except ValueError:
        logger.warning(f"approval.bulk_digest_time_ist={raw!r} is not HH:MM; using 09:00")
        return DEFAULT_TIME


def digest_enabled() -> bool:
    return bool(get_rule("approval.bulk_digest_enabled", fallback=True)) and tokens.bulk_email_enabled()


def is_due(now: datetime, at: time) -> bool:
    """True once the IST clock has passed today's digest time."""
    return now.astimezone(IST).time() >= at


def ist_day_start(now: datetime) -> datetime:
    local = now.astimezone(IST)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


async def _candidates(db, level: str) -> set[str]:
    """Everyone who might decide at `level`: assigned approvers and their
    live delegates. bulk_eligibility then checks each one properly."""
    now = datetime.now(timezone.utc)
    people = {a.user_email.strip().lower() for a in await load_assignments(db, level)}
    for d in await load_delegations(db, level):
        if d.valid_from <= now <= d.valid_until:
            people.add(d.delegate_email.strip().lower())
    return people


async def eligible_by_approver(db, now: datetime) -> dict[str, list[PurchaseRequest]]:
    """{approver email: [requests they may bulk-approve]}, oldest first."""
    pending = (await db.execute(
        select(PurchaseRequest)
        .where(PurchaseRequest.status == "pending_approval")
        .order_by(PurchaseRequest.created_at.asc().nulls_last(), PurchaseRequest.id)
    )).scalars().all()

    by_approver: dict[str, list[PurchaseRequest]] = {}
    people_at: dict[str, set[str]] = {}
    roles: dict[str, str] = {}
    for req in pending:
        chain = req.approval_chain or []
        idx = req.current_approver_index or 0
        if idx >= len(chain):
            continue
        level = chain[idx]
        if level not in people_at:
            people_at[level] = await _candidates(db, level)
        for email in sorted(people_at[level]):
            if email not in roles:
                roles[email] = await approver_role_for(db, email)
            eligible, _, _ = await bulk_eligibility(db, req, email, roles[email], now)
            if eligible:
                by_approver.setdefault(email, []).append(req)
    return by_approver


async def _already_sent_today(db, approver: str, now: datetime) -> bool:
    row = (await db.execute(
        select(EmailBatchToken.id).where(
            EmailBatchToken.approver_id == approver,
            EmailBatchToken.created_at >= ist_day_start(now),
        ).limit(1)
    )).first()
    return row is not None


def _context(approver: str, reqs: list[PurchaseRequest], batch_url: str, expires_at: datetime) -> dict:
    total = sum(float(r.amount or 0) for r in reqs)
    return {
        "approver": approver,
        "count": len(reqs),
        "total_amount": f"{total:,.2f}",
        "currency": "INR",
        "batch_url": batch_url,
        "expires_at": expires_at.astimezone(IST).strftime("%d %b %Y, %H:%M IST"),
        "items": [
            {
                "request_id": r.id,
                "short_id": r.id[:8].upper(),
                "requested_by": r.requested_by,
                "department": r.department,
                "request_type": r.request_type,
                "amount": f"{float(r.amount or 0):,.2f}",
            }
            for r in reqs
        ],
    }


async def send_digests(session_factory, producer, now: Optional[datetime] = None) -> int:
    """One digest run. Returns how many digest emails were queued."""
    now = now or datetime.now(timezone.utc)
    if not digest_enabled():
        return 0
    min_items = int(get_rule("approval.bulk_digest_min_items", fallback=2))
    max_items = int(get_rule("approval.bulk_approve_max_items", fallback=25))

    async with session_factory() as db:
        groups = await eligible_by_approver(db, now)

    sent = 0
    for approver, reqs in sorted(groups.items()):
        if len(reqs) < min_items:
            continue
        reqs = reqs[:max_items]
        async with session_factory() as db:
            if await _already_sent_today(db, approver, now):
                continue
            await tokens.revoke_batch_tokens(db, approver, "superseded_by_new_digest")
            _, expires_at, batch_url = await tokens.mint_batch_action_token(
                db, approver_id=approver, request_ids=[r.id for r in reqs], commit=False,
            )
            # The email commits with the batch token (outbox), or neither does.
            await staged(producer, db).publish_notification(
                recipient=approver,
                channel="email",
                template_name="bulk_approval_digest",
                template_context=_context(approver, reqs, batch_url, expires_at),
                priority="urgent",
                related_entity_id=None,
            )
            await db.commit()
        sent += 1
        logger.info(f"Batch-approval digest queued for {approver}: {len(reqs)} request(s)")
    return sent


async def run_bulk_digest(session_factory, producer, redis_client=None):
    """Background loop: checks every minute; runs once per IST day after the
    digest time. The Redis key lets only one replica run each day."""
    await asyncio.sleep(30)  # let migrations and the rules cache settle
    while True:
        key = None
        try:
            now = datetime.now(timezone.utc)
            if digest_enabled() and is_due(now, digest_time()):
                day = now.astimezone(IST).date().isoformat()
                claimed = True
                if redis_client is not None:
                    key = f"bulk_digest:ran:{day}"
                    claimed = bool(await redis_client.set(key, "1", nx=True, ex=2 * 86400))
                if claimed:
                    count = await send_digests(session_factory, producer, now)
                    logger.info(f"Batch-approval digest for {day}: {count} email(s)")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Batch-approval digest run failed: {e}", exc_info=True)
            if key and redis_client is not None:
                # Try again next minute; approvers already sent today are skipped.
                await redis_client.delete(key)
        await asyncio.sleep(CHECK_SECONDS)
