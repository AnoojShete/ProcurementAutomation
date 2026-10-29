"""FR-09: every business rule this service reads changes behaviour when an
admin changes it. Each test sets the rule to two values through the shared
rules-engine cache (the same path a live rule takes) and checks the effect.
docs/business-rules.md lists these tests per rule."""
import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

import shared.rules_engine as rules_engine  # noqa: E402


@pytest.fixture
def rule(monkeypatch):
    rules_engine.clear_cache()
    monkeypatch.setattr(rules_engine, "fetch_all_rules", lambda: {})
    yield rules_engine.update_rule_cache
    rules_engine.clear_cache()


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_risk_contract_renewal_milestones_days(rule):
    from app.api.contracts import _renewal_schedule
    contract = SimpleNamespace(contract_end_date=date(2028, 1, 1), notice_period_days=30)
    rule("risk.contract_renewal_milestones_days", [60, 30, 15])
    assert [r["alert_level"] for r in _renewal_schedule(contract)["renewal_reminders"]] == [60, 30, 15]
    rule("risk.contract_renewal_milestones_days", [90])
    assert [r["alert_level"] for r in _renewal_schedule(contract)["renewal_reminders"]] == [90]


def _on_time_rate():
    from app.services import risk_signals
    now = datetime(2026, 10, 16, tzinfo=timezone.utc)
    signed = now - timedelta(days=40)
    db = AsyncMock()
    first = MagicMock(scalar=MagicMock(return_value=now - timedelta(days=400)))
    rows = MagicMock(all=MagicMock(return_value=[SimpleNamespace(ordered_at=signed, received_at=signed + timedelta(days=10))]))
    db.execute.side_effect = [first, rows]
    return run(risk_signals.platform_signals(db, "v-1", now=now))["on_time_delivery_rate"]


def test_vendor_expected_delivery_days(rule):
    rule("vendor.expected_delivery_days", 14)     # delivered in 10 days: on time
    assert _on_time_rate() == 1.0
    rule("vendor.expected_delivery_days", 7)
    assert _on_time_rate() == 0.0


def _auto_send():
    from app.services import contract_service
    db = AsyncMock()
    db.execute.return_value = MagicMock(first=MagicMock(return_value=("tried",)))
    contract = SimpleNamespace(id="c-1", status="draft")
    with patch.object(contract_service.settings, "esign_auto_send", True), \
            patch.object(contract_service, "is_drop_folder_contract", AsyncMock(return_value=False)):
        return run(contract_service.auto_send_for_signature(db, None, contract))


def test_contract_auto_send_scope(rule):
    rule("contract.auto_send_scope", "drop_folder")
    assert _auto_send() == "not_from_drop_folder"
    rule("contract.auto_send_scope", "all")
    assert _auto_send() == "already_tried"   # got past the scope check


def _signature_reminders_sent():
    from app.services import reminder_sweep
    now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
    session = AsyncMock()
    session.execute.return_value = MagicMock(all=MagicMock(return_value=[
        SimpleNamespace(id="c-1", request_id="r-1", since=now - timedelta(days=4))]))
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    with patch.object(reminder_sweep, "remind_once", AsyncMock(return_value=True)):
        return run(reminder_sweep.sweep_signature_reminders(factory, object(), now=now))


def test_contract_signature_reminder_days(rule):
    rule("contract.signature_reminder_days", 3)    # waiting 4 days
    assert _signature_reminders_sent() == 1
    rule("contract.signature_reminder_days", 7)
    assert _signature_reminders_sent() == 0


def _clause_route(found):
    """Routes with the Legal-BERT path stubbed to return `found`."""
    from app.services import clause_router
    with patch.object(clause_router.clause_model, "available", return_value=True), \
            patch.object(clause_router, "_model_clauses", return_value=found), \
            patch.object(clause_router, "_log_to_db", lambda *a: None):
        return run(clause_router.route_clause_extraction(MagicMock(), "c-1", "text"))


ONE_OF_THREE = {"renewal_type": "auto", "notice_period_days": None, "contract_end_date": None}
ALL_THREE = {"renewal_type": "auto", "notice_period_days": 30, "contract_end_date": "2027-01-01"}


def test_contract_clause_extraction_fallback_threshold(rule):
    rule("contract.clause_extraction_fallback_threshold", 0.4)   # 1 of 3 clauses = 0.33
    r = _clause_route(ONE_OF_THREE)
    assert r.route_name == "regex_fallback" and r.fallback_reason == "low_confidence"
    rule("contract.clause_extraction_fallback_threshold", 0.3)
    assert _clause_route(ONE_OF_THREE).route_name == "legal_bert_primary"


def test_dev_force_model_fallback(rule, monkeypatch):
    """FR-08: forcing the clause router's primary to fail shows the
    fallback (reason "forced") — in development only."""
    rule("contract.clause_extraction_fallback_threshold", 0.4)
    rule("dev.force_model_fallback", [])
    assert _clause_route(ALL_THREE).route_name == "legal_bert_primary"
    rule("dev.force_model_fallback", ["clauses"])
    r = _clause_route(ALL_THREE)
    assert r.route_name == "regex_fallback" and r.fallback_reason == "forced"
    monkeypatch.setenv("APP_ENV", "production")
    assert _clause_route(ALL_THREE).route_name == "legal_bert_primary"


def test_risk_sanctions_match_threshold_pct(rule):
    """FR-14: the threshold decides what counts as a potential match
    ("Sea Breeze Shipping Lines" vs the listed "Sea Breeze Shipping
    Limited" scores about 86)."""
    from app.services import sanctions
    csv_text = ("id,schema,name,aliases,birth_date,countries,addresses,identifiers,sanctions,phones,emails,dataset,"
                "first_seen,last_seen,last_change\nuk-5,LegalEntity,Sea Breeze Shipping Limited,,,ir,,,,,,UK HMT,,,\n")
    index = sanctions.build_index(csv_text, "v")
    index["_flat"] = [sanctions.normalise(n) for n in index["entries"][0]["names"]]
    index["_owners"] = [(0, n) for n in index["entries"][0]["names"]]
    rule("risk.sanctions_match_threshold_pct", 90)
    assert sanctions.screen_name("Sea Breeze Shipping Lines", index) == []
    rule("risk.sanctions_match_threshold_pct", 85)
    assert sanctions.screen_name("Sea Breeze Shipping Lines", index)[0]["entity_id"] == "uk-5"


# ── Phase 2: contract obligations ───────────────────────────────────────────

def _warranty_due(today):
    from app.services.obligation_service import reminder_days, reminder_due
    ob = SimpleNamespace(due_date=today + timedelta(days=20), recurrence="none")
    return reminder_due(ob, today, reminder_days())


def test_contract_obligation_reminder_days(rule):
    today = date(2026, 10, 20)
    rule("contract.obligation_reminder_days", [30, 7])     # 20 days left: inside the 30-day window
    assert _warranty_due(today)[0] == "2026-11-09:30"
    rule("contract.obligation_reminder_days", [14, 7])     # 20 days left: nothing yet
    assert _warranty_due(today) is None


def _min_score_used():
    from app.services import obligation_service as svc
    seen = {}

    def fake_extract(text, use_model, min_score):
        seen["min_score"] = min_score
        return []
    db = AsyncMock()
    db.execute.return_value = MagicMock(all=MagicMock(return_value=[]))
    contract = SimpleNamespace(id="c-1", contract_text="x", obligations_extracted_at=None)
    with patch.object(svc.ox, "extract_obligations", fake_extract), \
            patch.object(svc, "write_audit_log", AsyncMock()):
        run(svc.extract_for_contract(db, contract))
    return seen["min_score"]


def test_contract_obligation_model_min_confidence(rule):
    rule("contract.obligation_model_min_confidence", 0.5)
    assert _min_score_used() == 0.5
    rule("contract.obligation_model_min_confidence", 3.0)
    assert _min_score_used() == 3.0


def _credit_status():
    from app.services import obligation_service as svc
    ob = SimpleNamespace(id="o-1", contract_id="c-1", type="sla_uptime", status="open", due_date=None,
                         value={"uptime_pct": 99.9, "credit_pct_per_step": 10, "step_pct": 0.1, "credit_cap_pct": 50})
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))))
    db.get = AsyncMock(return_value=SimpleNamespace(purchase_request_id="pr-1"))
    with patch.object(svc, "monthly_fee", AsyncMock(return_value=(10000.0, "INR"))):
        credit = run(svc.record_downtime(db, ob, "2026-10", 99.5, "it@example.com"))
    return credit.status


def test_contract_sla_credit_auto_expect(rule):
    rule("contract.sla_credit_auto_expect", True)
    assert _credit_status() == "expected"
    rule("contract.sla_credit_auto_expect", False)
    assert _credit_status() == "proposed"


# ── Deterministic risk scorecard (merged from updated_risk) ─────────────────

def _clearance(spend):
    from app.api import vendors as api
    vendor = SimpleNamespace(id="v1", vendor_tier="petty", status="active")
    score = SimpleNamespace(id="s1", rating_status="provisional", is_provisional=True, final_band="Low", band="Low", points_band="Low",
                            blocked_by=[], override_rule_ids=[], provisional_reasons=["incidents"], score=None)
    db = AsyncMock()
    db.get = AsyncMock(return_value=vendor)
    db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))))
    with patch.object(api.risk_service, "latest_risk_score", AsyncMock(return_value=score)):
        return run(api.get_vendor_clearance("v1", purpose="purchase", spend_amount=spend, contract_id=None,
                                            currency="INR", db=db)).data


def test_risk_petty_threshold(rule):
    rule("risk.petty_threshold", 50000)
    out = _clearance(40000)
    assert out["cleared"] is True and "cleared_under_petty_exception" in out["reasons"]
    rule("risk.petty_threshold", 30000)
    out = _clearance(40000)
    assert out["cleared"] is False and "rating_provisional" in out["reasons"]


def _alert(rule_value, rule):
    from app.services import risk_service
    rule("risk.alert_recipients", rule_value)
    producer = MagicMock(publish_notification=AsyncMock())
    sent = run(risk_service.send_high_risk_alert(producer, SimpleNamespace(name="Acme"), "v1", "High", 60, "High", []))
    return sent, producer.publish_notification


def test_risk_alert_recipients(rule):
    sent, publish = _alert("risk-team@acme.test", rule)
    assert sent and publish.await_args.kwargs["recipient"] == "risk-team@acme.test"
    sent, publish = _alert("", rule)
    assert not sent and publish.await_count == 0


def _incident_history(now, days_on_file):
    from app.services.collectors import performance_collectors as pc
    captured = {}

    async def raw(**kw):
        captured["body"] = kw["body"]
        return SimpleNamespace(id="r1")
    vendor = SimpleNamespace(id="v1", created_at=now - timedelta(days=days_on_file))
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=0), all=MagicMock(return_value=[])))
    with patch.object(pc, "record_raw_response", raw), patch.object(pc, "record_observation", AsyncMock(return_value=SimpleNamespace(id="o1"))):
        run(pc.collect_incidents(db, vendor, now))
    return captured["body"]["history_available"]


def test_risk_min_relationship_days(rule):
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    rule("risk.min_relationship_days", 90)     # 100 days on file, no delivered order yet
    assert _incident_history(now, 100) is True
    rule("risk.min_relationship_days", 120)
    assert _incident_history(now, 100) is False


def _retention(rule_value, rule):
    from app.services.collectors import base
    rule("risk.raw_retention_months", rule_value)
    db = MagicMock(add=MagicMock(), flush=AsyncMock())
    row = run(base.record_raw_response(db=db, vendor_id="v1", signal_key="sanctions", provider="x", request_method="GET",
                                       body={"ok": True}, fetched_at=datetime(2026, 1, 15, tzinfo=timezone.utc)))
    return row.retention_until


def test_risk_raw_retention_months(rule):
    # months are approximated as 30.5 days (collectors/base.compute_retention_date)
    assert _retention(24, rule) == date(2028, 1, 17)
    assert _retention(6, rule) == date(2026, 7, 17)


# ── Signing mandates and auto-signing (Prompt 10) ────────────────────────

def _auto_signed(rule, channel="bulk", spend=10000):
    """Runs the approval.decided handler for a final finance approval of a
    request whose contract is unsigned, with an active mandate capped at
    ₹1,00,000; True when the contract was signed under the mandate."""
    from app.kafka import consumer
    from app.services import contract_service
    contract = SimpleNamespace(id="c-1", status="sent", vendor_id="v-1")
    mandate = SimpleNamespace(id="m-1", max_amount_per_contract=100000, mandate_text_sha256="abc")
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        MagicMock(scalar_one_or_none=MagicMock(return_value=["dept_manager", "finance"])),
        MagicMock(scalar_one_or_none=MagicMock(return_value=contract)),
        MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=mandate)))),
    ])
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = db
    sign = AsyncMock(return_value=(contract, {}))
    payload = {"decision": "approved", "request_id": "r-1", "decision_level": "level_2_finance",
               "decision_channel": channel, "decided_by": "finance@company.com",
               "bulk_batch_id": "b-1" if channel == "bulk" else None}
    app = SimpleNamespace(state=SimpleNamespace(kafka_producer=None))
    with patch.object(consumer, "async_session_factory", factory), \
         patch.object(consumer, "auto_send_for_signature", AsyncMock(return_value="skipped")), \
         patch.object(contract_service, "_contract_amount", AsyncMock(return_value=spend)), \
         patch.object(contract_service, "signing_risk", AsyncMock(return_value={"signing_blocked": False})), \
         patch.object(contract_service, "sign_contract_digitally", sign):
        run(consumer._handle_approval_decided(app, payload))
    return sign.await_count == 1


def test_contract_auto_sign_enabled(rule):
    rule("contract.auto_sign_enabled", True)
    assert _auto_signed(rule) is True
    rule("contract.auto_sign_enabled", False)
    assert _auto_signed(rule) is False


def test_contract_auto_sign_allow_email_channel(rule):
    rule("contract.auto_sign_enabled", True)
    rule("contract.auto_sign_allow_email_channel", True)
    assert _auto_signed(rule, channel="email") is True
    rule("contract.auto_sign_allow_email_channel", False)
    assert _auto_signed(rule, channel="email") is False


def test_contract_auto_sign_max_amount(rule):
    rule("contract.auto_sign_enabled", True)
    rule("contract.auto_sign_max_amount", 50000)
    assert _auto_signed(rule, spend=30000) is True
    rule("contract.auto_sign_max_amount", 25000)
    assert _auto_signed(rule, spend=30000) is False


def _create_mandate(role="finance", amount=10000, days=30):
    """POST /mandates up to the password check (auth-service's
    /auth/verify-password answers 400 wrong_password, and so does create);
    returns the status code and message of the refusal."""
    from fastapi import HTTPException
    from app.api import mandates
    body = SimpleNamespace(password="wrong", max_amount_per_contract=amount, validity_days=days)
    user = SimpleNamespace(role=role, email=f"{role}@company.com")
    client = MagicMock()
    client.__aenter__.return_value.post = AsyncMock(return_value=SimpleNamespace(status_code=400, text=""))
    with patch.object(mandates.httpx, "AsyncClient", MagicMock(return_value=client)):
        try:
            run(mandates.create_mandate(body=body, request=MagicMock(), db=AsyncMock(), user=user))
        except HTTPException as e:
            return e.status_code, str(e.detail)
    return 201, ""


def test_contract_auto_sign_roles(rule):
    rule("contract.auto_sign_roles", ["finance"])
    assert "password" in _create_mandate(role="finance")[1]   # allowed; stopped at the password
    rule("contract.auto_sign_roles", ["admin"])
    assert _create_mandate(role="finance")[0] == 403


def test_contract_mandate_max_days(rule):
    rule("contract.mandate_max_days", 90)
    assert "password" in _create_mandate(days=60)[1]
    rule("contract.mandate_max_days", 30)
    status, message = _create_mandate(days=60)
    assert status == 400 and "Validity" in message


def _collect_breach_with(rule_values, rule):
    from app.services.collectors import cyber_collectors as cc
    for key, value in rule_values.items():
        rule(key, value)
    matcher = AsyncMock(return_value={"catalogue_loaded": False})
    vendor = SimpleNamespace(id="v1", name="Acme Systems", website="acme.example", contact_email=None)
    with patch.object(cc, "match_vendor_breaches", matcher), \
            patch.object(cc, "record_raw_response", AsyncMock(return_value=SimpleNamespace(id="raw"))), \
            patch.object(cc, "record_observation", AsyncMock()):
        run(cc.collect_breach(AsyncMock(), vendor, datetime(2026, 10, 29, tzinfo=timezone.utc)))
    return matcher.call_args.kwargs


def test_risk_breach_catalogue_max_age_days(rule):
    assert _collect_breach_with({"risk.breach_catalogue_max_age_days": 7}, rule)["max_age_days"] == 7
    assert _collect_breach_with({"risk.breach_catalogue_max_age_days": 90}, rule)["max_age_days"] == 90


def test_risk_breach_name_match_pct(rule):
    assert _collect_breach_with({"risk.breach_name_match_pct": 95}, rule)["name_match_pct"] == 95
    assert _collect_breach_with({"risk.breach_name_match_pct": 70}, rule)["name_match_pct"] == 70


def test_risk_required_certifications_by_tier(rule):
    from app.services.collectors import cyber_collectors as cc

    def cert_required(cert_map):
        rule("risk.required_certifications_by_tier", cert_map)
        db = AsyncMock()
        no_rows = MagicMock()
        no_rows.first.return_value = None
        no_rows.scalars.return_value.first.return_value = None
        db.execute.return_value = no_rows
        observed = AsyncMock()
        with patch.object(cc, "record_raw_response", AsyncMock(return_value=SimpleNamespace(id="raw"))), \
                patch.object(cc, "record_observation", observed):
            run(cc.collect_certification(db, SimpleNamespace(id="v1", name="Acme"),
                                         datetime(2026, 10, 29, tzinfo=timezone.utc), effective_tier="moderate"))
        return observed.call_args.kwargs["fields"]["cert.required"]

    assert cert_required({"moderate": []}) is False
    assert cert_required({"moderate": ["ISO 27001"]}) is True


def _statement(**overrides):
    meta = {"total_equity": 100, "profit_after_tax": 10, "current_assets": 130,
            "current_liabilities": 100, "total_borrowings": 90, "audit_opinion": "unmodified"}
    return {**meta, **overrides}


def test_risk_financial_min_current_ratio(rule):
    from app.services.collectors.company_collectors import financial_statement_score
    rule("risk.financial_min_current_ratio", 1.2)    # 1.3: passes, all five checks
    assert financial_statement_score(_statement())[0] == 1.0
    rule("risk.financial_min_current_ratio", 1.5)    # 1.3: fails liquidity
    assert financial_statement_score(_statement())[0] == 0.8


def test_risk_financial_max_debt_to_equity(rule):
    from app.services.collectors.company_collectors import financial_statement_score
    rule("risk.financial_max_debt_to_equity", 1.0)   # 0.9: passes
    assert financial_statement_score(_statement())[0] == 1.0
    rule("risk.financial_max_debt_to_equity", 0.5)   # 0.9: fails leverage
    assert financial_statement_score(_statement())[0] == 0.8
