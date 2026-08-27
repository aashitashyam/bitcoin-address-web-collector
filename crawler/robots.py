"""
robots.txt compliance, with per-domain caching so we don't refetch it
on every single page request.
"""

import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

_CACHE_TTL_SECONDS = 3600
_cache: dict[str, tuple[RobotFileParser, float]] = {}


def _robots_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/robots.txt"


def _fetch_parser(url: str, user_agent: str) -> RobotFileParser:
    rp = RobotFileParser()
    try:
        resp = httpx.get(_robots_url(url), timeout=10, headers={"User-Agent": user_agent})
        if resp.status_code == 200:
            rp.parse(resp.text.splitlines())
        else:
            # No robots.txt (404, etc) - treat as "allow all", per convention.
            rp.parse([])
    except httpx.HTTPError:
        rp.parse([])
    return rp


def can_fetch(url: str, user_agent: str) -> bool:
    domain = urlparse(url).netloc
    now = time.time()
    cached = _cache.get(domain)
    if cached is None or (now - cached[1]) > _CACHE_TTL_SECONDS:
        rp = _fetch_parser(url, user_agent)
        _cache[domain] = (rp, now)
    else:
        rp = cached[0]
    return rp.can_fetch(user_agent, url)
