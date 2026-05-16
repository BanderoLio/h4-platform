"""Guardrails for URLs the worker will fetch from (git) or POST to (webhooks)."""

import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKLIST_HOSTNAMES = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
        "metadata",
        "metadata.google.internal",
    }
)


def _address_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_worker_fetch_url(url: str) -> None:
    """Reject URLs that target loopback, RFC1918, link-local, or metadata-style hosts.

    Used for repo and webhook URLs so the API and worker cannot be abused as SSRF proxies.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https")
    host = parsed.hostname
    if not host:
        raise ValueError("URL must include a host")
    h = host.lower().rstrip(".")
    if h in _BLOCKLIST_HOSTNAMES or h.endswith(".localhost") or h.endswith(".local"):
        raise ValueError("this host is not allowed")
    try:
        parsed_ip = ipaddress.ip_address(h)
    except ValueError:
        parsed_ip = None
    if parsed_ip is not None:
        if _address_blocked(parsed_ip):
            raise ValueError("this IP range is not allowed")
        return
    try:
        infos = socket.getaddrinfo(h, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("could not resolve host") from exc
    for info in infos:
        addr = info[4][0]
        try:
            resolved = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _address_blocked(resolved):
            raise ValueError("host resolves to a disallowed network")
