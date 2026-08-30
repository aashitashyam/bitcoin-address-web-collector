"""
All Database access here. 
Every function takes an open connection
so the caller controls transaction boundaries.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import psycopg

from config import CRAWL, DB

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def get_connection() -> psycopg.Connection:
    return psycopg.connect(DB.dsn)


def init_schema(conn: psycopg.Connection, schema_path: str | None = None) -> None:
    path = schema_path or _SCHEMA_PATH
    with open(path, "r", encoding="utf-8") as f:
        sql = f.read()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def domain_of(url: str) -> str:
    return urlparse(url).netloc.lower()


# ---------------- crawl queue ----------------

def enqueue_url(conn, url: str, depth: int = 0, priority: int = 0) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO crawl_queue (url, domain, depth, priority)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (url) DO NOTHING
            """,
            (url, domain_of(url), depth, priority),
        )
    conn.commit()


def get_next_url(conn) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, url, depth, attempts
            FROM crawl_queue
            WHERE status = 'pending' AND next_crawl <= NOW()
            ORDER BY priority DESC, next_crawl
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        )
        row = cur.fetchone()
        if not row:
            return None
        queue_id, url, depth, attempts = row
        cur.execute(
            "UPDATE crawl_queue SET status = 'processing' WHERE id = %s",
            (queue_id,),
        )
    conn.commit()
    return {"id": queue_id, "url": url, "depth": depth, "attempts": attempts}


_TRANSIENT_OUTCOMES = {"rate_limited", "server_error", "request_error"}
_PERMANENT_FAIL_OUTCOMES = {"http_error", "unsafe_destination"}


def finish_url(
    conn,
    queue_id: int,
    outcome: str,
    attempts: int = 0,
    retry_after_seconds: int | None = None,
) -> None:
    """
    outcome is one of: success, robots_disallowed, non_html, rate_limited,
    server_error, request_error, http_error, unsafe_destination.

    Scheduling:
      - success / robots_disallowed / non_html -> back to 'pending' after
        the normal revisit cooldown, attempts reset to 0.
      - rate_limited / server_error / request_error -> transient failure;
        back to 'pending' with exponential backoff (respecting a
        Retry-After header if the site sent one), unless attempts has
        exceeded the configured max, in which case it's marked 'failed'
        and won't be retried again.
      - http_error / unsafe_destination -> permanent failure, marked
        'failed' immediately. Retrying a 404 or a private-IP address
        won't help.
    """
    if outcome in _PERMANENT_FAIL_OUTCOMES:
        status, next_attempts, backoff_minutes = "failed", attempts, 0

    elif outcome in _TRANSIENT_OUTCOMES:
        next_attempts = attempts
        if next_attempts >= CRAWL.max_retry_attempts:
            status, backoff_minutes = "failed", 0
        else:
            status = "pending"
            backoff_minutes = min(
                CRAWL.retry_base_minutes * (2 ** max(next_attempts - 1, 0)),
                CRAWL.retry_max_hours * 60,
            )
            if retry_after_seconds:
                backoff_minutes = max(backoff_minutes, retry_after_seconds / 60)

    else:  # success, robots_disallowed, non_html
        status = "pending"
        next_attempts = 0
        backoff_minutes = CRAWL.revisit_hours_default * 60

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE crawl_queue
            SET status = %s,
                attempts = %s,
                last_outcome = %s,
                last_crawled = NOW(),
                next_crawl = NOW() + (%s || ' minutes')::interval
            WHERE id = %s
            """,
            (status, next_attempts, outcome, str(backoff_minutes), queue_id),
        )
    conn.commit()


# ---------------- pages ----------------

def upsert_page(conn, url: str, content_hash: str, http_status: int, links_found: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO crawled_pages (url, domain, content_hash, http_status, links_found)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (url) DO UPDATE SET
                last_crawled = NOW(),
                content_hash = EXCLUDED.content_hash,
                http_status  = EXCLUDED.http_status,
                links_found  = EXCLUDED.links_found
            """,
            (url, domain_of(url), content_hash, http_status, links_found),
        )
    conn.commit()


# ---------------- addresses ----------------

def upsert_address_observation(
    conn,
    address: str,
    address_type: str,
    url: str,
    page_title: str,
    context: str,
    content_hash: str,
    source_type: str = "unknown",
) -> dict:
    """
    Returns {"address_id": int, "address_is_new": bool, "domain_is_new": bool}.
    "is_new" is computed via Postgres's `xmax = 0` trick, which is true
    only when the row was actually INSERTed by this statement (not when
    an ON CONFLICT DO UPDATE touched an existing row).
    """
    domain = domain_of(url)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domains (domain)
            VALUES (%s)
            ON CONFLICT (domain) DO UPDATE SET last_seen = NOW()
            RETURNING id, (xmax = 0) AS is_new
            """,
            (domain,),
        )
        domain_id, domain_is_new = cur.fetchone()

        cur.execute(
            """
            INSERT INTO bitcoin_addresses (address, address_type, first_source_url, last_source_url, observation_count)
            VALUES (%s, %s, %s, %s, 1)
            ON CONFLICT (address) DO UPDATE SET
                last_seen          = NOW(),
                last_source_url    = EXCLUDED.last_source_url,
                observation_count  = bitcoin_addresses.observation_count + 1
            RETURNING id, (xmax = 0) AS is_new
            """,
            (address, address_type, url, url),
        )
        address_id, address_is_new = cur.fetchone()

        cur.execute(
            """
            INSERT INTO address_observations (address_id, url, domain, domain_id, page_title, source_type, context, content_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (address_id, url, domain, domain_id, page_title, source_type, context[:1000], content_hash),
        )

        cur.execute(
            """
            UPDATE bitcoin_addresses
            SET domain_count = (
                SELECT COUNT(DISTINCT domain) FROM address_observations WHERE address_id = %s
            )
            WHERE id = %s
            """,
            (address_id, address_id),
        )
    conn.commit()
    return {"address_id": address_id, "address_is_new": address_is_new, "domain_is_new": domain_is_new}


def record_onchain_check(conn, address: str, has_utxo: bool) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bitcoin_addresses
            SET onchain_checked_at = NOW(), onchain_has_utxo = %s
            WHERE address = %s
            """,
            (has_utxo, address),
        )
    conn.commit()


# ---------------- crawl run stats ----------------

def record_crawl_run(conn, started_at, stats: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO crawl_runs (
                started_at, pages_crawled, pages_skipped, pages_failed,
                requests_total, robots_skipped, rate_limited,
                server_errors_or_timeouts, http_errors, unsafe_urls_rejected,
                candidates_found, valid_candidates, new_addresses,
                duplicate_observations, new_domains, links_enqueued,
                unexpected_errors
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                started_at,
                stats["pages_crawled"], stats["pages_skipped"], stats["pages_failed"],
                stats["requests_total"], stats["robots_skipped"], stats["rate_limited"],
                stats["server_errors_or_timeouts"], stats["http_errors"], stats["unsafe_urls_rejected"],
                stats["candidates_found"], stats["valid_candidates"], stats["new_addresses"],
                stats["duplicate_observations"], stats["new_domains"], stats["links_enqueued"],
                stats["unexpected_errors"],
            ),
        )
    conn.commit()


# ---------------- read/report queries ----------------

def get_stats(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM bitcoin_addresses")
        n_addresses = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM crawled_pages")
        n_pages = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM crawl_queue WHERE status = 'pending'")
        n_pending = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM bitcoin_addresses WHERE domain_count > 1")
        n_multi_domain = cur.fetchone()[0]
    return {
        "addresses": n_addresses,
        "pages_crawled": n_pages,
        "urls_pending": n_pending,
        "addresses_on_multiple_domains": n_multi_domain,
    }
