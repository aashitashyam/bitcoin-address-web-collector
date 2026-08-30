import httpx

from config import CRAWL
from crawler import robots, url_safety


def fetch_url(url: str) -> dict:
    """
    Always returns a dict with at least {"outcome": ..., "url": ..., "status": ...}.

    Possible outcomes:
      success             - "html" attached, "status" == 200
      unsafe_destination  - resolves to a private/internal/loopback address
      robots_disallowed   - robots.txt forbids fetching this URL
      non_html            - response content-type isn't text/html or text/plain
      rate_limited        - HTTP 429 (may include "retry_after_seconds")
      server_error        - HTTP 5xx
      http_error          - any other non-2xx status (e.g. 404, 403)
      request_error       - network-level failure (timeout, DNS, connection reset, ...)

    Never raises.
    """
    if CRAWL.block_private_ips and not url_safety.is_safe_url(url):
        return {"outcome": "unsafe_destination", "url": url, "status": None}

    if CRAWL.respect_robots_txt and not robots.can_fetch(url, CRAWL.user_agent):
        return {"outcome": "robots_disallowed", "url": url, "status": None}

    headers = {"User-Agent": CRAWL.user_agent}
    try:
        with httpx.Client(headers=headers, timeout=CRAWL.request_timeout, follow_redirects=True) as client:
            response = client.get(url)
    except httpx.HTTPError:
        return {"outcome": "request_error", "url": url, "status": None}

    status = response.status_code

    if status == 429:
        retry_after = response.headers.get("retry-after")
        retry_after_seconds = int(retry_after) if retry_after and retry_after.isdigit() else None
        return {
            "outcome": "rate_limited",
            "url": url,
            "status": status,
            "retry_after_seconds": retry_after_seconds,
        }

    if 500 <= status < 600:
        return {"outcome": "server_error", "url": url, "status": status}

    if status != 200:
        return {"outcome": "http_error", "url": url, "status": status}

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type and "text/plain" not in content_type:
        return {"outcome": "non_html", "url": url, "status": status}

    return {
        "outcome": "success",
        "url": str(response.url),
        "status": status,
        "html": response.text,
    }
