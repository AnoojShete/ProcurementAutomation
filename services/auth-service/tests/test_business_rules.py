"""Unit and integration tests for Business Rules API endpoints and validation."""
import os
import sys
_service_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _service_root not in sys.path:
    sys.path.insert(0, _service_root)

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.models import BusinessRule, BusinessRuleHistory
from app.api.business_rules import (
    _validate_spend_tiers,
    _validate_rule_value,
    get_all_business_rules,
    patch_business_rule,
    reset_business_rule,
    get_internal_rules,
    RulePatchRequest,
    RuleResetRequest,
)
from shared.auth.jwt_tokens import create_access_token


class TestSpendTiersValidation:
    def test_valid_contiguous_spend_tiers(self):
        tiers = [
            {
                "tier_name": "tier_1",
                "min_amount": 0,
                "max_amount": 1000,
                "required_approvers": ["manager"],
                "sla_hours": 24,
            },
            {
                "tier_name": "tier_2",
                "min_amount": 1000,
                "max_amount": 10000,
                "required_approvers": ["manager", "finance"],
                "sla_hours": 48,
            },
            {
                "tier_name": "tier_3",
                "min_amount": 10000,
                "max_amount": None,
                "required_approvers": ["manager", "finance", "director"],
                "sla_hours": 72,
            },
        ]
        # Should not raise
        _validate_spend_tiers(tiers)

    def test_gap_in_tiers_raises_400(self):
        tiers = [
            {
                "tier_name": "tier_1",
                "min_amount": 0,
                "max_amount": 1000,
                "required_approvers": ["manager"],
                "sla_hours": 24,
            },
            {
                "tier_name": "tier_2",
                "min_amount": 1500,  # GAP: 1000 to 1500
                "max_amount": 10000,
                "required_approvers": ["finance"],
                "sla_hours": 48,
            },
        ]
        with pytest.raises(HTTPException) as exc:
            _validate_spend_tiers(tiers)
        assert exc.value.status_code == 400
        assert "contiguous" in exc.value.detail

    def test_overlap_in_tiers_raises_400(self):
        tiers = [
            {
                "tier_name": "tier_1",
                "min_amount": 0,
                "max_amount": 2000,
                "required_approvers": ["manager"],
                "sla_hours": 24,
            },
            {
                "tier_name": "tier_2",
                "min_amount": 1000,  # OVERLAP: starts before 2000
                "max_amount": 10000,
                "required_approvers": ["finance"],
                "sla_hours": 48,
            },
        ]
        with pytest.raises(HTTPException) as exc:
            _validate_spend_tiers(tiers)
        assert exc.value.status_code == 400
        assert "contiguous" in exc.value.detail

    def test_empty_approvers_raises_400(self):
        tiers = [
            {
                "tier_name": "tier_1",
                "min_amount": 0,
                "max_amount": 1000,
                "required_approvers": [],
                "sla_hours": 24,
            }
        ]
        with pytest.raises(HTTPException) as exc:
            _validate_spend_tiers(tiers)
        assert exc.value.status_code == 400
        assert "at least one" in exc.value.detail


@pytest.mark.asyncio
class TestRuleValueBoundsAndCrossField:
    async def test_numeric_bounds_violation_raises_400(self):
        mock_db = AsyncMock()
        rule = BusinessRule(
            rule_key="approval.auto_approve_max_amount",
            value_type="currency",
            min_value=0.0,
            max_value=50000.0,
            current_value=5000.0,
        )
        with pytest.raises(HTTPException) as exc:
            await _validate_rule_value(mock_db, rule, 75000.0)
        assert exc.value.status_code == 400
        assert "above maximum" in exc.value.detail

    async def test_petty_cash_greater_than_standard_raises_400(self):
        rule_petty = BusinessRule(
            rule_key="vendor.petty_tier_max_amount",
            value_type="currency",
            min_value=0.0,
            max_value=100000.0,
            current_value=500.0,
        )
        rule_standard = BusinessRule(
            rule_key="vendor.standard_tier_max_amount",
            value_type="currency",
            current_value=5000.0,
        )

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=rule_standard))))
        )

        with pytest.raises(HTTPException) as exc:
            await _validate_rule_value(mock_db, rule_petty, 6000.0)  # 6000 > 5000
        assert exc.value.status_code == 400
        assert "strictly less than" in exc.value.detail

    async def test_anomaly_watch_threshold_greater_than_anomalous_raises_400(self):
        rule_watch = BusinessRule(
            rule_key="license.anomaly_watch_threshold",
            value_type="float",
            min_value=0.0,
            max_value=1.0,
            current_value=0.6,
        )
        rule_anom = BusinessRule(
            rule_key="license.anomaly_anomalous_threshold",
            value_type="float",
            current_value=0.8,
        )

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=rule_anom))))
        )

        with pytest.raises(HTTPException) as exc:
            await _validate_rule_value(mock_db, rule_watch, 0.85)  # 0.85 >= 0.8
        assert exc.value.status_code == 400
        assert "strictly less than" in exc.value.detail


@pytest.mark.asyncio
class TestPatchAndResetEndpoints:
    async def test_empty_justification_rejects_with_400(self):
        mock_db = AsyncMock()
        user = MagicMock()
        user.email = "admin@example.com"
        user.id = "admin-1"

        payload = RulePatchRequest(new_value=1000.0, justification="")
        with pytest.raises(HTTPException) as exc:
            await patch_business_rule("approval.auto_approve_max_amount", payload, current_user=user, db=mock_db)
        assert exc.value.status_code == 400
        assert "Justification is required" in exc.value.detail

    async def test_patch_updates_value_and_records_history(self):
        mock_db = AsyncMock()
        user = MagicMock()
        user.email = "admin@example.com"
        user.id = "admin-1"

        rule = BusinessRule(
            id="rule-1",
            rule_key="approval.auto_approve_max_amount",
            category="approval",
            display_name="Auto Approve Max",
            description="Threshold",
            value_type="currency",
            current_value=5000.0,
            default_value=5000.0,
            min_value=0.0,
            max_value=50000.0,
        )
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=rule))))
        )
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_db.add = MagicMock()

        payload = RulePatchRequest(new_value=7500.0, justification="Quarterly policy adjustment approved by VP")

        with patch("app.api.business_rules.publish_business_rule_updated", new_callable=AsyncMock) as mock_pub:
            resp = await patch_business_rule("approval.auto_approve_max_amount", payload, current_user=user, db=mock_db)

            assert resp["data"]["current_value"] == 7500.0
            assert mock_db.commit.called
            mock_pub.assert_awaited_once()

            # Verify history record added
            added_history = [call.args[0] for call in mock_db.add.call_args_list if isinstance(call.args[0], BusinessRuleHistory)]
            assert len(added_history) == 1
            assert added_history[0].old_value == 5000.0
            assert added_history[0].new_value == 7500.0
            assert added_history[0].justification == "Quarterly policy adjustment approved by VP"

    async def test_reset_restores_default_value(self):
        mock_db = AsyncMock()
        user = MagicMock()
        user.email = "admin@example.com"
        user.id = "admin-1"

        rule = BusinessRule(
            id="rule-1",
            rule_key="approval.auto_approve_max_amount",
            category="approval",
            display_name="Auto Approve Max",
            description="Threshold",
            value_type="currency",
            current_value=12000.0,
            default_value=5000.0,
        )
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=rule))))
        )
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_db.add = MagicMock()

        payload = RuleResetRequest(justification="Reverting experimental threshold")

        with patch("app.api.business_rules.publish_business_rule_updated", new_callable=AsyncMock) as mock_pub:
            resp = await reset_business_rule("approval.auto_approve_max_amount", payload, current_user=user, db=mock_db)

            assert resp["data"]["current_value"] == 5000.0
            assert mock_db.commit.called
            mock_pub.assert_awaited_once()


class TestInternalAndRBAC:
    def test_internal_endpoint_rejects_missing_or_invalid_secret(self):
        client = TestClient(app)
        # Missing secret
        resp1 = client.get("/internal/business-rules")
        assert resp1.status_code == 403

        # Wrong secret
        resp2 = client.get("/internal/business-rules", headers={"X-Internal-Service-Secret": "wrong-secret"})
        assert resp2.status_code == 403

    def test_non_admin_token_forbidden_on_admin_endpoint(self):
        client = TestClient(app)
        user_token = create_access_token("user-1", "user@company.com", "requester")
        headers = {"Authorization": f"Bearer {user_token}"}

        resp = client.get("/admin/business-rules", headers=headers)
        assert resp.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("value,ok", [([], True), (["extraction"], True), (["extraction", "clauses"], True),
                                      (["chatbot"], False), ("extraction", False)])
async def test_force_model_fallback_accepts_only_known_routers(value, ok):
    """FR-08: the demo switch only names routers that honour it."""
    rule = BusinessRule(rule_key="dev.force_model_fallback", value_type="json", min_value=None, max_value=None,
                        current_value=[])
    if ok:
        await _validate_rule_value(AsyncMock(), rule, value)
    else:
        with pytest.raises(HTTPException) as exc:
            await _validate_rule_value(AsyncMock(), rule, value)
        assert exc.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("value,ok", [("allow", True), ("finance_approval", True), ("block", True),
                                      ("deny", False), (True, False)])
async def test_no_budget_policy_accepts_only_known_policies(value, ok):
    """Phase 1 budgets: a typo would silently behave like 'allow'."""
    rule = BusinessRule(rule_key="budget.no_budget_policy", value_type="json", min_value=None, max_value=None,
                        current_value="allow")
    if ok:
        await _validate_rule_value(AsyncMock(), rule, value)
    else:
        with pytest.raises(HTTPException) as exc:
            await _validate_rule_value(AsyncMock(), rule, value)
        assert exc.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("value,ok", [([30, 7], True), ([1], True), ([], False), ([0], False), ([400], False),
                                      (["30"], False), (30, False)])
async def test_obligation_reminder_days_must_be_whole_days(value, ok):
    """Phase 2 obligations: the sweep ignores anything that isn't a whole day."""
    rule = BusinessRule(rule_key="contract.obligation_reminder_days", value_type="json", min_value=None,
                        max_value=None, current_value=[30, 7])
    if ok:
        await _validate_rule_value(AsyncMock(), rule, value)
    else:
        with pytest.raises(HTTPException) as exc:
            await _validate_rule_value(AsyncMock(), rule, value)
        assert exc.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("value,ok", [
    ({"price": 0.45, "lead_time": 0.15, "warranty": 0.1, "support": 0.1, "vendor_risk": 0.1, "delivery_record": 0.1}, True),
    ({"price": 1}, True), ({"price": 0.5, "lead_time": 0.4}, False), ({"price": 0.5, "colour": 0.5}, False),
    ({"price": 1.5, "lead_time": -0.5}, False), ({}, False), ([1], False), ({"price": True}, False)])
async def test_sourcing_criteria_must_be_known_weights_summing_to_one(value, ok):
    """Phase 3 RFQs: scoring would silently fall back to defaults otherwise."""
    rule = BusinessRule(rule_key="sourcing.default_criteria", value_type="json", min_value=None,
                        max_value=None, current_value={"price": 1})
    if ok:
        await _validate_rule_value(AsyncMock(), rule, value)
    else:
        with pytest.raises(HTTPException) as exc:
            await _validate_rule_value(AsyncMock(), rule, value)
        assert exc.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("value,ok", [("risk-team@acme.test", True), ("", True), ("not-an-email", False),
                                      ("a@b.c, d@e.f", False), (["a@b.c"], False)])
async def test_risk_alert_recipients_is_one_address_or_empty(value, ok):
    rule = BusinessRule(rule_key="risk.alert_recipients", value_type="json", min_value=None, max_value=None,
                        current_value="x@y.z")
    if ok:
        await _validate_rule_value(AsyncMock(), rule, value)
    else:
        with pytest.raises(HTTPException) as exc:
            await _validate_rule_value(AsyncMock(), rule, value)
        assert exc.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("value,ok", [("29AAACA1234B1ZE", True), ("29aaaca1234b1ze", False), ("29AAACA1234B1Z", False),
                                      ("", False), (29, False)])
async def test_buyer_gstin_must_look_like_a_gstin(value, ok):
    """Phase 4: every invoice's GST check compares against it."""
    rule = BusinessRule(rule_key="gst.buyer_gstin", value_type="json", min_value=None, max_value=None,
                        current_value="29AAACA1234B1ZE")
    if ok:
        await _validate_rule_value(AsyncMock(), rule, value)
    else:
        with pytest.raises(HTTPException) as exc:
            await _validate_rule_value(AsyncMock(), rule, value)
        assert exc.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("value,ok", [({"hardware": "194Q", "saas": "194J(a)"}, True), ({}, True),
                                      ({"furniture": "194C"}, False), ({"saas": 194}, False), (["194Q"], False)])
async def test_tds_category_sections_are_codes_per_known_category(value, ok):
    rule = BusinessRule(rule_key="tds.category_sections", value_type="json", min_value=None, max_value=None,
                        current_value={})
    if ok:
        await _validate_rule_value(AsyncMock(), rule, value)
    else:
        with pytest.raises(HTTPException) as exc:
            await _validate_rule_value(AsyncMock(), rule, value)
        assert exc.value.status_code == 400
