import hashlib
import time
from datetime import datetime, timezone

from bitcoin.extractor import extract_context, find_candidates
from bitcoin.validator import validate_address
from config import CRAWL
from crawler import url_safety
from crawler.classify import classify_source
from crawler.fetcher import fetch_url
from crawler.parser import extract_text_and_links
from database import repository as repo

_last_request_time: dict[str, float] = {}

_TRANSIENT_OUTCOMES = {"rate_limited", "server_error", "request_error"}


def _politeness_wait(domain: str) -> None:
    """Enforce a minimum delay between two requests to the same domain."""
    last = _last_request_time.get(domain, 0.0)
    elapsed = time.time() - last
    if elapsed < CRAWL.delay_between_requests:
        time.sleep(CRAWL.delay_between_requests - elapsed)
    _last_request_time[domain] = time.time()


def _new_stats() -> dict:
    return {
        "pages_crawled": 0,
        "pages_skipped": 0,
        "pages_failed": 0,
        "requests_total": 0,
        "robots_skipped": 0,
        "rate_limited": 0,
        "server_errors_or_timeouts": 0,
        "http_errors": 0,
        "unsafe_urls_rejected": 0,
        "candidates_found": 0,
        "valid_candidates": 0,
        "new_addresses": 0,
        "duplicate_observations": 0,
        "new_domains": 0,
        "links_enqueued": 0,
        "unexpected_errors": 0,
    }


def _process_one(conn, item: dict, max_depth: int, stats: dict) -> None:
    """Process a single queued URL. Raises on unexpected errors - the
    caller (run()) is responsible for catching those so one bad page
    can't take down the whole crawl."""
    url, depth, queue_id, attempts = item["url"], item["depth"], item["id"], item["attempts"]
    domain = repo.domain_of(url)

    _politeness_wait(domain)
    result = fetch_url(url)
    stats["requests_total"] += 1
    outcome = result["outcome"]

    if outcome == "unsafe_destination":
        stats["unsafe_urls_rejected"] += 1
        repo.finish_url(conn, queue_id, outcome=outcome, attempts=attempts)
        stats["pages_failed"] += 1
        return

    if outcome == "robots_disallowed":
        stats["robots_skipped"] += 1
        repo.finish_url(conn, queue_id, outcome=outcome, attempts=0)
        stats["pages_skipped"] += 1
        return

    if outcome == "non_html":
        repo.finish_url(conn, queue_id, outcome=outcome, attempts=0)
        stats["pages_skipped"] += 1
        return

    if outcome == "http_error":
        stats["http_errors"] += 1
        repo.finish_url(conn, queue_id, outcome=outcome, attempts=attempts)
        stats["pages_failed"] += 1
        return

    if outcome in _TRANSIENT_OUTCOMES:
        if outcome == "rate_limited":
            stats["rate_limited"] += 1
        else:
            stats["server_errors_or_timeouts"] += 1
        repo.finish_url(
            conn,
            queue_id,
            outcome=outcome,
            attempts=attempts + 1,
            retry_after_seconds=result.get("retry_after_seconds"),
        )
        stats["pages_skipped"] += 1
        return

    # outcome == "success"
    title, text, links = extract_text_and_links(result["html"], result["url"])
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    repo.upsert_page(conn, result["url"], content_hash, result["status"], len(links))

    source_type = classify_source(result["url"], title)
    candidates = find_candidates(text)
    stats["candidates_found"] += len(candidates)

    for candidate in candidates:
        validated = validate_address(candidate)
        if validated is None:
            continue
        stats["valid_candidates"] += 1
        context = extract_context(text, candidate)
        obs = repo.upsert_address_observation(
            conn,
            address=candidate,
            address_type=validated["type"],
            url=result["url"],
            page_title=title,
            context=context,
            content_hash=content_hash,
            source_type=source_type,
        )
        if obs["address_is_new"]:
            stats["new_addresses"] += 1
        else:
            stats["duplicate_observations"] += 1
        if obs["domain_is_new"]:
            stats["new_domains"] += 1

    if depth < max_depth:
        for link in links:
            if CRAWL.block_private_ips and not url_safety.is_safe_url(link):
                stats["unsafe_urls_rejected"] += 1
                continue
            repo.enqueue_url(conn, link, depth=depth + 1)
            stats["links_enqueued"] += 1

    repo.finish_url(conn, queue_id, outcome="success", attempts=0)
    stats["pages_crawled"] += 1


def run(conn, max_pages: int = 100, max_depth: int | None = None) -> dict:
    max_depth = CRAWL.max_depth if max_depth is None else max_depth
    started_at = datetime.now(timezone.utc)
    stats = _new_stats()

    for _ in range(max_pages):
        item = repo.get_next_url(conn)
        if item is None:
            break  # queue is empty, or everything is on cooldown/backoff

        try:
            _process_one(conn, item, max_depth, stats)
        except Exception:
            # A single bad page (parser bug, unexpected encoding, DB
            # hiccup on one insert, ...) must never kill the whole run.
            # Roll back whatever this page's processing left half-done,
            # record it as a retryable failure, and move on.
            conn.rollback()
            stats["unexpected_errors"] += 1
            try:
                repo.finish_url(
                    conn,
                    item["id"],
                    outcome="request_error",
                    attempts=item["attempts"] + 1,
                )
            except Exception:
                conn.rollback()

    repo.record_crawl_run(conn, started_at, stats)
    return stats
