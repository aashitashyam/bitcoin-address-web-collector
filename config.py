"""
Central configuration. Everything is overridable via environment variables
(or a .env file, loaded automatically) so you never hardcode credentials.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class DBConfig:
    host: str = os.getenv("BTC_DB_HOST", "localhost")
    port: int = int(os.getenv("BTC_DB_PORT", "5432"))
    dbname: str = os.getenv("BTC_DB_NAME", "btc_collector")
    user: str = os.getenv("BTC_DB_USER", "btc_collector")
    password: str = os.getenv("BTC_DB_PASSWORD", "changeme")

    @property
    def dsn(self) -> str:
        return (
            f"host={self.host} port={self.port} dbname={self.dbname} "
            f"user={self.user} password={self.password}"
        )


@dataclass
class CrawlConfig:
    # Identify yourself honestly. Some sites will allowlist/blocklist by UA.
    user_agent: str = os.getenv(
        "BTC_CRAWLER_UA",
        "BitcoinAddressResearchCrawler/1.0 (+academic research project)",
    )
    request_timeout: float = float(os.getenv("BTC_REQUEST_TIMEOUT", "20"))
    # Minimum seconds between two requests to the SAME domain in one run.
    delay_between_requests: float = float(os.getenv("BTC_CRAWL_DELAY", "2.0"))
    max_depth: int = int(os.getenv("BTC_MAX_DEPTH", "4"))
    respect_robots_txt: bool = os.getenv("BTC_RESPECT_ROBOTS", "true").lower() == "true"
    # Hours to wait before a URL is eligible to be recrawled.
    revisit_hours_default: int = int(os.getenv("BTC_REVISIT_HOURS", "48"))


@dataclass
class BitcoinCoreRPCConfig:
    enabled: bool = os.getenv("BTC_RPC_ENABLED", "false").lower() == "true"
    host: str = os.getenv("BTC_RPC_HOST", "127.0.0.1")
    port: int = int(os.getenv("BTC_RPC_PORT", "8332"))
    user: str = os.getenv("BTC_RPC_USER", "")
    password: str = os.getenv("BTC_RPC_PASSWORD", "")


DB = DBConfig()
CRAWL = CrawlConfig()
RPC = BitcoinCoreRPCConfig()
