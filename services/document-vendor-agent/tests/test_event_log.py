"""FR-06: the Control Panel's Kafka log is stored (survives restarts),
resumes where it left off, filters, and never stores or shows full
payloads (bank details)."""
import asyncio
import json

from app.services import event_monitor as em


def test_restart_resumes_right_after_the_last_stored_record():
    assert em.start_offset(last_stored=41, begin=0, end=90, backlog=50, first_connect=True) == 42
    # a partition never stored before shows recent history on first connect
    assert em.start_offset(None, begin=0, end=90, backlog=50, first_connect=True) == 40
    assert em.start_offset(None, begin=60, end=90, backlog=50, first_connect=True) == 60
    # retention may have trimmed Kafka below what we stored: never seek before the beginning
    assert em.start_offset(last_stored=5, begin=30, end=90, backlog=50, first_connect=False) == 30


def test_filters_build_the_right_query():
    sql, params = em.build_query(after=10, limit=50, topic="reminder.due", correlation_id="c-1",
                                 since_hours=24, q="approval")
    text = str(sql)
    for clause in ("id > :after", "topic = :topic", "correlation_id = :cid", "event_time >=", "ILIKE :q"):
        assert clause in text
    assert params["topic"] == "reminder.due" and params["q"] == "%approval%" and params["secs"] == 86400


def test_no_filters_means_everything_after_the_cursor():
    sql, params = em.build_query(0, 200, None, None, None, None)
    assert "topic =" not in str(sql) and params == {"after": 0, "limit": 200}


def test_bank_details_are_never_in_a_stored_summary():
    event = {"event_type": "document.classified", "payload": {
        "document_id": "d-1", "document_type": "invoice",
        "extracted_fields": {"bank_account_number": "000123456789"}, "bank_account_number": "000123456789"}}
    summary = em.summarize("document.classified", 0, 1, None, json.dumps(event).encode())
    assert "000123456789" not in json.dumps(summary)


def test_without_a_database_the_in_memory_log_is_used():
    mon = em.EventMonitor("kafka:9092")
    mon.add({"topic": "t", "message": "m", "fields": {}})
    events, latest = asyncio.run(mon.query(after=0))
    assert len(events) == 1 and latest == 1


def test_event_times_are_stored_as_real_timestamps():
    from datetime import timezone
    t = em._parse_time("2026-10-14T03:56:27.123456+00:00")
    assert t.year == 2026 and t.tzinfo is not None
    assert em._parse_time("2026-10-14T03:56:27").tzinfo == timezone.utc  # naive → UTC
    assert em._parse_time(None) is None and em._parse_time("not a time") is None
