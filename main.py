import argparse
import logging

from database import repository as repo
from workers import crawl_worker


def load_seeds(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def main() -> None:
    parser = argparse.ArgumentParser(description="Bitcoin address web collector")
    parser.add_argument("--seeds", default="seeds.txt", help="Path to seed URL list")
    parser.add_argument("--max-pages", type=int, default=50, help="Pages per batch")
    parser.add_argument("--max-depth", type=int, default=None, help="Max crawl depth from seeds")
    parser.add_argument("--init-db", action="store_true", help="Create/upgrade schema before running")
    parser.add_argument("--stats-only", action="store_true", help="Print DB stats and exit")
    parser.add_argument(
        "--forever",
        action="store_true",
        help="Run continuously instead of exiting after one batch (Ctrl+C / SIGTERM to stop)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=60,
        help="Seconds to wait between polls when idle, in --forever mode",
    )
    args = parser.parse_args()

    conn = repo.get_connection()

    if args.init_db:
        repo.init_schema(conn)
        print("Schema initialized.")

    if args.stats_only:
        print(repo.get_stats(conn))
        conn.close()
        return

    seeds = load_seeds(args.seeds)
    for seed in seeds:
        repo.enqueue_url(conn, seed, depth=0, priority=10)
    print(f"Enqueued {len(seeds)} seed URL(s).")

    if args.forever:
        conn.close()  # continuous_worker manages its own connection/reconnects
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        from workers import continuous_worker

        continuous_worker.run_forever(
            max_pages_per_batch=args.max_pages,
            poll_interval_seconds=args.poll_interval,
        )
        return

    stats = crawl_worker.run(conn, max_pages=args.max_pages, max_depth=args.max_depth)
    print("Run complete:", stats)
    print("Totals so far:", repo.get_stats(conn))

    conn.close()


if __name__ == "__main__":
    main()
