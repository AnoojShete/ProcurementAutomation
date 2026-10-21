"""The assistant decides what a message means before retrieving anything.
Regression tests for the four failures seen in use (21 Oct 2026):

  "Are there any SaaS license anomalies?"  -> answered with "Current value: 0.39"
  "hi"                                     -> a generic procurement line
  "like what"                              -> searched with the previous message, random rule
  "sure procurement is easy like vendors"  -> "no record of 'sure procurement'"
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import intent, llm_client, topics
from shared.auth.middleware import CurrentUser

FINANCE = CurrentUser(id="u", email="finance@demo.example.com", role="finance")
REQUESTER = CurrentUser(id="u", email="requester@demo.example.com", role="requester")
VENDORS = ["Acme IT Supplies Inc", "Zenith Test Systems 30696F Pvt Ltd", "Zenith Test Systems CF1349 Pvt Ltd",
           "Dell Technologies India Pvt Ltd"]


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _msg(role, content):
    return SimpleNamespace(role=role, content=content)


# ── classification ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,kind", [
    ("hi", "greeting"), ("Hello!", "greeting"), ("good morning", "greeting"), ("hey there", "greeting"),
    ("thanks", "greeting"), ("thank you so much", "greeting"), ("bye", "greeting"),
    ("like what", "examples"), ("like what?", "examples"), ("for example", "examples"), ("such as?", "examples"),
    ("give me some examples", "examples"), ("what else", "examples"),
    ("what can you do?", "capabilities"), ("how can you help", "capabilities"), ("help", "capabilities"),
    ("sure procurement is easy like vendors", "smalltalk"), ("ok cool", "smalltalk"), ("i think contracts are boring", "smalltalk"),
    ("vendors", "topic_only"), ("licences?", "question"), ("my requests", "topic_only"),
    ("Are there any SaaS license anomalies?", "licence_anomalies"), ("which licences are under-used", "licence_anomalies"),
    ("any unused seats we could reclaim?", "licence_anomalies"),
    ("What is Acme IT Supplies Inc's risk rating?", "question"), ("How much notice to end a services contract?", "question"),
    ("show me vendors with high risk", "question"), ("Who approves a purchase above 5,000 rupees?", "question"),
])
def test_classify(text, kind):
    assert intent.classify(text).kind == kind


def test_examples_follow_the_previous_topic():
    assert intent.classify("like what", previous_user="tell me about contracts").topic == "contracts"
    assert intent.classify("like what", previous_user="hi").topic is None


def test_a_remark_is_not_a_vendor_lookup():
    i = intent.classify("sure procurement is easy like vendors")
    assert i.kind == "smalltalk" and i.topic == "vendors"


# ── replies ─────────────────────────────────────────────────────────────────

def _reply(text, user=FINANCE, previous=None):
    return intent.reply(intent.classify(text, previous), text, role=user.role, first_name="Fiona", vendor=VENDORS[0])


def test_hi_gets_a_greeting_with_examples():
    r = _reply("hi")
    assert r.startswith("Hi Fiona!") and "?" in r and "- " in r
    assert "I can help with procurement-related questions" not in r


def test_like_what_lists_examples_not_a_rule():
    r = _reply("like what", previous="hi")
    assert "few things you could ask" in r and r.count("\n- ") >= 3
    assert "approval.email_action" not in r and "Business rule" not in r


def test_remark_about_vendors_offers_vendor_questions():
    r = _reply("sure procurement is easy like vendors")
    assert "no record" not in r.lower() and "sure procurement" not in r.lower()
    assert "risk rating of Acme IT Supplies Inc" in r


def test_requester_examples_skip_staff_only_topics():
    for text in ("hi", "like what", "what can you do?"):
        r = _reply(text, REQUESTER)
        assert "licence" not in r.lower() and "budget" not in r.lower(), r
        assert "How many purchase requests" not in r and "rated High risk" not in r, r


def test_like_what_does_not_repeat_the_greeting_examples():
    greeting = _reply("hi", REQUESTER)
    more = intent.reply(intent.classify("like what", "hi"), "like what", role="requester", first_name=None,
                        vendor=VENDORS[0], shown=greeting)
    shown = [l for l in greeting.splitlines() if l.startswith("- ")]
    assert not any(l in more for l in shown), more
    assert more.count("\n- ") >= 2


def test_topic_only_asks_a_clarifying_question():
    r = _reply("vendors")
    assert r.startswith("What would you like to know about vendors?")


def test_thanks_and_bye():
    assert _reply("thanks").startswith("You're welcome")
    assert _reply("bye").startswith("Bye")


def test_ambiguous_vendor_name_gets_a_question():
    q = intent.clarify_vendor("What is Zenith's risk rating?", VENDORS)
    assert q.startswith("Which vendor do you mean: Zenith Test Systems 30696F") and "CF1349" in q
    assert intent.clarify_vendor("What is Acme IT Supplies Inc's risk rating?", VENDORS) is None
    assert intent.clarify_vendor("What is Dell's risk rating?", VENDORS) is None          # one match: fine
    assert intent.clarify_vendor("What does the SaaS contract say?", VENDORS) is None


# ── licence anomalies from live data ────────────────────────────────────────

LICENCES = [SimpleNamespace(id="l1", app_name="Slack Enterprise", total_seats=63, assigned_seats=44, cost_per_seat=650),
            SimpleNamespace(id="l2", app_name="Notion Team", total_seats=200, assigned_seats=180, cost_per_seat=400),
            SimpleNamespace(id="l3", app_name="Docker Pro", total_seats=60, assigned_seats=55, cost_per_seat=900)]
RULES = {"license.anomaly_anomalous_threshold": 0.39, "license.anomaly_watch_threshold": 0.34,
         "license.grace_period_days": 7}


def _score(v, factor="utilisation_90d", active=35, seats=63):
    return {"anomaly_score": v, "active_seats_30d": active, "total_seats": seats,
            "top_factors": [{"feature": factor, "direction": "increasing_risk", "contribution": 0.6}]}


def test_no_anomaly_explains_criteria_closest_licences_and_next_steps():
    r = topics.licence_anomaly_answer(LICENCES, {"l1": _score(0.24), "l2": _score(0.18, active=150, seats=200)}, RULES,
                                      {"potential_annual_savings": 0})
    assert r.startswith("No: none of the 3 licences is anomalous right now (no score at or above 0.39)")
    assert "Slack Enterprise: score 0.24 (normal), 35 of 63 seats active in the last 30 days; main signal: low use over 90 days" in r
    assert "Isolation Forest" in r and "0.34 or more is on watch" in r
    assert "What to do" in r and "Slack Enterprise (19 unassigned)" in r
    assert "license.anomaly" not in r and "Current value" not in r       # no raw keys


def test_anomalous_licence_is_listed_with_actions():
    r = topics.licence_anomaly_answer(LICENCES, {"l1": _score(0.52, "trend_slope", 12), "l3": _score(0.36, seats=60)},
                                      RULES, {"potential_annual_savings": 33800})
    assert r.startswith("Yes: 1 of 3 licences show a usage anomaly (score at or above 0.39)")
    assert "Slack Enterprise: score 0.52 (anomalous), 12 of 63 seats active" in r and "usage falling" in r
    assert "reclaim request" in r and "7-day grace period" in r and "INR 33,800 a year" in r


def test_threshold_comes_from_the_rule_not_a_constant():
    r = topics.licence_anomaly_answer(LICENCES, {"l1": _score(0.30)}, {**RULES, "license.anomaly_anomalous_threshold": 0.25}, None)
    assert r.startswith("Yes: 1 of 3") and "at or above 0.25" in r


def test_requester_is_told_licences_are_staff_only():
    r = run(topics.answer_licence_anomalies(MagicMock(), REQUESTER))
    assert "approvers, finance and admins" in r


# ── the reply path: conversational intents never reach retrieval ────────────

def _ask(history, user=FINANCE):
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[(v,) for v in VENDORS]),
                                                  scalar=MagicMock(return_value="Fiona Finance")))
    retrieve = AsyncMock(return_value=[])
    with patch.object(llm_client.rag_service, "retrieve", retrieve), \
            patch.object(llm_client.httpx, "AsyncClient") as client:
        out = run(llm_client.query_llm_with_tools([_msg(r, c) for r, c in history], user, db))
    return out, retrieve, client


@pytest.mark.parametrize("history", [
    [("user", "hi")],
    [("user", "hi"), ("assistant", "Hi!"), ("user", "like what")],
    [("user", "sure procurement is easy like vendors")],
    [("user", "vendors")],
])
def test_conversational_messages_skip_retrieval_and_the_model(history):
    out, retrieve, client = _ask(history)
    retrieve.assert_not_awaited()
    client.assert_not_called()
    assert out and "no record" not in out.lower()


def test_licence_anomaly_question_uses_live_data():
    with patch.object(topics, "answer_licence_anomalies", AsyncMock(return_value="live answer")) as live:
        out, retrieve, _ = _ask([("user", "Are there any SaaS license anomalies?")])
    assert out == "live answer" and live.await_count == 1
    retrieve.assert_not_awaited()


def test_ambiguous_vendor_question_asks_before_retrieving():
    out, retrieve, _ = _ask([("user", "What is Zenith's risk rating?")])
    assert out.startswith("Which vendor do you mean") and not retrieve.await_count


def test_follow_up_after_a_greeting_is_not_merged_into_the_search():
    assert llm_client.search_query([_msg("user", "hi"), _msg("assistant", "Hi!"), _msg("user", "warranty of laptops?")]) \
        == "warranty of laptops?"


def test_rule_passages_are_plain_words_with_the_key_only_as_reference():
    from app.services import indexer
    import inspect
    src = inspect.getsource(indexer.load_sources)
    assert "It is currently set to" in src and "Reference: {r.rule_key}" in src
    assert "Current value:" not in src
