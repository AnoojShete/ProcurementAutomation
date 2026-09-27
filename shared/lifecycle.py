"""Legal purchase-request status transitions.

Enforced on the PurchaseRequest model itself (approval-inventory-agent's
app/models.py, via @validates), so every writer — API, Temporal
activities, Kafka handlers, the reconciler — goes through the same rules.
Before this, handlers set statuses unconditionally: an invoice.matched
event could move a *rejected* request to invoice_received.

Setting the status it already has is always allowed (a no-op), which is
what makes redelivered events harmless.
"""

TERMINAL = frozenset({"rejected", "cancelled", "split", "invoice_received"})

REQUEST_TRANSITIONS: dict[str, frozenset] = {
    "pending_approval": frozenset({"approved", "rejected", "cancelled", "split"}),
    # Reclaim requests wait out a grace period before entering approval.
    "pending_grace_period": frozenset({"pending_approval", "approved", "rejected", "cancelled"}),
    "backordered": frozenset({"pending_approval", "cancelled"}),
    # An invoice may arrive before or after the contract is signed.
    "approved": frozenset({"fulfilled", "partially_invoiced", "invoice_received", "cancelled"}),
    "fulfilled": frozenset({"partially_invoiced", "invoice_received"}),
    "partially_invoiced": frozenset({"invoice_received"}),
    **{s: frozenset() for s in TERMINAL},
}

# How far along the lifecycle a status is — used to recognise an event that
# arrives after the request has already moved past it (e.g. contract.signed
# after the invoice was received): that's not an error, just nothing to do.
PROGRESS = {
    "pending_grace_period": 0, "backordered": 0, "pending_approval": 0,
    "approved": 1, "fulfilled": 2, "partially_invoiced": 3, "invoice_received": 4,
}


class IllegalTransition(ValueError):
    def __init__(self, current: str, target: str):
        self.current = current
        self.target = target
        super().__init__(f"illegal purchase request transition {current!r} -> {target!r}")


def can_transition(current: str | None, target: str) -> bool:
    if current is None or current == target:
        return True
    allowed = REQUEST_TRANSITIONS.get(current)
    if allowed is None:
        # A status this table doesn't know yet — don't block legacy data.
        return True
    return target in allowed


def check_transition(current: str | None, target: str) -> None:
    if not can_transition(current, target):
        raise IllegalTransition(current, target)


def already_past(current: str | None, target: str) -> bool:
    """True when `current` is further along the happy path than `target`."""
    if current is None or current not in PROGRESS or target not in PROGRESS:
        return False
    return PROGRESS[current] > PROGRESS[target]
