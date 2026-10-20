"""Budget control before approval (feature expansion Phase 1).

A budget is money set aside for one department, IT category (hardware,
software, saas, services) and fiscal period. Each new purchase request is
checked against what is left and remembers which budget it draws on
(`purchase_requests.budget_id`).

What a budget has used is never stored; it is computed from the requests
that point at it and the invoices booked against them:

  consumed   invoiced on requests that are approved or later
  committed  the rest of those requests' amounts (approved, not invoiced yet)
  pending    requests still waiting for approval or stock

So approval, rejection, cancellation and backorder splits are reflected
automatically, wherever in the code the status changes. A request counts
against its budget from the moment it is created (pending), which is the
conservative choice: two requests can't both be told there is money left
for the same rupees.

Rules:
  budget.fiscal_period_type                    quarterly | annual
  budget.fiscal_year_start_month               4 (April, Indian fiscal year)
  budget.warning_threshold_pct                 0.8: request takes the budget past 80 %
  budget.over_budget_requires_finance_approval adds a finance step when over
  budget.block_when_over                       refuse over-budget requests instead
  budget.no_budget_policy                      allow | finance_approval | block
  approval.high_risk_vendor_requires_finance   High-band vendor adds a finance step
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.rules_engine import get_rule

CATEGORIES = ("hardware", "software", "saas", "services")
# Reclaims and reinstatements move seats around; they don't spend money.
CATEGORY_BY_REQUEST_TYPE = {"hardware": "hardware", "license": "software", "saas": "saas"}
USED_STATUSES = ("approved", "ordered", "fulfilled", "partially_invoiced", "invoice_received")
PENDING_STATUSES = ("pending_approval", "backordered")
FINANCE_LEVEL = "finance_head"


class BudgetBlocked(Exception):
    """The request may not be created (rule budget.block_when_over or
    budget.no_budget_policy = block)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class BudgetCheck:
    status: str                       # within | warning | over | no_budget
    fiscal_year: str
    period: str
    category: str
    department: str
    budget_id: Optional[str] = None
    budget_amount: Optional[float] = None
    used_before: float = 0.0          # consumed + committed + pending, before this request
    request_amount: float = 0.0
    left_after: Optional[float] = None
    warning_crossed: bool = False     # this request moved the budget into warning / over
    routing: list = field(default_factory=list)  # why approval steps were added

    def to_dict(self) -> dict:
        return asdict(self)


def category_for(request_type: Optional[str]) -> Optional[str]:
    return CATEGORY_BY_REQUEST_TYPE.get(request_type or "")


def fiscal_period(when: datetime, period_type: Optional[str] = None, start_month: Optional[int] = None) -> tuple[str, str]:
    """(fiscal_year, period) for a date: ("2026-27", "Q3") with an April
    start, or ("2026-27", "FY") when budgets are annual."""
    period_type = period_type or get_rule("budget.fiscal_period_type", fallback="quarterly")
    start_month = int(start_month or get_rule("budget.fiscal_year_start_month", fallback=4))
    first_year = when.year if when.month >= start_month else when.year - 1
    fiscal_year = f"{first_year}-{(first_year + 1) % 100:02d}"
    if period_type == "annual":
        return fiscal_year, "FY"
    return fiscal_year, f"Q{(when.month - start_month) % 12 // 3 + 1}"


_USAGE_SQL = """
SELECT pr.budget_id AS budget_id,
       COALESCE(SUM(CASE WHEN pr.status IN :used THEN COALESCE(a.invoiced, 0) ELSE 0 END), 0) AS consumed,
       COALESCE(SUM(CASE WHEN pr.status IN :used THEN GREATEST(pr.amount - COALESCE(a.invoiced, 0), 0) ELSE 0 END), 0) AS committed,
       COALESCE(SUM(CASE WHEN pr.status IN :pending THEN pr.amount ELSE 0 END), 0) AS pending
FROM purchase_requests pr
LEFT JOIN (SELECT purchase_request_id, SUM(amount) AS invoiced
           FROM invoice_allocations GROUP BY purchase_request_id) a
       ON a.purchase_request_id = pr.id
WHERE pr.budget_id IN :ids
GROUP BY pr.budget_id
"""


async def usage(db: AsyncSession, budget_ids: list[str]) -> dict[str, dict]:
    """{budget_id: {consumed, committed, pending, used}} for these budgets."""
    from sqlalchemy import bindparam
    out = {str(b): {"consumed": 0.0, "committed": 0.0, "pending": 0.0, "used": 0.0} for b in budget_ids}
    if not budget_ids:
        return out
    stmt = text(_USAGE_SQL).bindparams(
        bindparam("ids", expanding=True), bindparam("used", expanding=True), bindparam("pending", expanding=True))
    rows = (await db.execute(stmt, {"ids": list(budget_ids), "used": list(USED_STATUSES),
                                    "pending": list(PENDING_STATUSES)})).mappings().all()
    for r in rows:
        consumed, committed, pending = float(r["consumed"]), float(r["committed"]), float(r["pending"])
        out[str(r["budget_id"])] = {"consumed": consumed, "committed": committed, "pending": pending,
                                    "used": consumed + committed + pending}
    return out


def summarise(budget, used: dict) -> dict:
    amount = float(budget.amount_inr)
    left = amount - used["used"]
    return {
        "id": str(budget.id), "fiscal_year": budget.fiscal_year, "period": budget.period,
        "department": budget.department, "category": budget.category, "amount_inr": amount,
        "owner_email": budget.owner_email, **used, "left": round(left, 2),
        "used_pct": round(used["used"] / amount, 4) if amount else None,
        "status": status_for(amount, used["used"]),
    }


def status_for(amount: float, used: float) -> str:
    if used > amount + 0.005:
        return "over"
    warn = float(get_rule("budget.warning_threshold_pct", fallback=0.8))
    if amount and used / amount >= warn:
        return "warning"
    return "within"


async def find_budget(db: AsyncSession, fiscal_year: str, period: str, department: str, category: str,
                      lock: bool = False):
    from sqlalchemy import func, select
    from app.models import Budget
    stmt = select(Budget).where(
        Budget.fiscal_year == fiscal_year, Budget.period == period,
        func.lower(Budget.department) == department.lower(), Budget.category == category)
    if lock:
        # Held until the request is committed: two requests drawing on the
        # same budget are checked one after the other.
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalars().first()


async def check_request(db: AsyncSession, *, request_type: Optional[str], department: str, amount: float,
                        when: Optional[datetime] = None) -> Optional[BudgetCheck]:
    """The budget check for a new request, or None when the request type
    doesn't spend money. Locks the budget row for the caller's transaction."""
    category = category_for(request_type)
    if category is None:
        return None
    fiscal_year, period = fiscal_period(when or datetime.now(timezone.utc))
    amount = float(amount or 0)
    budget = await find_budget(db, fiscal_year, period, department or "", category, lock=True)
    if budget is None:
        return BudgetCheck(status="no_budget", fiscal_year=fiscal_year, period=period, category=category,
                           department=department, request_amount=amount)
    used_before = (await usage(db, [str(budget.id)]))[str(budget.id)]["used"]
    total = float(budget.amount_inr)
    before, after = status_for(total, used_before), status_for(total, used_before + amount)
    rank = {"within": 0, "warning": 1, "over": 2}
    return BudgetCheck(
        status=after, fiscal_year=fiscal_year, period=period, category=category, department=department,
        budget_id=str(budget.id), budget_amount=total, used_before=round(used_before, 2), request_amount=amount,
        left_after=round(total - used_before - amount, 2), warning_crossed=rank[after] > rank[before],
    )


async def vendor_risk_band(db: AsyncSession, vendor_id: Optional[str]) -> Optional[str]:
    """Latest risk band from contract-risk-agent's risk_scores (shared DB)."""
    if not vendor_id:
        return None
    row = (await db.execute(text(
        "SELECT band FROM risk_scores WHERE vendor_id = :v ORDER BY scored_at DESC NULLS LAST LIMIT 1"
    ), {"v": vendor_id})).first()
    return row[0] if row else None


def route(chain: list[str], check: Optional[BudgetCheck], vendor_band: Optional[str],
          spends_money: bool) -> tuple[list[str], list[str]]:
    """The approval chain after the budget and vendor-risk rules, and the
    reasons for any step added. Raises BudgetBlocked when a rule refuses
    the request outright."""
    reasons = []
    if check is not None:
        if check.status == "over":
            if get_rule("budget.block_when_over", fallback=False):
                raise BudgetBlocked("over_budget", (
                    f"This request (₹{check.request_amount:,.0f}) is more than the ₹{max(check.budget_amount - check.used_before, 0):,.0f} "
                    f"left in the {check.department} {check.category} budget for {check.period} {check.fiscal_year}."))
            if get_rule("budget.over_budget_requires_finance_approval", fallback=True):
                reasons.append("over_budget")
        elif check.status == "no_budget":
            policy = get_rule("budget.no_budget_policy", fallback="allow")
            if policy == "block":
                raise BudgetBlocked("no_budget", (
                    f"There is no {check.category} budget for {check.department} in {check.period} {check.fiscal_year}."))
            if policy == "finance_approval":
                reasons.append("no_budget")
    if spends_money and vendor_band == "High" and get_rule("approval.high_risk_vendor_requires_finance", fallback=False):
        reasons.append("high_risk_vendor")
    chain = list(chain or [])
    if reasons and FINANCE_LEVEL not in chain:
        chain.append(FINANCE_LEVEL)
    return chain, reasons
