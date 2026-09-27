from datetime import datetime, timedelta, timezone

from app.services.approval_authority import Assignment, Delegation, evaluate_authority

NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
ASSIGNED = [
    Assignment("dept_manager", "approver@acme.test", None),
    Assignment("dept_manager", "lead@acme.test", 50_000),
    Assignment("finance_head", "finance@acme.test", None),
    Assignment("dept_manager", "admin@acme.test", None),
    Assignment("finance_head", "admin@acme.test", None),
]


def decide(user, *, level="dept_manager", amount=10_000, requested_by="req@acme.test", decision="approved",
           prior=(), delegations=()):
    return evaluate_authority(
        decision=decision, requested_by=requested_by, amount=amount, level=level, user_email=user,
        assignments=ASSIGNED, delegations=list(delegations), prior_approvers=list(prior), now=NOW,
    )


def test_assigned_approver_allowed():
    assert decide("approver@acme.test").allowed


def test_email_match_is_case_insensitive():
    assert decide("Approver@ACME.test").allowed


def test_not_assigned_to_this_level():
    d = decide("finance@acme.test", level="dept_manager")
    assert not d.allowed and d.code == "NOT_ASSIGNED"


def test_self_approval_blocked_even_for_admin():
    d = decide("admin@acme.test", requested_by="admin@acme.test")
    assert not d.allowed and d.code == "SEPARATION_OF_DUTIES"


def test_same_person_cannot_approve_two_levels():
    d = decide("admin@acme.test", level="finance_head", prior=["admin@acme.test"])
    assert not d.allowed and d.code == "SEPARATION_OF_DUTIES"


def test_requester_may_reject_but_not_approve():
    assert decide("admin@acme.test", requested_by="admin@acme.test", decision="rejected").allowed


def test_amount_limit():
    assert decide("lead@acme.test", amount=40_000).allowed
    d = decide("lead@acme.test", amount=60_000)
    assert not d.allowed and d.code == "OVER_LIMIT" and d.limit == 50_000


def test_live_delegation_grants_authority():
    dele = Delegation("dept_manager", "approver@acme.test", "stand-in@acme.test", NOW - timedelta(days=1), NOW + timedelta(days=1))
    d = decide("stand-in@acme.test", delegations=[dele])
    assert d.allowed and d.via_delegation == "approver@acme.test"


def test_expired_delegation_does_not():
    dele = Delegation("dept_manager", "approver@acme.test", "stand-in@acme.test", NOW - timedelta(days=5), NOW - timedelta(days=1))
    assert not decide("stand-in@acme.test", delegations=[dele]).allowed


def test_delegation_from_unassigned_user_grants_nothing():
    dele = Delegation("dept_manager", "nobody@acme.test", "stand-in@acme.test", NOW - timedelta(days=1), NOW + timedelta(days=1))
    assert not decide("stand-in@acme.test", delegations=[dele]).allowed


def test_no_pending_level():
    assert decide("approver@acme.test", level=None).code == "NO_PENDING_LEVEL"
