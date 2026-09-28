import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.approval_service import ApprovalService

class TestSpendTierRouting:
    """Test that amounts are correctly routed to spend tiers.
    
    Rules from config.yaml:
    - Up to ₹500: auto-approved, no approval chain
    - ₹500-₹5,000: manager approval
    - Above ₹5,000: manager + finance approval
    """
    
    def test_auto_approval_tier_small_amount(self):
        """Amounts <= ₹500 should be auto-approved."""
        tier, chain = ApprovalService.determine_spend_tier_static(100.0)
        assert tier == "auto"
        assert chain == []
    
    def test_auto_approval_tier_boundary(self):
        """Exactly ₹500 should be auto-approved."""
        tier, chain = ApprovalService.determine_spend_tier_static(500.0)
        assert tier == "auto"
        assert chain == []
    
    def test_manager_tier_lower_bound(self):
        """₹501 should require manager approval."""
        tier, chain = ApprovalService.determine_spend_tier_static(501.0)
        assert tier == "manager"
        assert chain == ["dept_manager"]
    
    def test_manager_tier_upper_bound(self):
        """₹5,000 should require manager approval."""
        tier, chain = ApprovalService.determine_spend_tier_static(5000.0)
        assert tier == "manager"
        assert chain == ["dept_manager"]
    
    def test_manager_finance_tier(self):
        """₹5,001 should require manager + finance approval."""
        tier, chain = ApprovalService.determine_spend_tier_static(5001.0)
        assert tier == "manager+finance"
        assert chain == ["dept_manager", "finance_head"]
    
    def test_large_amount_tier(self):
        """Very large amounts should require manager + finance."""
        tier, chain = ApprovalService.determine_spend_tier_static(1000000.0)
        assert tier == "manager+finance"
        assert chain == ["dept_manager", "finance_head"]
    
    def test_zero_amount(self):
        """Zero amount should be auto-approved."""
        tier, chain = ApprovalService.determine_spend_tier_static(0.0)
        assert tier == "auto"
        assert chain == []
    
    def test_approval_chain_order(self):
        """Manager must come before finance in the chain."""
        tier, chain = ApprovalService.determine_spend_tier_static(10000.0)
        assert len(chain) == 2
        assert chain[0] == "dept_manager"
        assert chain[1] == "finance_head"

    def test_dynamic_spend_tiers_from_rules_engine(self):
        """Dynamic spend tiers override defaults when configured in rules engine."""
        from unittest.mock import patch

        custom_tiers = [
            {"tier_name": "micro", "min_amount": 0, "max_amount": 200, "required_roles": []},
            {"tier_name": "lead", "min_amount": 200, "max_amount": 2000, "required_roles": ["team_lead"]},
            {"tier_name": "director_approval", "min_amount": 2000, "max_amount": 20000, "required_roles": ["team_lead", "director"]},
            {"tier_name": "executive_cfo", "min_amount": 20000, "max_amount": None, "required_roles": ["team_lead", "director", "cfo"]},
        ]

        with patch("shared.rules_engine.get_rule", return_value=custom_tiers):
            tier, chain = ApprovalService.determine_spend_tier_static(150.0)
            assert tier == "micro"
            assert chain == []

            tier, chain = ApprovalService.determine_spend_tier_static(1500.0)
            assert tier == "lead"
            assert chain == ["team_lead"]

            tier, chain = ApprovalService.determine_spend_tier_static(5000.0)
            assert tier == "director_approval"
            assert chain == ["team_lead", "director"]

            tier, chain = ApprovalService.determine_spend_tier_static(50000.0)
            assert tier == "executive_cfo"
            assert chain == ["team_lead", "director", "cfo"]

