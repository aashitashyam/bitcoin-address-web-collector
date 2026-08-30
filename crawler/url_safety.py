"""
Rejects URLs that resolve to internal/private network destinations, so a
page discovered anywhere on the public web can't trick the crawler into
making requests against localhost, a private LAN, link-local addresses,
etc. 

Standard SSRF risk for any crawler that follows arbitrary links it didn't 
choose itself.

Resolution results are cached per-hostname for a while (same pattern as
crawler/robots.py's robots.txt cache), since one page can link to dozens
of URLs on a handful of domains and re-resolving every single link would
be wasteful.

**Limitation: this checks the destination at discovery/fetch time,
not at the moment the TCP connection is actually opened, so it does not
protect against DNS rebinding (a hostname that resolves safely now but
to a private IP by the time it's actually connected to). Closing that
fully means resolving right at the socket layer, which is a bigger change
than this version makes.--FUTURE WORK--
"""

from __future__ import annotations

import ipaddress
import socket
import time
from urllib.parse import urlparse

_CACHE_TTL_SECONDS = 3600
_cache: dict[str, tuple[bool, float]] = {}


def _is_unsafe_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # can't parse it - fail closed
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve_is_safe(hostname: str) -> bool:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False  # can't resolve it - fail closed
    resolved_ips = {info[4][0] for info in infos}
    if not resolved_ips:
        return False
    return not any(_is_unsafe_ip(ip) for ip in resolved_ips)


def is_safe_url(url: str) -> bool:
    """
    False for anything that isn't a plain http/https URL pointing at a
    public, resolvable hostname. Fails closed - DNS errors or anything
    unparseable count as unsafe rather than being let through.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme not in ("http", "https"):
        return False
    if not parsed.hostname:
        return False

    hostname = parsed.hostname.lower()
    if hostname == "localhost":
        return False

    now = time.time()
    cached = _cache.get(hostname)
    if cached is not None and (now - cached[1]) <= _CACHE_TTL_SECONDS:
        return cached[0]

    result = _resolve_is_safe(hostname)
    _cache[hostname] = (result, now)
    return result
