import argparse

from database import repository as repo
from workers import crawl_worker


def load_seeds(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def main() -> None:
    parser = argparse.ArgumentParser(description="Bitcoin address web collector")
    parser.add_argument("--seeds", default="seeds.txt", help="Path to seed URL list")
    parser.add_argument("--max-pages", type=int, default=50, help="Max pages to crawl this run")
    parser.add_argument("--max-depth", type=int, default=None, help="Max crawl depth from seeds")
    parser.add_argument("--init-db", action="store_true", help="Create schema before running")
    parser.add_argument("--stats-only", action="store_true", help="Print DB stats and exit")
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

    stats = crawl_worker.run(conn, max_pages=args.max_pages, max_depth=args.max_depth)
    print("Run complete:", stats)
    print("Totals so far:", repo.get_stats(conn))

    conn.close()


if __name__ == "__main__":
    main()
