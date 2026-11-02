"""Tests for SSRF and safe outbound HTTP client (OWASP API7, API10)."""
import ipaddress
import socket
import pytest
from unittest.mock import patch, MagicMock

from shared.net.safe_http import (
    parse_and_validate_ip,
    is_ip_blocked,
    resolve_and_verify_host,
    validate_url,
    safe_fetch,
    SSRFSecurityError,
)


def test_ip_blocking_private_and_loopback():
    assert is_ip_blocked(ipaddress.ip_address("127.0.0.1"))
    assert is_ip_blocked(ipaddress.ip_address("127.0.0.2"))
    assert is_ip_blocked(ipaddress.ip_address("10.0.1.5"))
    assert is_ip_blocked(ipaddress.ip_address("172.16.0.1"))
    assert is_ip_blocked(ipaddress.ip_address("172.31.255.255"))
    assert is_ip_blocked(ipaddress.ip_address("192.168.1.1"))
    assert is_ip_blocked(ipaddress.ip_address("169.254.169.254"))  # Cloud metadata
    assert is_ip_blocked(ipaddress.ip_address("0.0.0.0"))
    assert is_ip_blocked(ipaddress.ip_address("255.255.255.255"))
    # IPv6
    assert is_ip_blocked(ipaddress.ip_address("::1"))
    assert is_ip_blocked(ipaddress.ip_address("fc00::1"))
    assert is_ip_blocked(ipaddress.ip_address("fe80::1"))
    # IPv4-mapped IPv6
    assert is_ip_blocked(ipaddress.ip_address("::ffff:127.0.0.1"))
    assert is_ip_blocked(ipaddress.ip_address("::ffff:169.254.169.254"))

    # Public IP should not be blocked
    assert not is_ip_blocked(ipaddress.ip_address("93.184.216.34"))
    assert not is_ip_blocked(ipaddress.ip_address("8.8.8.8"))


def test_parse_encoded_ips():
    # Decimal 2130706433 is 127.0.0.1
    ip_dec = parse_and_validate_ip("2130706433")
    assert str(ip_dec) == "127.0.0.1"
    assert is_ip_blocked(ip_dec)

    # Decimal 2852039166 is 169.254.169.254
    ip_meta = parse_and_validate_ip("2852039166")
    assert str(ip_meta) == "169.254.169.254"
    assert is_ip_blocked(ip_meta)

    # Hex 0x7f000001 is 127.0.0.1
    ip_hex = parse_and_validate_ip("0x7f000001")
    assert str(ip_hex) == "127.0.0.1"
    assert is_ip_blocked(ip_hex)


def test_validate_url_schemes():
    with pytest.raises(SSRFSecurityError, match="Scheme 'ftp' not permitted"):
        validate_url("ftp://example.com/file")

    with pytest.raises(SSRFSecurityError, match="Scheme 'file' not permitted"):
        validate_url("file:///etc/passwd")

    with pytest.raises(SSRFSecurityError, match="Scheme 'gopher' not permitted"):
        validate_url("gopher://example.com/")


def test_validate_url_ports():
    with pytest.raises(SSRFSecurityError, match="Port 22 is not permitted"):
        validate_url("http://example.com:22/test")

    with pytest.raises(SSRFSecurityError, match="Port 8080 is not permitted"):
        validate_url("https://example.com:8080/test")


def test_validate_url_credentials_forbidden():
    with pytest.raises(SSRFSecurityError, match="URLs containing embedded credentials"):
        validate_url("http://admin:secret@example.com/")


def test_dns_resolution_blocks_private_ips():
    # Mock socket.getaddrinfo to return 127.0.0.1
    with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]):
        with pytest.raises(SSRFSecurityError, match="resolved to blocked IP"):
            resolve_and_verify_host("evil.com")


def test_dns_resolution_blocks_metadata():
    with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))]):
        with pytest.raises(SSRFSecurityError, match="resolved to blocked IP"):
            resolve_and_verify_host("metadata.internal")


def test_dns_resolution_succeeds_for_public_ip():
    with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]):
        ip = resolve_and_verify_host("example.com")
        assert str(ip) == "93.184.216.34"


def test_safe_fetch_blocks_redirect_to_private():
    # First request returns 302 to http://127.0.0.1/admin
    mock_resp_1 = MagicMock()
    mock_resp_1.is_redirect = True
    mock_resp_1.headers = {"location": "http://127.0.0.1/admin"}

    with patch("shared.net.safe_http.validate_url") as mock_validate:
        # First call succeeds as public IP
        mock_validate.side_effect = [
            ("http", "example.com", 80, ipaddress.ip_address("93.184.216.34")),
            SSRFSecurityError("Destination IP 127.0.0.1 is in a blocked network range")
        ]
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_stream_ctx = MagicMock()
            mock_stream_ctx.__enter__.return_value = mock_resp_1
            mock_client.stream.return_value = mock_stream_ctx

            with pytest.raises(SSRFSecurityError, match="blocked network range"):
                safe_fetch("http://example.com/redirect")


def test_safe_fetch_enforces_max_bytes():
    mock_resp = MagicMock()
    mock_resp.is_redirect = False
    # Return 2 chunks of 600 bytes when max_bytes is 1000
    mock_resp.iter_bytes.return_value = [b"a" * 600, b"b" * 600]

    with patch("shared.net.safe_http.validate_url", return_value=("http", "example.com", 80, ipaddress.ip_address("93.184.216.34"))):
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_stream_ctx = MagicMock()
            mock_stream_ctx.__enter__.return_value = mock_resp
            mock_client.stream.return_value = mock_stream_ctx

            with pytest.raises(SSRFSecurityError, match="exceeded maximum allowed size"):
                safe_fetch("http://example.com/large", max_bytes=1000)
