import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.usage_service import UsageService

@pytest.mark.asyncio
class TestUsageReclaim:
    """Test license utilisation scoring and automatic reclaim triggering.
    
    When utilisation drops below 30% (configurable threshold),
    the system should automatically create a 'reclaim' purchase request.
    """
    
    async def test_high_utilisation_no_reclaim(self):
        """80% utilisation should NOT trigger a reclaim."""
        score = UsageService.compute_utilisation_score(
            total_seats=100,
            active_seats_30d=80
        )
        assert score == 0.8
        assert not UsageService.should_trigger_reclaim(score, threshold=0.3)
    
    async def test_low_utilisation_triggers_reclaim(self):
        """20% utilisation should trigger a reclaim."""
        score = UsageService.compute_utilisation_score(
            total_seats=100,
            active_seats_30d=20
        )
        assert score == 0.2
        assert UsageService.should_trigger_reclaim(score, threshold=0.3)
    
    async def test_zero_utilisation(self):
        """0% utilisation should definitely trigger a reclaim."""
        score = UsageService.compute_utilisation_score(
            total_seats=100,
            active_seats_30d=0
        )
        assert score == 0.0
        assert UsageService.should_trigger_reclaim(score, threshold=0.3)
    
    async def test_full_utilisation(self):
        """100% utilisation should NOT trigger a reclaim."""
        score = UsageService.compute_utilisation_score(
            total_seats=100,
            active_seats_30d=100
        )
        assert score == 1.0
        assert not UsageService.should_trigger_reclaim(score, threshold=0.3)
    
    async def test_boundary_utilisation(self):
        """Exactly at threshold should NOT trigger reclaim (only below)."""
        score = UsageService.compute_utilisation_score(
            total_seats=100,
            active_seats_30d=30
        )
        assert score == 0.3
        assert not UsageService.should_trigger_reclaim(score, threshold=0.3)
    
    async def test_zero_total_seats(self):
        """Zero total seats should return 0 utilisation without error."""
        score = UsageService.compute_utilisation_score(
            total_seats=0,
            active_seats_30d=0
        )
        assert score == 0.0
    
    async def test_warning_threshold(self):
        """40% utilisation should trigger warning but not reclaim."""
        score = UsageService.compute_utilisation_score(
            total_seats=100,
            active_seats_30d=40
        )
        assert UsageService.should_trigger_warning(score, threshold=0.5)
        assert not UsageService.should_trigger_reclaim(score, threshold=0.3)
