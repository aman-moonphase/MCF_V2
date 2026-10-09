"""Basic SSRF protection for server-side URL fetching (URL ingestion).

Strategy:
- only http/https, no embedded credentials;
- every address the hostname resolves to must be public (no loopback, private, link-local,
  carrier-grade NAT, multicast, reserved, or unspecified ranges — e.g. 127.0.0.1, 10.x, 169.254.169.254);
- redirects are followed manually and each hop is re-validated.

Known limitation: a DNS answer can change between validation and the actual connection
(DNS rebinding). Closing that gap needs connection-level pinning, which is out of scope here.
"""

import ipaddress
import socket
from typing import Callable
from urllib.parse import urljoin, urlsplit

import requests

MAX_REDIRECTS = 5
_ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURLError(ValueError):
    """The URL is not allowed to be fetched by the server."""


def _is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _resolve(hostname: str) -> list[str]:
    infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    return list({info[4][0] for info in infos})


def validate_public_url(url: str, *, allow_private: bool = False, resolver: Callable[[str], list[str]] = _resolve) -> str:
    """Raise UnsafeURLError unless `url` is an http(s) URL whose host resolves only to public addresses."""
    if not url or not isinstance(url, str):
        raise UnsafeURLError("A URL is required.")
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeURLError("Only http:// and https:// URLs can be ingested.")
    if parts.username or parts.password:
        raise UnsafeURLError("URLs with embedded credentials are not allowed.")
    hostname = parts.hostname
    if not hostname:
        raise UnsafeURLError("The URL has no hostname.")
    if allow_private:
        return url.strip()

    try:
        addresses = [hostname] if _is_ip_literal(hostname) else resolver(hostname)
    except (socket.gaierror, UnicodeError) as e:
        raise UnsafeURLError(f"Could not resolve host '{hostname}'.") from e
    if not addresses:
        raise UnsafeURLError(f"Could not resolve host '{hostname}'.")
    for address in addresses:
        if not _is_public_address(address):
            raise UnsafeURLError("URLs that point to private, local, or internal network addresses are not allowed.")
    return url.strip()


def _is_ip_literal(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        return False


def safe_get(url: str, *, timeout: float = 15, headers: dict | None = None, allow_private: bool = False) -> requests.Response:
    """GET a URL, validating the URL and every redirect target against SSRF rules."""
    current = validate_public_url(url, allow_private=allow_private)
    for _ in range(MAX_REDIRECTS + 1):
        response = requests.get(current, timeout=timeout, headers=headers, allow_redirects=False)
        if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("Location"):
            current = validate_public_url(urljoin(current, response.headers["Location"]), allow_private=allow_private)
            continue
        return response
    raise UnsafeURLError(f"Too many redirects (more than {MAX_REDIRECTS}).")
