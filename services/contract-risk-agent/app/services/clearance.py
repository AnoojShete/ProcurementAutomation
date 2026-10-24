"""Vendor clearance: may this vendor be activated, bought from or signed with?

One decision used everywhere (Prompt 9C C3/C4): the /clearance endpoint,
contract signing (signing_risk) and anything downstream. `decide` is pure;
`evaluate` loads the latest score, the latest human decision and the vendor.

Order of the checks:
  1. no score                         -> not cleared
  2. a non-remediable hard override   -> never cleared, whatever a person
     (sanctions match, prohibited        decided (red-team finding: an admin's
     country)                            "accept risk" used to clear it)
  3. the score: other overrides, not rated, provisional (activation never;
     a purchase only under the petty exception), High
  4. the latest human decision: reject blocks; approve / approve with
     conditions only count while the current score is still assessed Low or
     Medium with no override (red-team finding: an old approval used to keep
     a vendor cleared after its score turned High); accept risk counts until
     it expires
  5. vendor status: purchases and contracts need an active vendor

`reasons` holds only what decided the outcome (merge review G7).
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import desc, select, text

PETTY_TIER = "petty"            # vendors.vendor_tier: petty | standard | strategic


@dataclass
class ScoreView:
    rating_status: str
    final_band: str
    points_band: str = "Low"
    score: Optional[float] = None
    override_rule_ids: list = field(default_factory=list)
    non_remediable: set = field(default_factory=set)
    provisional_reasons: list = field(default_factory=list)
    blocked_by: list = field(default_factory=list)
    pending_review: set = field(default_factory=set)   # signal keys whose result awaits a person


@dataclass
class DecisionView:
    decision: str
    expires_at: Optional[datetime] = None
    conditions: list = field(default_factory=list)


def _overdue(conditions: list, now: datetime) -> tuple[list, bool]:
    out, any_overdue = [], False
    for i, c in enumerate(conditions or []):
        due, status = c.get("due_date"), c.get("status", "pending")
        overdue = False
        if due and status != "fulfilled":
            try:
                overdue = datetime.strptime(str(due)[:10], "%Y-%m-%d").date() < now.date()
            except ValueError:
                overdue = False
        any_overdue = any_overdue or overdue
        out.append({"id": c.get("id", f"c{i + 1}"), "text": c.get("text", ""), "due_date": due,
                    "status": status, "overdue": overdue})
    return out, any_overdue


def _sanctions_pending(score: "ScoreView") -> bool:
    """A possible sanctions match waiting for review. For a petty vendor the
    sanctions check isn't required, so it doesn't show up among the
    provisional reasons; the rule result's status does (red-team finding)."""
    return "sanctions" in (score.pending_review or set()) or any(
        r.get("signal") == "sanctions" for r in score.provisional_reasons or [] if isinstance(r, dict))


def decide(score: Optional[ScoreView], decision: Optional[DecisionView], *, purpose: str,
           spend_amount: Optional[float], vendor_tier: Optional[str], vendor_status: Optional[str],
           petty_threshold: float, now: datetime) -> dict:
    if score is None:
        return {"cleared": False, "purpose": purpose, "rating_status": "not_rated", "final_band": "Unrated",
                "points_band": "Low", "risk_score": None, "blocked_by": [], "overrides_active": [],
                "required_signals_missing": [], "post_score_decision": None, "decision_expires_at": None,
                "conditions": [], "reasons": ["scorecard_unavailable"]}

    overrides = list(score.override_rule_ids or [])
    blocked_by = list(dict.fromkeys(list(score.blocked_by or []) + overrides))
    conditions, overdue = _overdue(decision.conditions if decision else [], now)
    blocking: list[str] = []
    basis: Optional[str] = None

    # 2. Non-remediable overrides: nothing clears them.
    hard = [o for o in overrides if o in (score.non_remediable or set())]
    blocking += [f"override_{o}" for o in hard]

    # 3. The score on its own.
    if not hard:
        if overrides:
            blocking += [f"override_{o}" for o in overrides]
        elif score.rating_status == "not_rated":
            blocking.append("vendor_not_rated")
        elif score.rating_status == "provisional":
            # Prompt 10 Section 6.2: petty exception requires effective_tier 'low', no overrides, and amount <= vendor.petty_tier_max_amount
            is_effective_low = (getattr(score, "effective_tier", None) or "low").lower() == "low"
            petty = (purpose != "activation" and (vendor_tier or "").lower() == PETTY_TIER
                     and is_effective_low and not overrides
                     and spend_amount is not None and spend_amount <= petty_threshold
                     and not _sanctions_pending(score))
            if petty:
                basis = "cleared_under_petty_exception"
            else:
                blocking.append("rating_provisional")
        elif score.final_band == "High":
            blocking.append("high_risk_band")
        else:
            basis = f"assessed_{score.final_band.lower()}"

    # 4. The latest human decision.
    if decision and not hard:
        d = decision.decision
        still_eligible = score.rating_status == "assessed" and score.final_band in ("Low", "Medium") and not overrides
        if d == "reject":
            blocking, basis = ["decision_rejected"], None
        elif d in ("approve", "approve_with_conditions"):
            if not still_eligible:
                blocking.append("approval_ineligible")
                basis = None
            elif d == "approve_with_conditions" and overdue:
                blocking, basis = ["condition_overdue"], None
            else:
                blocking, basis = [], d
        elif d == "accept_risk":
            if decision.expires_at and decision.expires_at < now:
                blocking, basis = blocking + ["risk_acceptance_expired"], None
            else:
                until = decision.expires_at.date().isoformat() if decision.expires_at else "no expiry"
                blocking, basis = [], f"risk_accepted_until_{until}"

    # 5. Vendor status.
    status = vendor_status or "onboarding"
    if purpose in ("purchase", "contract") and status != "active":
        blocking.append(f"vendor_status_{status}_not_active")
    elif purpose == "activation" and status not in ("onboarding", "active"):
        blocking.append(f"vendor_status_{status}_invalid_for_activation")

    cleared = not blocking and basis is not None
    return {
        "cleared": cleared, "purpose": purpose, "rating_status": score.rating_status,
        "final_band": score.final_band, "points_band": score.points_band, "risk_score": score.score,
        "blocked_by": blocked_by, "overrides_active": overrides, "non_remediable_overrides": hard,
        "required_signals_missing": list(score.provisional_reasons or []),
        "post_score_decision": decision.decision if decision else None,
        "decision_expires_at": decision.expires_at.isoformat() if decision and decision.expires_at else None,
        "conditions": conditions,
        "reasons": [basis] if cleared else list(dict.fromkeys(blocking)),
    }


# ── loading ──────────────────────────────────────────────────────────────────

def score_view(row, non_remediable: set, pending_review: Optional[set] = None) -> ScoreView:
    rating = getattr(row, "rating_status", None) or ("provisional" if getattr(row, "is_provisional", False) else "assessed")
    return ScoreView(
        rating_status=rating, final_band=getattr(row, "final_band", None) or getattr(row, "band", None) or "Unrated",
        points_band=getattr(row, "points_band", None) or "Low",
        score=float(row.score) if getattr(row, "score", None) is not None else None,
        override_rule_ids=list(getattr(row, "override_rule_ids", None) or []), non_remediable=non_remediable,
        provisional_reasons=list(getattr(row, "provisional_reasons", None) or []),
        blocked_by=list(getattr(row, "blocked_by", None) or []), pending_review=pending_review or set())


async def load(db, vendor_id: str) -> tuple[Any, Optional[ScoreView], Optional[DecisionView]]:
    """(vendor, score view, latest decision). Non-remediable overrides and
    checks awaiting review come from the score's own stored rule results."""
    from app.models import Vendor, VendorDecision
    from app.services import risk_service
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        return None, None, None
    row = await risk_service.latest_risk_score(db, vendor_id)
    latest = (await db.execute(select(VendorDecision).where(VendorDecision.vendor_id == vendor_id)
                               .order_by(desc(VendorDecision.decided_at)).limit(1))).scalars().first()
    decision = DecisionView(latest.decision, latest.expires_at, list(latest.conditions or [])) if latest else None
    if row is None:
        return vendor, None, decision
    res = await db.execute(text(
        "SELECT rule_id, signal_key, status, override_band, remediable FROM risk_score_rule_results "
        "WHERE score_id = :s AND (override_band IS NOT NULL OR status = 'review_pending')"), {"s": str(row.id)})
    rows = res.all()
    non_remediable = {r.rule_id for r in rows if r.override_band and r.remediable is False}
    pending = {r.signal_key for r in rows if r.status == "review_pending"}
    return vendor, score_view(row, non_remediable, pending), decision


async def evaluate(db, vendor_id: str, purpose: str = "purchase", spend_amount: Optional[float] = None,
                   now: Optional[datetime] = None) -> Optional[dict]:
    """The clearance of a vendor, or None when the vendor doesn't exist."""
    from shared.rules_engine import get_rule
    vendor, score, decision = await load(db, vendor_id)
    if vendor is None:
        return None
    return decide(score, decision, purpose=purpose, spend_amount=spend_amount,
                  vendor_tier=getattr(vendor, "vendor_tier", None), vendor_status=getattr(vendor, "status", None),
                  petty_threshold=float(get_rule("vendor.petty_tier_max_amount", fallback=get_rule("risk.petty_threshold", fallback=50000.0))),
                  now=now or datetime.now(timezone.utc))
