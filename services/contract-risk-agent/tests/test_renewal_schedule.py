"""FR-02: renewal reminders count back from the notice deadline (end date
− notice period), and a contract created late gets one reminder, not every
missed milestone at once."""
from datetime import date, datetime, timedelta, timezone

from app.services.renewal_schedule import all_milestones, notice_deadline, reminder_schedule

END = date(2027, 6, 30)
MILESTONES = [60, 30, 15]


def _at(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)


def test_counts_from_the_notice_deadline_not_the_end_date():
    now = _at(date(2026, 10, 16))
    sched = reminder_schedule(END, 30, MILESTONES, now)
    deadline = date(2027, 5, 31)
    assert notice_deadline(END, 30) == deadline
    assert [(r.alert_level, r.fire_at.date()) for r in sched] == [
        (60, deadline - timedelta(days=60)), (30, deadline - timedelta(days=30)), (15, deadline - timedelta(days=15)),
    ]


def test_unknown_notice_period_counts_from_the_end_date():
    sched = reminder_schedule(END, None, MILESTONES, _at(date(2026, 10, 16)))
    assert sched[0].fire_at.date() == END - timedelta(days=60)
    assert notice_deadline(END, None) == END


def test_created_ten_days_before_the_deadline_gets_one_reminder():
    deadline = notice_deadline(END, 30)
    sched = reminder_schedule(END, 30, MILESTONES, _at(deadline - timedelta(days=10)))
    assert [r.alert_level for r in sched] == [15]          # the nearest missed one, once


def test_between_milestones_sends_the_missed_one_then_the_rest():
    deadline = notice_deadline(END, 30)
    sched = reminder_schedule(END, 30, MILESTONES, _at(deadline - timedelta(days=45)))
    assert [r.alert_level for r in sched] == [60, 30, 15]
    assert sched[0].fire_at < _at(deadline - timedelta(days=45)) < sched[1].fire_at


def test_milestones_from_the_rule_are_cleaned_up():
    # The business rule is a free list: order, duplicates and zeros don't matter.
    assert [r.alert_level for r in all_milestones(END, 30, [15, 60, 30, 30, 0])] == [60, 30, 15]
