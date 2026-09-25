"""IFSC bank-code validation tests.

All HTTP calls are mocked. Key requirement: 404 (IFSC not found) and
5xx/timeout (API unavailable) must produce DIFFERENT statuses — the service
never treats "couldn't reach the API" the same as "code doesn't exist".
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import httpx

from app.services.ifsc_service import validate_ifsc, IFSCStatus


class FakeResponse:
    def __init__(self, status_code: int, json_data: dict = None):
        self.status_code = status_code
        self._json = json_data or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=MagicMock(),
                response=MagicMock(status_code=self.status_code),
            )


class TestIFSCValidation:

    @pytest.mark.asyncio
    async def test_valid_ifsc_code_returns_valid(self):
        """A 200 response with bank data → IFSCStatus.VALID."""
        fake_data = {"BANK": "HDFC Bank", "BRANCH": "Mumbai Main", "ADDRESS": "123 Test St"}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=FakeResponse(200, fake_data))
            mock_client_cls.return_value = mock_client

            result = await validate_ifsc("HDFC0000001")

        assert result.status == IFSCStatus.VALID
        assert result.bank == "HDFC Bank"
        assert result.branch == "Mumbai Main"

    @pytest.mark.asyncio
    async def test_invalid_ifsc_code_returns_invalid(self):
        """A 404 response → IFSCStatus.INVALID (not pending).
        This is the key distinction: 404 = code genuinely doesn't exist."""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=FakeResponse(404))
            mock_client_cls.return_value = mock_client

            result = await validate_ifsc("XXXX0000000")

        assert result.status == IFSCStatus.INVALID
        assert "not found" in (result.error or "").lower() or "does not exist" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_api_5xx_returns_pending_not_invalid(self):
        """A 500 response → IFSCStatus.PENDING (NOT invalid).
        The API is down — we cannot conclude the IFSC doesn't exist."""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=FakeResponse(500))
            mock_client_cls.return_value = mock_client

            result = await validate_ifsc("HDFC0000001")

        assert result.status == IFSCStatus.PENDING
        # Must explicitly NOT be INVALID
        assert result.status != IFSCStatus.INVALID

    @pytest.mark.asyncio
    async def test_timeout_returns_pending(self):
        """A request timeout → IFSCStatus.PENDING (API unavailable)."""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
            mock_client_cls.return_value = mock_client

            result = await validate_ifsc("HDFC0000001")

        assert result.status == IFSCStatus.PENDING

    @pytest.mark.asyncio
    async def test_uppercase_normalization(self):
        """IFSC codes must be uppercased before lookup — lowercase 'hdfc0000001'
        would 404 as invalid even though 'HDFC0000001' is valid."""
        seen_urls = []

        async def fake_get(url, **kwargs):
            seen_urls.append(url)
            return FakeResponse(200, {"BANK": "Test", "BRANCH": "X", "ADDRESS": "Y"})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=fake_get)
            mock_client_cls.return_value = mock_client

            await validate_ifsc("hdfc0000001")

        assert seen_urls and "HDFC0000001" in seen_urls[0], \
            f"Expected uppercase IFSC in URL, got: {seen_urls}"

    @pytest.mark.asyncio
    async def test_empty_code_returns_invalid(self):
        result = await validate_ifsc("")
        assert result.status == IFSCStatus.INVALID
