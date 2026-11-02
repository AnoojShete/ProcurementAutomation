"""Safe outbound HTTP client preventing SSRF and unsafe consumption (OWASP API7 / API10).

Features:
- Schemes: http and https only
- Ports: 80 and 443 only
- No userinfo (user:pass@host)
- IP filtering: blocks loopback, private RFC 1918, link-local, cloud metadata
  (169.254.169.254), CGNAT, unique-local, multicast, and reserved ranges for IPv4/IPv6.
- Handles decimal, hex, and octal encoded IP notations.
- Connects directly to the resolved pinned IP to defeat DNS rebinding.
- Re-validates every redirect hop (at most 2 redirects allowed).
- Enforces timeouts, maximum response size (1 MB default), and project User-Agent.
"""
import ipaddress
import logging
import socket
from typing import Optional, Tuple
from urllib.parse import urlparse, urljoin

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "ProcurementAutomation-SafeFetch/1.0 (+https://procurement.local)"
DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_BYTES = 1024 * 1024  # 1 MB
MAX_REDIRECTS = 2

# IP ranges blocked unconditionally
BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),       # CGNAT
    ipaddress.ip_network("127.0.0.0/8"),        # Loopback IPv4
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local & cloud metadata
    ipaddress.ip_network("172.16.0.0/12"),      # Private RFC 1918
    ipaddress.ip_network("192.0.0.0/24"),       # IETF protocol assignments
    ipaddress.ip_network("192.0.2.0/24"),       # TEST-NET-1
    ipaddress.ip_network("192.168.0.0/16"),     # Private RFC 1918
    ipaddress.ip_network("198.18.0.0/15"),      # Benchmark testing
    ipaddress.ip_network("198.51.100.0/24"),    # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),     # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),        # Multicast
    ipaddress.ip_network("240.0.0.0/4"),        # Reserved
    ipaddress.ip_network("255.255.255.255/32"), # Broadcast
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),            # Loopback IPv6
    ipaddress.ip_network("::ffff:0:0/96"),      # IPv4-mapped IPv6
    ipaddress.ip_network("100::/64"),           # Discard prefix
    ipaddress.ip_network("64:ff9b::/96"),       # IPv4/IPv6 translation
    ipaddress.ip_network("2001::/32"),          # TEREDO
    ipaddress.ip_network("2001:db8::/32"),      # Documentation IPv6
    ipaddress.ip_network("fc00::/7"),           # Unique-local IPv6
    ipaddress.ip_network("fe80::/10"),          # Link-local IPv6
    ipaddress.ip_network("ff00::/8"),           # Multicast IPv6
]


class SSRFSecurityError(ValueError):
    """Raised when an outbound URL violates SSRF defense policies."""
    pass


def parse_and_validate_ip(ip_str: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Parse string or integer-based representations into an IP address object."""
    # Handle pure integer strings (decimal-encoded IPs, e.g. 2130706433 -> 127.0.0.1)
    if ip_str.isdigit():
        try:
            return ipaddress.IPv4Address(int(ip_str))
        except Exception as e:
            raise SSRFSecurityError(f"Invalid integer-encoded IP: {ip_str}") from e

    # Handle standard IP representations
    try:
        return ipaddress.ip_address(ip_str)
    except ValueError:
        pass

    # Check for hex representation (e.g. 0x7f000001)
    if ip_str.startswith("0x") or ip_str.startswith("0X"):
        try:
            return ipaddress.IPv4Address(int(ip_str, 16))
        except Exception as e:
            raise SSRFSecurityError(f"Invalid hex-encoded IP: {ip_str}") from e

    raise ValueError(f"Not an IP literal: {ip_str}")


def is_ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if the given IP address falls into any restricted network range."""
    # Convert IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1) to IPv4
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped

    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True

    for net in BLOCKED_NETWORKS:
        if ip in net:
            return True

    return False


def resolve_and_verify_host(hostname: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Resolve hostname via DNS and ensure all resolved IP addresses are safe."""
    # Check if host is already an IP literal (including decimal/hex)
    try:
        ip = parse_and_validate_ip(hostname)
        if is_ip_blocked(ip):
            raise SSRFSecurityError(f"Destination IP {ip} is in a blocked network range")
        return ip
    except ValueError:
        # Not an IP literal, proceed to DNS resolution
        pass

    try:
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise SSRFSecurityError(f"DNS resolution failed for host {hostname!r}: {e}") from e

    if not addr_info:
        raise SSRFSecurityError(f"No DNS records found for host {hostname!r}")

    safe_ip: Optional[ipaddress.IPv4Address | ipaddress.IPv6Address] = None
    for family, _, _, _, sockaddr in addr_info:
        raw_ip = sockaddr[0]
        ip = ipaddress.ip_address(raw_ip)
        if is_ip_blocked(ip):
            raise SSRFSecurityError(f"Host {hostname!r} resolved to blocked IP {ip}")
        if safe_ip is None:
            safe_ip = ip

    if safe_ip is None:
        raise SSRFSecurityError(f"Unable to resolve a safe IP for {hostname!r}")

    return safe_ip


def validate_url(url: str) -> Tuple[str, str, int, ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Validate URL scheme, ports, credentials, and resolve IP.
    Returns (scheme, hostname, port, resolved_ip).
    """
    parsed = urlparse(url)

    if parsed.scheme.lower() not in ("http", "https"):
        raise SSRFSecurityError(f"Scheme {parsed.scheme!r} not permitted; only http and https are allowed")

    if parsed.username or parsed.password:
        raise SSRFSecurityError("URLs containing embedded credentials (userinfo) are forbidden")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFSecurityError("URL must contain a valid hostname")

    port = parsed.port
    if port is None:
        port = 80 if parsed.scheme.lower() == "http" else 443

    if port not in (80, 443):
        raise SSRFSecurityError(f"Port {port} is not permitted; only ports 80 and 443 are allowed")

    resolved_ip = resolve_and_verify_host(hostname)
    return parsed.scheme.lower(), hostname, port, resolved_ip


def safe_fetch(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> httpx.Response:
    """Fetch an outbound URL safely, enforcing all SSRF and DoS protections.
    Follows redirects manually up to MAX_REDIRECTS, re-validating each hop.
    """
    current_url = url
    req_headers = dict(headers or {})
    req_headers.setdefault("User-Agent", USER_AGENT)

    for redirect_count in range(MAX_REDIRECTS + 1):
        scheme, hostname, port, resolved_ip = validate_url(current_url)

        # Pin the connection to the verified IP to defeat DNS rebinding.
        # We rewrite the request host to the resolved IP literal and supply the original Host header.
        ip_str = f"[{resolved_ip}]" if isinstance(resolved_ip, ipaddress.IPv6Address) else str(resolved_ip)
        parsed = urlparse(current_url)
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"

        connect_url = f"{scheme}://{ip_str}:{port}{path}"
        host_header = hostname if (port in (80, 443)) else f"{hostname}:{port}"
        req_headers["Host"] = host_header

        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            verify=True,
        ) as client:
            try:
                # Stream the response to enforce the size cap before reading the whole body
                with client.stream(method, connect_url, headers=req_headers) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise SSRFSecurityError("Redirect received without Location header")
                        if redirect_count >= MAX_REDIRECTS:
                            raise SSRFSecurityError(f"Exceeded maximum allowed redirects ({MAX_REDIRECTS})")
                        current_url = urljoin(current_url, location)
                        continue

                    # Read up to max_bytes + 1 to detect oversize payloads
                    chunks = []
                    bytes_read = 0
                    for chunk in response.iter_bytes():
                        bytes_read += len(chunk)
                        if bytes_read > max_bytes:
                            raise SSRFSecurityError(
                                f"Response exceeded maximum allowed size of {max_bytes} bytes"
                            )
                        chunks.append(chunk)

                    body = b"".join(chunks)
                    response.read()  # Complete response consumption
                    # Reconstruct standard response with validated body
                    return httpx.Response(
                        status_code=response.status_code,
                        headers=response.headers,
                        content=body,
                        request=response.request,
                    )
            except httpx.RequestError as e:
                raise SSRFSecurityError(f"Outbound request failed: {e}") from e

    raise SSRFSecurityError("Unexpected termination of safe fetch loop")
