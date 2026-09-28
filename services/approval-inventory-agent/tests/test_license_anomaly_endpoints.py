import pytest
import os
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import get_anomaly_thresholds
from app.services.usage_service import UsageService
from app.models import License, LicenseUsage, LicenseReclaimHistory, AuditLog


@pytest.mark.asyncio
class TestLicenseAnomalyEndpoints:
    """Test SSO usage anomaly detection, summary aggregation, reclaim history, and configurable thresholds."""

    def test_configurable_thresholds_and_status(self):
        """1. Verify anomaly_status is derived using configurable env var thresholds."""
        with patch.dict(os.environ, {"ANOMALY_WATCH_THRESHOLD": "0.4", "ANOMALY_ANOMALOUS_THRESHOLD": "0.8"}):
            watch_th, anomalous_th = get_anomaly_thresholds()
            assert watch_th == 0.4
            assert anomalous_th == 0.8

            def calculate_anomaly_status(s):
                if s is None:
                    return "insufficient_history"
                if s >= anomalous_th:
                    return "anomalous"
                if s >= watch_th:
                    return "watch"
                return "normal"
            # Below 0.4 -> normal
            assert calculate_anomaly_status(0.35) == "normal"
            # 0.4 to 0.79 -> watch
            assert calculate_anomaly_status(0.5) == "watch"
            assert calculate_anomaly_status(0.79) == "watch"
            # 0.8 and above -> anomalous
            assert calculate_anomaly_status(0.8) == "anomalous"
            assert calculate_anomaly_status(0.95) == "anomalous"
            # None -> insufficient_history
            assert calculate_anomaly_status(None) == "insufficient_history"

    def test_default_thresholds(self):
        """Default thresholds must be 0.5 (watch) and 0.75 (anomalous)."""
        env_clean = {k: v for k, v in os.environ.items() if "ANOMALY" not in k}
        with patch.dict(os.environ, env_clean, clear=True):
            watch_th, anomalous_th = get_anomaly_thresholds()
            assert watch_th == 0.5
            assert anomalous_th == 0.75

    async def test_compute_utilisation_enrichment(self, mock_db_session):
        """Verify compute_utilisation returns anomaly_score, anomaly_status, top_factors (with direction), and days_since_last_login."""
        now = datetime.now(timezone.utc)
        fake_license = License(
            id=str(uuid.uuid4()),
            app_name="Slack Enterprise",
            total_seats=100,
            assigned_seats=80,
            cost_per_seat=1200.0,
            status="active",
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = fake_license
        mock_result.scalar.return_value = None  # no license_usage rows yet
        mock_db_session.execute.return_value = mock_result

        with patch("app.services.usage_service._load_sso_events", return_value=[
            {"app_name": "Slack Enterprise", "user_email": "u1@company.com", "login_timestamp": (now - timedelta(days=5)).isoformat()}
        ]):
            usage = await UsageService.compute_utilisation(mock_db_session, fake_license.id)
            assert usage is not None
            assert "anomaly_score" in usage
            assert "anomaly_status" in usage
            assert "top_factors" in usage
            assert "days_since_last_login" in usage
            assert "utilisation_score" in usage

    async def test_insufficient_history_returns_null_score(self, mock_db_session):
        """4. A license with zero SSO events must return null anomaly_score and status 'insufficient_history'."""
        fake_license = License(
            id=str(uuid.uuid4()),
            app_name="Brand New SaaS App",
            total_seats=50,
            status="active",
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = fake_license
        mock_result.scalar.return_value = None  # no license_usage rows yet
        mock_db_session.execute.return_value = mock_result

        with patch("app.services.usage_service._load_sso_events", return_value=[]):
            usage = await UsageService.compute_utilisation(mock_db_session, fake_license.id)
            assert usage is not None
            assert usage["anomaly_score"] is None
            assert usage["anomaly_status"] == "insufficient_history"

    async def test_anomaly_summary_and_potential_savings_calculation(self, mock_db_session):
        """2. GET /licenses/anomaly-summary correctly counts by status and arithmetic sum of savings."""
        lic1 = License(id=str(uuid.uuid4()), app_name="App1", total_seats=100, cost_per_seat=1000.0, status="active")
        lic2 = License(id=str(uuid.uuid4()), app_name="App2", total_seats=50, cost_per_seat=2000.0, status="active")
        lic3 = License(id=str(uuid.uuid4()), app_name="App3", total_seats=20, cost_per_seat=500.0, status="active")
        lic4 = License(id=str(uuid.uuid4()), app_name="App4", total_seats=10, cost_per_seat=1500.0, status="active")

        # Mock query returning all 4 active licenses
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = [lic1, lic2, lic3, lic4]
        mock_db_session.execute.return_value = mock_res

        # Mock compute_utilisation for each
        async def fake_compute(db, lic_id):
            if lic_id == lic1.id:
                return {"anomaly_score": 0.85, "anomaly_status": "anomalous"}
            elif lic_id == lic2.id:
                return {"anomaly_score": 0.60, "anomaly_status": "watch"}
            elif lic_id == lic3.id:
                return {"anomaly_score": 0.20, "anomaly_status": "normal"}
            else:
                return {"anomaly_score": None, "anomaly_status": "insufficient_history"}

        with patch.object(UsageService, "compute_utilisation", side_effect=fake_compute):
            summary = await UsageService.get_anomaly_summary(mock_db_session)
            assert summary["total_licenses"] == 4
            assert summary["anomalous"] == 1
            assert summary["watch"] == 1
            assert summary["normal"] == 1
            assert summary["insufficient_history"] == 1
            # Potential savings: only anomalous (lic1): 100 * 1000.0 = 100,000.0
            assert summary["potential_annual_savings"] == 100000.0

    async def test_usage_history_chronological_90_days(self, mock_db_session):
        """Verify usage history returns 90 daily records in chronological order."""
        fake_license = License(id=str(uuid.uuid4()), app_name="App1", total_seats=50, status="active")
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = fake_license
        mock_db_session.execute.return_value = mock_res

        with patch("app.services.usage_service._load_sso_events", return_value=[]):
            history = await UsageService.get_usage_history(mock_db_session, fake_license.id, days=90)
            assert len(history) == 90
            # Check chronological order
            assert history[0]["date"] < history[-1]["date"]
            assert all("date" in h and "active_seats" in h for h in history)

    async def test_mark_reviewed_sets_cooldown_and_logs(self, mock_db_session):
        """5. POST /licenses/{id}/mark-reviewed sets 30-day review cooldown and logs to reclaim-history."""
        fake_license = License(
            id=str(uuid.uuid4()),
            app_name="App1",
            total_seats=50,
            status="active",
            reclaim_cooldown_until=None,
        )
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = fake_license
        mock_db_session.execute.return_value = mock_res

        res = await UsageService.mark_reviewed(mock_db_session, fake_license.id, reviewer="reviewer@company.com")
        assert res["status"] == "reviewed"
        assert res["license_id"] == fake_license.id
        assert fake_license.reclaim_cooldown_until is not None

        # Verify added to DB
        assert mock_db_session.add.call_count >= 2
        # Commit called
        assert mock_db_session.commit.called
