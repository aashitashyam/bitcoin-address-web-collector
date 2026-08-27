import hashlib
import time

from bitcoin.extractor import extract_context, find_candidates
from bitcoin.validator import validate_address
from config import CRAWL
from crawler.classify import classify_source
from crawler.fetcher import fetch_url
from crawler.parser import extract_text_and_links
from database import repository as repo

_last_request_time: dict[str, float] = {}


def _politeness_wait(domain: str) -> None:
    """Enforce a minimum delay between two requests to the same domain."""
    last = _last_request_time.get(domain, 0.0)
    elapsed = time.time() - last
    if elapsed < CRAWL.delay_between_requests:
        time.sleep(CRAWL.delay_between_requests - elapsed)
    _last_request_time[domain] = time.time()


def run(conn, max_pages: int = 100, max_depth: int | None = None) -> dict:
    max_depth = CRAWL.max_depth if max_depth is None else max_depth
    stats = {"pages_crawled": 0, "pages_skipped": 0, "addresses_found": 0, "links_enqueued": 0}

    for _ in range(max_pages):
        item = repo.get_next_url(conn)
        if item is None:
            break  # queue is empty (or everything is on cooldown)

        url, depth, queue_id = item["url"], item["depth"], item["id"]
        domain = repo.domain_of(url)

        _politeness_wait(domain)
        result = fetch_url(url)

        if result.get("skipped"):
            repo.finish_url(conn, queue_id, "skipped", CRAWL.revisit_hours_default)
            stats["pages_skipped"] += 1
            continue

        title, text, links = extract_text_and_links(result["html"], result["url"])
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        repo.upsert_page(conn, result["url"], content_hash, result["status"], len(links))
        source_type = classify_source(result["url"], title)

        for candidate in find_candidates(text):
            validated = validate_address(candidate)
            if validated is None:
                continue
            context = extract_context(text, candidate)
            repo.upsert_address_observation(
                conn,
                address=candidate,
                address_type=validated["type"],
                url=result["url"],
                page_title=title,
                context=context,
                content_hash=content_hash,
                source_type=source_type,
            )
            stats["addresses_found"] += 1

        if depth < max_depth:
            for link in links:
                repo.enqueue_url(conn, link, depth=depth + 1)
                stats["links_enqueued"] += 1

        repo.finish_url(conn, queue_id, "done", CRAWL.revisit_hours_default)
        stats["pages_crawled"] += 1

    return stats
