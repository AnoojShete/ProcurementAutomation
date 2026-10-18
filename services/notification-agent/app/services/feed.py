"""The in-app notification feed: what the bell counts and what the
Notifications page shows first.

A person's feed is the notifications addressed to their own email, plus
those sent to a shared mailbox their role covers (config.yaml
`role_mailboxes`). "Important" means something to act on now: urgent
priority and actually delivered. Digested routine updates and digest
roll-ups stay out of it; they remain in the full log (GET /log).

Read state is per person (notification_reads), so one notification sent
to a role mailbox is read separately by each person who sees it.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import role_mailboxes
from app.models import NotificationLog, NotificationRead
from shared.auth.middleware import CurrentUser

URGENT = "urgent"
NOT_IN_FEED_STATUSES = ("queued_digest",)
# Urgent in email, but nothing to do in the app: the roll-up of routine
# updates, and a signed contract (the request already moved on its own).
NOT_IN_FEED_EVENTS = ("digest.flush", "contract.signed")


def mailboxes_for(user: CurrentUser) -> list[str]:
    return sorted({user.email.lower(), *(m.lower() for m in role_mailboxes().get(user.role, []))})


def _feed_filter(user: CurrentUser, important_only: bool):
    conditions = [func.lower(NotificationLog.recipient).in_(mailboxes_for(user))]
    if important_only:
        conditions += [
            NotificationLog.priority == URGENT,
            NotificationLog.status.not_in(NOT_IN_FEED_STATUSES),
            NotificationLog.event_type.not_in(NOT_IN_FEED_EVENTS),
        ]
    return and_(*conditions)


def _read_join(user: CurrentUser):
    return and_(NotificationRead.notification_id == NotificationLog.id, NotificationRead.user_id == user.id)


async def list_feed(db: AsyncSession, user: CurrentUser, *, important_only: bool = True,
                    unread_only: bool = False, limit: int = 50):
    """[(NotificationLog, read: bool)], newest first."""
    stmt = (
        select(NotificationLog, NotificationRead.notification_id.is_not(None))
        .outerjoin(NotificationRead, _read_join(user))
        .where(_feed_filter(user, important_only))
    )
    if unread_only:
        stmt = stmt.where(NotificationRead.notification_id.is_(None))
    stmt = stmt.order_by(NotificationLog.created_at.desc()).limit(limit)
    return [(row[0], bool(row[1])) for row in (await db.execute(stmt)).all()]


async def unread_count(db: AsyncSession, user: CurrentUser) -> int:
    stmt = (
        select(func.count())
        .select_from(NotificationLog)
        .outerjoin(NotificationRead, _read_join(user))
        .where(_feed_filter(user, important_only=True), NotificationRead.notification_id.is_(None))
    )
    return int((await db.execute(stmt)).scalar_one())


async def in_feed(db: AsyncSession, user: CurrentUser, notification_id: str) -> bool:
    stmt = select(NotificationLog.id).where(NotificationLog.id == notification_id, _feed_filter(user, False))
    return (await db.execute(stmt)).first() is not None


async def mark_read(db: AsyncSession, user: CurrentUser, notification_ids: Optional[list[str]] = None) -> int:
    """Mark the given notifications (or, with None, every important one) as
    read for this person. Ids outside their feed are ignored. Returns how
    many became read."""
    stmt = (
        select(NotificationLog.id)
        .outerjoin(NotificationRead, _read_join(user))
        .where(_feed_filter(user, important_only=notification_ids is None),
               NotificationRead.notification_id.is_(None))
    )
    if notification_ids is not None:
        stmt = stmt.where(NotificationLog.id.in_(notification_ids))
    ids = list((await db.execute(stmt)).scalars().all())
    if ids:
        now = datetime.now(timezone.utc)
        await db.execute(
            insert(NotificationRead)
            .values([{"user_id": user.id, "notification_id": i, "read_at": now} for i in ids])
            .on_conflict_do_nothing()
        )
        await db.commit()
    return len(ids)
