"""shared/lifecycle.py — the purchase-request state machine."""
import pytest

from shared.lifecycle import IllegalTransition, already_past, can_transition, check_transition


@pytest.mark.parametrize("current,target", [
    ("pending_approval", "approved"),
    ("pending_approval", "rejected"),
    ("approved", "fulfilled"),
    ("approved", "invoice_received"),       # invoice before the contract is signed
    ("fulfilled", "partially_invoiced"),
    ("partially_invoiced", "invoice_received"),
    ("pending_grace_period", "pending_approval"),
    (None, "pending_approval"),            # new row
    ("approved", "approved"),              # redelivery is a no-op
])
def test_legal(current, target):
    assert can_transition(current, target)
    check_transition(current, target)


@pytest.mark.parametrize("current,target", [
    ("rejected", "invoice_received"),      # the old invoice.matched handler allowed this
    ("pending_approval", "invoice_received"),
    ("pending_approval", "fulfilled"),
    ("invoice_received", "fulfilled"),     # never move backwards
    ("cancelled", "approved"),
    ("fulfilled", "approved"),
])
def test_illegal(current, target):
    assert not can_transition(current, target)
    with pytest.raises(IllegalTransition):
        check_transition(current, target)


def test_unknown_legacy_status_is_not_blocked():
    assert can_transition("some_old_status", "approved")


def test_already_past():
    assert already_past("invoice_received", "fulfilled")
    assert already_past("partially_invoiced", "fulfilled")
    assert not already_past("approved", "fulfilled")
    assert not already_past("rejected", "fulfilled")
