"""
All database access lives here. Every function takes an open connection
so the caller controls transaction boundaries.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import psycopg

from config import DB

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
            SELECT id, url, depth
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
        queue_id, url, depth = row
        cur.execute(
            "UPDATE crawl_queue SET status = 'processing' WHERE id = %s",
            (queue_id,),
        )
    conn.commit()
    return {"id": queue_id, "url": url, "depth": depth}


def finish_url(conn, queue_id: int, status: str, revisit_hours: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE crawl_queue
            SET status = %s,
                last_crawled = NOW(),
                next_crawl = NOW() + (%s || ' hours')::interval
            WHERE id = %s
            """,
            (status, str(revisit_hours), queue_id),
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
) -> int:
    domain = domain_of(url)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domains (domain)
            VALUES (%s)
            ON CONFLICT (domain) DO UPDATE SET last_seen = NOW()
            RETURNING id
            """,
            (domain,),
        )
        domain_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO bitcoin_addresses (address, address_type, first_source_url, last_source_url, observation_count)
            VALUES (%s, %s, %s, %s, 1)
            ON CONFLICT (address) DO UPDATE SET
                last_seen          = NOW(),
                last_source_url    = EXCLUDED.last_source_url,
                observation_count  = bitcoin_addresses.observation_count + 1
            RETURNING id
            """,
            (address, address_type, url, url),
        )
        address_id = cur.fetchone()[0]

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
    return address_id


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
