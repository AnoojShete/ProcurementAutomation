"""Approval authority and separation of duties.

Before this, any approver/finance/admin could approve any request at any
level, including one they raised themselves (admin can both create and
approve). Now a decision is allowed only when:

  - the caller is assigned to the level the request is waiting on
    (approver_assignments), directly or through a live delegation from an
    assigned approver (approval_delegations);
  - the amount is within the caller's limit for that level;
  - for approvals: the caller is not the requester (maker != checker),
    and hasn't already approved an earlier level of the same request —
    every level needs a different person.

evaluate_authority() is pure so the rules are unit-testable; the rest
loads its inputs and records assignments/delegations.
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text


@dataclass
class Assignment:
    level: str
    user_email: str
    max_amount: Optional[float] = None


@dataclass
class Delegation:
    level: str
    delegator_email: str
    delegate_email: str
    valid_from: datetime
    valid_until: datetime


@dataclass
class AuthorityDecision:
    allowed: bool
    code: str
    reason: str
    level: Optional[str] = None
    via_delegation: Optional[str] = None
    limit: Optional[float] = None


class AuthorityError(PermissionError):
    def __init__(self, decision: AuthorityDecision):
        self.decision = decision
        super().__init__(decision.reason)


def _norm(email: Optional[str]) -> str:
    return (email or "").strip().lower()


def evaluate_authority(
    *,
    decision: str,
    requested_by: str,
    amount: float,
    level: Optional[str],
    user_email: str,
    assignments: list[Assignment],
    delegations: list[Delegation],
    prior_approvers: list[str],
    now: datetime,
) -> AuthorityDecision:
    user = _norm(user_email)
    if level is None:
        return AuthorityDecision(False, "NO_PENDING_LEVEL", "This request isn't waiting on an approval level.")

    if decision == "approved" and user == _norm(requested_by):
        return AuthorityDecision(
            False, "SEPARATION_OF_DUTIES", "You can't approve a request you raised yourself.", level,
        )
    if decision == "approved" and user in {_norm(p) for p in prior_approvers}:
        return AuthorityDecision(
            False, "SEPARATION_OF_DUTIES",
            "You already approved an earlier level of this request; each level needs a different approver.",
            level,
        )

    held = [a for a in assignments if a.level == level and _norm(a.user_email) == user]
    via = None
    if not held:
        for d in delegations:
            if d.level != level or _norm(d.delegate_email) != user or not (d.valid_from <= now <= d.valid_until):
                continue
            if _norm(d.delegator_email) == _norm(requested_by) and decision == "approved":
                continue  # a requester can't hand their own request to a proxy
            delegator_held = [a for a in assignments if a.level == level and _norm(a.user_email) == _norm(d.delegator_email)]
            if delegator_held:
                held, via = delegator_held, d.delegator_email
                break
    if not held:
        return AuthorityDecision(
            False, "NOT_ASSIGNED", f"You aren't an assigned approver for the '{level}' level.", level,
        )

    limits = [a.max_amount for a in held]
    limit = None if any(x is None for x in limits) else max(limits)
    if limit is not None and float(amount) > limit:
        return AuthorityDecision(
            False, "OVER_LIMIT",
            f"Amount {float(amount):,.2f} is above your approval limit of {limit:,.2f} for '{level}'.",
            level, via, limit,
        )
    return AuthorityDecision(True, "OK", "Allowed", level, via, limit)


# --- database side -----------------------------------------------------------

async def load_assignments(db, level: Optional[str] = None) -> list[Assignment]:
    q = "SELECT level, user_email, max_amount FROM approver_assignments WHERE active"
    params = {}
    if level:
        q += " AND level = :level"
        params["level"] = level
    rows = (await db.execute(text(q), params)).all()
    return [Assignment(r.level, r.user_email, float(r.max_amount) if r.max_amount is not None else None) for r in rows]


async def load_delegations(db, level: Optional[str] = None) -> list[Delegation]:
    q = ("SELECT level, delegator_email, delegate_email, valid_from, valid_until FROM approval_delegations "
         "WHERE revoked_at IS NULL")
    params = {}
    if level:
        q += " AND level = :level"
        params["level"] = level
    rows = (await db.execute(text(q), params)).all()
    return [Delegation(r.level, r.delegator_email, r.delegate_email, r.valid_from, r.valid_until) for r in rows]


async def check_request_authority(db, req, user_email: str, decision: str) -> AuthorityDecision:
    chain = req.approval_chain or []
    idx = req.current_approver_index or 0
    level = chain[idx] if idx < len(chain) else None
    prior = [
        h.decided_by for h in (req.approval_history or [])
        if h.decision == "approved"
    ]
    return evaluate_authority(
        decision=decision,
        requested_by=req.requested_by,
        amount=float(req.amount or 0),
        level=level,
        user_email=user_email,
        assignments=await load_assignments(db, level) if level else [],
        delegations=await load_delegations(db, level) if level else [],
        prior_approvers=prior,
        now=datetime.now(timezone.utc),
    )


async def list_authority(db) -> dict:
    assignments = (
        await db.execute(text(
            "SELECT id, level, user_email, max_amount, active, created_by, created_at "
            "FROM approver_assignments ORDER BY level, user_email"
        ))
    ).all()
    delegations = (
        await db.execute(text(
            "SELECT id, level, delegator_email, delegate_email, valid_from, valid_until, reason, created_by, "
            "created_at, revoked_at FROM approval_delegations ORDER BY created_at DESC LIMIT 200"
        ))
    ).all()
    now = datetime.now(timezone.utc)
    return {
        "assignments": [
            {
                "id": str(a.id), "level": a.level, "user_email": a.user_email,
                "max_amount": float(a.max_amount) if a.max_amount is not None else None,
                "active": a.active, "created_by": a.created_by,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in assignments
        ],
        "delegations": [
            {
                "id": str(d.id), "level": d.level, "delegator_email": d.delegator_email,
                "delegate_email": d.delegate_email, "valid_from": d.valid_from.isoformat(),
                "valid_until": d.valid_until.isoformat(), "reason": d.reason, "created_by": d.created_by,
                "active": d.revoked_at is None and d.valid_from <= now <= d.valid_until,
                "revoked_at": d.revoked_at.isoformat() if d.revoked_at else None,
            }
            for d in delegations
        ],
    }


async def upsert_assignment(db, level: str, user_email: str, max_amount: Optional[float], created_by: str) -> str:
    row_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO approver_assignments (id, level, user_email, max_amount, active, created_by, created_at) "
            "VALUES (:id, :level, :email, :max, true, :by, now()) "
            "ON CONFLICT (level, user_email) DO UPDATE SET max_amount = EXCLUDED.max_amount, active = true"
        ),
        {"id": row_id, "level": level, "email": user_email.strip().lower(), "max": max_amount, "by": created_by},
    )
    return row_id


async def deactivate_assignment(db, assignment_id: str) -> bool:
    res = await db.execute(text("UPDATE approver_assignments SET active = false WHERE id = :id"), {"id": assignment_id})
    return res.rowcount == 1


async def create_delegation(
    db, level: str, delegator_email: str, delegate_email: str, valid_until: datetime, reason: str, created_by: str,
) -> str:
    if _norm(delegator_email) == _norm(delegate_email):
        raise ValueError("can't delegate to yourself")
    if valid_until <= datetime.now(timezone.utc):
        raise ValueError("valid_until must be in the future")
    holders = await load_assignments(db, level)
    if not any(_norm(a.user_email) == _norm(delegator_email) for a in holders):
        raise ValueError(f"{delegator_email} isn't assigned to '{level}', so has nothing to delegate")
    row_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO approval_delegations (id, level, delegator_email, delegate_email, valid_from, valid_until, "
            "reason, created_by, created_at) VALUES (:id, :level, :from_, :to_, now(), :until, :reason, :by, now())"
        ),
        {
            "id": row_id, "level": level, "from_": delegator_email.strip().lower(),
            "to_": delegate_email.strip().lower(), "until": valid_until, "reason": reason, "by": created_by,
        },
    )
    return row_id


async def revoke_delegation(db, delegation_id: str) -> bool:
    res = await db.execute(
        text("UPDATE approval_delegations SET revoked_at = now() WHERE id = :id AND revoked_at IS NULL"),
        {"id": delegation_id},
    )
    return res.rowcount == 1
