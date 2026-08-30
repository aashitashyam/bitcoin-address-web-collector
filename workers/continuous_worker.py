"""
Wraps the bounded crawl_worker.run() in a loop so collector can run
unattended (as a systemd service or a long-lived container) instead
of being a one-shot script continuously re-invoked. 
Database gives what's due.
"""

from __future__ import annotations

import logging
import signal
import time

import psycopg

from database import repository as repo
from workers import crawl_worker

logger = logging.getLogger(__name__)

_stop_requested = False


def _handle_stop_signal(signum, _frame) -> None:
    global _stop_requested
    logger.info("Received signal %s - will stop after the current batch.", signum)
    _stop_requested = True


def run_forever(max_pages_per_batch: int = 100, poll_interval_seconds: int = 60) -> None:
    global _stop_requested
    _stop_requested = False
    signal.signal(signal.SIGINT, _handle_stop_signal)
    signal.signal(signal.SIGTERM, _handle_stop_signal)

    conn = repo.get_connection()

    while not _stop_requested:
        try:
            stats = crawl_worker.run(conn, max_pages=max_pages_per_batch)
        except psycopg.OperationalError:
            logger.exception("Database connection problem - reconnecting in 5s.")
            try:
                conn.close()
            except Exception:
                pass
            time.sleep(5)
            conn = repo.get_connection()
            continue

        logger.info("Batch complete: %s", stats)

        if stats["pages_crawled"] == 0 and stats["pages_skipped"] == 0 and stats["pages_failed"] == 0:
            # Nothing was due for (re)crawl right now - wait before polling
            # again. Sleep in small increments so a stop signal is honored
            # promptly instead of waiting out the full interval.
            for _ in range(poll_interval_seconds):
                if _stop_requested:
                    break
                time.sleep(1)

    conn.close()
    logger.info("Stopped.")
