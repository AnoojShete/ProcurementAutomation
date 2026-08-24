"""Tests for spend-tier routing using exact Decimal amounts.

Rules from config.yaml:
- Up to ₹500: auto-approved, no approval chain
- ₹500-₹5,000: manager approval
- Above ₹5,000: manager + finance approval

Issue 5: All amounts are Decimal, not float, to eliminate
floating-point comparison bugs at tier boundaries.
"""
import pytest
import sys
import os
from decimal import Decimal
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.approval_service import ApprovalService

class TestSpendTierRouting:
    """Test that amounts are correctly routed to spend tiers."""
    
    def test_auto_approval_tier_small_amount(self):
        """Amounts <= ₹500 should be auto-approved."""
        tier, chain = ApprovalService.determine_spend_tier_static(Decimal("100"))
        assert tier == "auto"
        assert chain == []
    
    def test_auto_approval_tier_boundary(self):
        """Exactly ₹500 should be auto-approved."""
        tier, chain = ApprovalService.determine_spend_tier_static(Decimal("500"))
        assert tier == "auto"
        assert chain == []
    
    def test_manager_tier_lower_bound(self):
        """₹501 should require manager approval."""
        tier, chain = ApprovalService.determine_spend_tier_static(Decimal("501"))
        assert tier == "manager"
        assert chain == ["dept_manager"]
    
    def test_manager_tier_upper_bound(self):
        """₹5,000 should require manager approval."""
        tier, chain = ApprovalService.determine_spend_tier_static(Decimal("5000"))
        assert tier == "manager"
        assert chain == ["dept_manager"]
    
    def test_manager_finance_tier(self):
        """₹5,001 should require manager + finance approval."""
        tier, chain = ApprovalService.determine_spend_tier_static(Decimal("5001"))
        assert tier == "manager+finance"
        assert chain == ["dept_manager", "finance_head"]
    
    def test_large_amount_tier(self):
        """Very large amounts should require manager + finance."""
        tier, chain = ApprovalService.determine_spend_tier_static(Decimal("1000000"))
        assert tier == "manager+finance"
        assert chain == ["dept_manager", "finance_head"]
    
    def test_zero_amount(self):
        """Zero amount should be auto-approved."""
        tier, chain = ApprovalService.determine_spend_tier_static(Decimal("0"))
        assert tier == "auto"
        assert chain == []
    
    def test_approval_chain_order(self):
        """Manager must come before finance in the chain."""
        tier, chain = ApprovalService.determine_spend_tier_static(Decimal("10000"))
        assert len(chain) == 2
        assert chain[0] == "dept_manager"
        assert chain[1] == "finance_head"

    def test_float_boundary_edge_case(self):
        """Decimal('500.00') must NOT round-trip to 500.0000000001.
        
        This is the exact bug that Issue 5 eliminates — a float
        like 499.999999999 or 500.000000001 would misroute at the
        tier boundary.  With Decimal, 500.00 == 500.00 exactly.
        """
        tier, chain = ApprovalService.determine_spend_tier_static(Decimal("500.00"))
        assert tier == "auto"
        assert chain == []

        tier2, chain2 = ApprovalService.determine_spend_tier_static(Decimal("500.01"))
        assert tier2 == "manager"
        assert chain2 == ["dept_manager"]
