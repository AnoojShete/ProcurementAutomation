import os
import uuid
from datetime import datetime, timezone
from typing import Optional, Any, List, Dict

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import BusinessRule, BusinessRuleHistory
from app.kafka_producer import publish_business_rule_updated
from shared.auth.middleware import require_role, CurrentUser

admin_router = APIRouter(prefix="/admin/business-rules", dependencies=[Depends(require_role("admin"))], tags=["Admin Business Rules"])
internal_router = APIRouter(prefix="/internal/business-rules", tags=["Internal Business Rules"])


class RulePatchRequest(BaseModel):
    new_value: Any
    justification: str


class RuleResetRequest(BaseModel):
    justification: str


def _serialize_rule(r: BusinessRule) -> dict:
    return {
        "id": r.id,
        "rule_key": r.rule_key,
        "category": r.category,
        "display_name": r.display_name,
        "description": r.description,
        "value_type": r.value_type,
        "current_value": r.current_value,
        "default_value": r.default_value,
        "min_value": float(r.min_value) if r.min_value is not None else None,
        "max_value": float(r.max_value) if r.max_value is not None else None,
        "updated_by": r.updated_by,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _serialize_history(h: BusinessRuleHistory) -> dict:
    return {
        "id": h.id,
        "rule_key": h.rule_key,
        "old_value": h.old_value,
        "new_value": h.new_value,
        "changed_by": h.changed_by,
        "changed_at": h.changed_at.isoformat() if h.changed_at else None,
        "justification": h.justification,
    }


def _validate_spend_tiers(val: Any):
    if not isinstance(val, list):
        raise HTTPException(status_code=400, detail="spend_tiers must be a list of tier objects")
    if len(val) == 0:
        raise HTTPException(status_code=400, detail="spend_tiers cannot be empty")
    
    current_min = 0.0
    for idx, tier in enumerate(val):
        if not isinstance(tier, dict):
            raise HTTPException(status_code=400, detail=f"Tier at index {idx} must be an object")
        if "tier_name" not in tier or "min_amount" not in tier or "max_amount" not in tier:
            raise HTTPException(status_code=400, detail=f"Tier at index {idx} missing required fields (tier_name, min_amount, max_amount)")
        
        approvers = tier.get("required_approvers")
        if approvers is None:
            approvers = tier.get("required_roles")
        if approvers is None or (tier.get("tier_name") != "auto" and len(approvers) == 0):
            raise HTTPException(status_code=400, detail=f"Tier at index {idx} must have at least one required approver")

        t_min = float(tier["min_amount"]) if tier["min_amount"] is not None else 0.0
        t_max = float(tier["max_amount"]) if tier["max_amount"] is not None else None
        
        if idx > 0 and t_min != current_min:
            raise HTTPException(status_code=400, detail=f"Tier '{tier.get('tier_name')}' min_amount ({t_min}) must equal previous tier upper bound ({current_min}) to be contiguous")
        if t_max is not None and t_max <= t_min:
            raise HTTPException(status_code=400, detail=f"Tier '{tier.get('tier_name')}' max_amount ({t_max}) must be > min_amount ({t_min})")
        if t_max is not None:
            current_min = t_max
        elif idx != len(val) - 1:
            raise HTTPException(status_code=400, detail="Only the final tier may have an unlimited (null) max_amount")


async def _validate_rule_value(db: AsyncSession, rule: BusinessRule, new_value: Any):
    v_type = rule.value_type
    
    if v_type == "bool":
        if not isinstance(new_value, bool):
            raise HTTPException(status_code=400, detail=f"Value for '{rule.rule_key}' must be a boolean")
    elif v_type == "int":
        if not isinstance(new_value, int) or isinstance(new_value, bool):
            raise HTTPException(status_code=400, detail=f"Value for '{rule.rule_key}' must be an integer")
    elif v_type in ("float", "decimal"):
        if not isinstance(new_value, (int, float)) or isinstance(new_value, bool):
            raise HTTPException(status_code=400, detail=f"Value for '{rule.rule_key}' must be a number")
    elif v_type == "json":
        if rule.rule_key == "approval.spend_tiers":
            _validate_spend_tiers(new_value)
        elif rule.rule_key == "budget.fiscal_period_type":
            if new_value not in ("quarterly", "annual"):
                raise HTTPException(status_code=400, detail="budget.fiscal_period_type must be 'quarterly' or 'annual'")
        elif rule.rule_key == "risk.contract_renewal_milestones_days":
            if not isinstance(new_value, list) or not all(isinstance(x, int) and x > 0 for x in new_value):
                raise HTTPException(status_code=400, detail="renewal milestones must be a list of positive integers")

    # Min / Max bounds
    if rule.min_value is not None:
        if isinstance(new_value, (int, float)) and new_value < float(rule.min_value):
            raise HTTPException(
                status_code=400,
                detail=f"Value {new_value} is below minimum allowed value of {rule.min_value}",
            )
    if rule.max_value is not None:
        if isinstance(new_value, (int, float)) and new_value > float(rule.max_value):
            raise HTTPException(
                status_code=400,
                detail=f"Value {new_value} is above maximum allowed value of {rule.max_value}",
            )

    # Cross-field validations
    async def get_other_val(key: str):
        res = await db.execute(select(BusinessRule).where(BusinessRule.rule_key == key))
        r = res.scalars().first()
        return float(r.current_value) if r and r.current_value is not None else None

    if rule.rule_key == "vendor.petty_tier_max_amount":
        std_val = await get_other_val("vendor.standard_tier_max_amount")
        if std_val is not None and float(new_value) >= std_val:
            raise HTTPException(status_code=400, detail=f"petty_tier_max_amount ({new_value}) must be strictly less than standard_tier_max_amount ({std_val})")
    elif rule.rule_key == "vendor.standard_tier_max_amount":
        petty_val = await get_other_val("vendor.petty_tier_max_amount")
        if petty_val is not None and float(new_value) <= petty_val:
            raise HTTPException(status_code=400, detail=f"standard_tier_max_amount ({new_value}) must be strictly greater than petty_tier_max_amount ({petty_val})")

    elif rule.rule_key == "license.anomaly_watch_threshold":
        anom_val = await get_other_val("license.anomaly_anomalous_threshold")
        if anom_val is not None and float(new_value) >= anom_val:
            raise HTTPException(status_code=400, detail=f"anomaly_watch_threshold ({new_value}) must be strictly less than anomaly_anomalous_threshold ({anom_val})")
    elif rule.rule_key == "license.anomaly_anomalous_threshold":
        watch_val = await get_other_val("license.anomaly_watch_threshold")
        if watch_val is not None and float(new_value) <= watch_val:
            raise HTTPException(status_code=400, detail=f"anomaly_anomalous_threshold ({new_value}) must be strictly greater than anomaly_watch_threshold ({watch_val})")

    elif rule.rule_key == "risk.psi_moderate_threshold":
        sig_val = await get_other_val("risk.psi_significant_threshold")
        if sig_val is not None and float(new_value) >= sig_val:
            raise HTTPException(status_code=400, detail=f"psi_moderate_threshold ({new_value}) must be strictly less than psi_significant_threshold ({sig_val})")
    elif rule.rule_key == "risk.psi_significant_threshold":
        mod_val = await get_other_val("risk.psi_moderate_threshold")
        if mod_val is not None and float(new_value) <= mod_val:
            raise HTTPException(status_code=400, detail=f"psi_significant_threshold ({new_value}) must be strictly greater than psi_moderate_threshold ({mod_val})")


@admin_router.get("")
async def get_all_business_rules(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BusinessRule).order_by(BusinessRule.category, BusinessRule.rule_key))
    rules = list(result.scalars().all())
    grouped: Dict[str, list] = {}
    for r in rules:
        grouped.setdefault(r.category, []).append(_serialize_rule(r))
    return {"data": grouped}


@admin_router.get("/history")
async def get_recent_history(
    category: Optional[str] = Query(None),
    rule_key: Optional[str] = Query(None),
    changed_by: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = select(BusinessRuleHistory)
    if category:
        query = query.join(BusinessRule, BusinessRule.rule_key == BusinessRuleHistory.rule_key).where(BusinessRule.category == category)
    if rule_key:
        query = query.where(BusinessRuleHistory.rule_key == rule_key)
    if changed_by:
        query = query.where(BusinessRuleHistory.changed_by.ilike(f"%{changed_by}%"))
    if date_from:
        try:
            df = datetime.fromisoformat(date_from)
            query = query.where(BusinessRuleHistory.changed_at >= df)
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.fromisoformat(date_to)
            query = query.where(BusinessRuleHistory.changed_at <= dt)
        except ValueError:
            pass

    query = query.order_by(desc(BusinessRuleHistory.changed_at)).offset(offset).limit(limit)
    result = await db.execute(query)
    items = list(result.scalars().all())
    return {"data": [_serialize_history(h) for h in items]}


@admin_router.get("/{rule_key}")
async def get_single_business_rule(rule_key: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BusinessRule).where(BusinessRule.rule_key == rule_key))
    rule = result.scalars().first()
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_key}' not found")
    
    hist_result = await db.execute(
        select(BusinessRuleHistory)
        .where(BusinessRuleHistory.rule_key == rule_key)
        .order_by(desc(BusinessRuleHistory.changed_at))
        .limit(20)
    )
    history = list(hist_result.scalars().all())
    return {"data": {"rule": _serialize_rule(rule), "history": [_serialize_history(h) for h in history]}}


@admin_router.patch("/{rule_key}")
async def patch_business_rule(
    rule_key: str,
    payload: RulePatchRequest,
    current_user: CurrentUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    if not payload.justification or not payload.justification.strip():
        raise HTTPException(status_code=400, detail="Justification is required and cannot be empty")
    
    result = await db.execute(select(BusinessRule).where(BusinessRule.rule_key == rule_key))
    rule = result.scalars().first()
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_key}' not found")

    await _validate_rule_value(db, rule, payload.new_value)

    old_val = rule.current_value
    now = datetime.now(timezone.utc)
    
    history_entry = BusinessRuleHistory(
        id=str(uuid.uuid4()),
        rule_key=rule.rule_key,
        old_value=old_val,
        new_value=payload.new_value,
        changed_by=current_user.email or current_user.id,
        changed_at=now,
        justification=payload.justification.strip(),
    )
    db.add(history_entry)

    rule.current_value = payload.new_value
    rule.updated_by = current_user.id
    rule.updated_at = now

    await db.commit()
    await db.refresh(rule)

    await publish_business_rule_updated(
        rule_key=rule.rule_key,
        new_value=rule.current_value,
        changed_by=current_user.email or current_user.id,
        changed_at=now.isoformat(),
    )

    return {"data": _serialize_rule(rule)}


@admin_router.post("/{rule_key}/reset")
async def reset_business_rule(
    rule_key: str,
    payload: RuleResetRequest,
    current_user: CurrentUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    if not payload.justification or not payload.justification.strip():
        raise HTTPException(status_code=400, detail="Justification is required and cannot be empty")

    result = await db.execute(select(BusinessRule).where(BusinessRule.rule_key == rule_key))
    rule = result.scalars().first()
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_key}' not found")

    await _validate_rule_value(db, rule, rule.default_value)

    old_val = rule.current_value
    now = datetime.now(timezone.utc)

    history_entry = BusinessRuleHistory(
        id=str(uuid.uuid4()),
        rule_key=rule.rule_key,
        old_value=old_val,
        new_value=rule.default_value,
        changed_by=current_user.email or current_user.id,
        changed_at=now,
        justification=payload.justification.strip(),
    )
    db.add(history_entry)

    rule.current_value = rule.default_value
    rule.updated_by = current_user.id
    rule.updated_at = now

    await db.commit()
    await db.refresh(rule)

    await publish_business_rule_updated(
        rule_key=rule.rule_key,
        new_value=rule.current_value,
        changed_by=current_user.email or current_user.id,
        changed_at=now.isoformat(),
    )

    return {"data": _serialize_rule(rule)}


@internal_router.get("")
async def get_internal_rules(
    x_internal_service_secret: Optional[str] = Header(None, alias="X-Internal-Service-Secret"),
    db: AsyncSession = Depends(get_db),
):
    expected_secret = os.environ.get("RULES_ENGINE_INTERNAL_SECRET", "dev-rules-secret-change-me")
    if not x_internal_service_secret or x_internal_service_secret != expected_secret:
        raise HTTPException(status_code=403, detail="Invalid internal service secret")
    
    result = await db.execute(select(BusinessRule))
    rules = list(result.scalars().all())
    data = {r.rule_key: r.current_value for r in rules}
    return {"data": data}
