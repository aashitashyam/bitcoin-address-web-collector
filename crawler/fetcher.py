import httpx

from config import CRAWL
from crawler import robots


def fetch_url(url: str) -> dict:
    """
    Returns either:
      {"skipped": True, "reason": "...", "url": url}
    or:
      {"skipped": False, "url": final_url, "status": int, "html": str}
    Never raises - network/robots problems are reported, not thrown.
    """
    if CRAWL.respect_robots_txt and not robots.can_fetch(url, CRAWL.user_agent):
        return {"skipped": True, "reason": "disallowed_by_robots_txt", "url": url}

    headers = {"User-Agent": CRAWL.user_agent}
    try:
        with httpx.Client(headers=headers, timeout=CRAWL.request_timeout, follow_redirects=True) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        return {"skipped": True, "reason": f"request_error: {exc}", "url": url}

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type and "text/plain" not in content_type:
        return {"skipped": True, "reason": f"non_html_content_type: {content_type}", "url": url}

    if response.status_code != 200:
        return {"skipped": True, "reason": f"http_status_{response.status_code}", "url": url}

    return {
        "skipped": False,
        "url": str(response.url),
        "status": response.status_code,
        "html": response.text,
    }
