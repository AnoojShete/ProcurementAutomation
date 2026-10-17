"""When a contract's renewal reminders fire.

Reminders count back from the notice deadline — the last day to give
notice (end date − notice period), which is what someone actually has to
act on — not from the end date. Pure (no I/O), so the Temporal workflow,
the API and the tests all use the same calculation.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional


@dataclass(frozen=True)
class Reminder:
    alert_level: int        # days before the notice deadline
    fire_at: datetime       # midnight UTC on that day


def notice_deadline(end_date: date, notice_period_days: Optional[int]) -> date:
    """Last day to give notice; the end date when the notice period is unknown."""
    return end_date - timedelta(days=notice_period_days or 0)


def reminder_schedule(
    end_date: date, notice_period_days: Optional[int], milestones: Iterable[int], now: datetime,
) -> list[Reminder]:
    """Reminders still to send, earliest first. Milestones already past are
    dropped except the most recent one, which is sent straight away — so a
    contract created 10 days before its deadline gets one reminder, not
    three at once."""
    all_reminders = all_milestones(end_date, notice_period_days, milestones)
    past = [r for r in all_reminders if r.fire_at <= now]
    future = [r for r in all_reminders if r.fire_at > now]
    return past[-1:] + future


def all_milestones(end_date: date, notice_period_days: Optional[int], milestones: Iterable[int]) -> list[Reminder]:
    """Every milestone, for display (whether or not it has passed)."""
    deadline = notice_deadline(end_date, notice_period_days)
    return sorted(
        (Reminder(m, datetime.combine(deadline - timedelta(days=m), time.min, tzinfo=timezone.utc))
         for m in {int(m) for m in milestones if int(m) > 0}),
        key=lambda r: r.fire_at,
    )
