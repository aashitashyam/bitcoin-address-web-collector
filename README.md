# Bitcoin Address Web Collector

A web crawler for discovering publicly exposed Bitcoin addresses and storing them with their source URL, page context, and observation history.

The collector identifies candidate Bitcoin addresses in HTML pages, validates them using the appropriate address encoding and checksum rules, and stores the results in PostgreSQL. It can optionally query a Bitcoin Core node to check whether a matching unspent output currently exists.

## Features

* Crawling from configurable seed URLs, following links across domains with no same-site restriction
* `robots.txt` support
* A private/internal-network destination check, so discovered links can't direct the crawler at the local machine or an internal network
* Configurable per-domain request delays
* Configurable crawl depth and page limits
* Automatic retry with exponential backoff for transient failures (timeouts, server errors, rate limiting), and immediate, non-retried failure for permanent ones (404, unsafe destinations)
* Continuous operation mode for unattended, long-running crawls, alongside the standard bounded batch mode
* Per-page failure isolation, so an unexpected error on one page does not stop the run
* Extraction of Bitcoin address candidates from HTML page text
* Validation of:

  * Legacy P2PKH and P2SH addresses (`1...`, `3...`) using Base58Check
  * Native SegWit v0 addresses (`bc1q...`) using Bech32
  * SegWit v1 and later addresses, including Taproot (`bc1p...`), using Bech32m
* Provenance tracking for discovered addresses:

  * Source URL
  * Domain
  * Page title
  * First and last observation times
  * Surrounding page text
  * Number of observations
  * Number of distinct domains
* PostgreSQL-backed storage
* Persistent crawl queue
* Configurable page revisit interval
* Per-run crawl statistics, persisted for later querying
* Optional Bitcoin Core `scantxoutset` integration

## How It Works

The crawler follows links starting from a configurable set of seed URLs. It is not restricted to the domains in the seed list; the only thing that excludes a destination is the private-network check below.

For each page, it:

1. Checks the site's `robots.txt` rules.
2. Confirms the destination does not resolve to a private, loopback, or other internal network address.
3. Applies the configured delay for the domain.
4. Fetches the page using a standard HTTP client.
5. Extracts visible page text and links.
6. Searches the text for strings that match Bitcoin address patterns.
7. Validates each candidate using the appropriate Bitcoin address encoding and checksum rules.
8. Stores valid addresses and their web observations in PostgreSQL.
9. Checks newly discovered links against the same private-network rule and adds the safe ones to the crawl queue.
10. Records crawl metadata and schedules the page for a future revisit, or a retry with backoff if the fetch failed.

Regex matching is used only to identify candidates. A regex match alone is not considered a valid Bitcoin address.

A checksum-valid address establishes that the string is a valid address encoding. It does not establish ownership, historical use, or a relationship between the address and the entity operating the webpage.

A failed fetch does not stop the crawl. Timeouts, server errors, and rate-limit responses are retried later with backoff. An unexpected error while processing a page is caught, the page is scheduled for a retry, and the crawl continues with the next URL.

## Project Structure

```text
btc_web_collector/
├── config.py
├── main.py
├── seeds.txt
├── database/
│   ├── schema.sql
│   └── repository.py
├── bitcoin/
│   ├── extractor.py
│   ├── validator.py
│   └── core_rpc.py
├── crawler/
│   ├── fetcher.py
│   ├── parser.py
│   ├── robots.py
│   └── url_safety.py
├── workers/
│   ├── crawl_worker.py
│   └── continuous_worker.py
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Requirements

* Python 3.11+
* PostgreSQL
* Docker (optional, for running PostgreSQL)
* Bitcoin Core (optional, only required for blockchain enrichment)

## Installation

### 1. Start PostgreSQL

Using Docker:

```bash
docker compose up -d
```

An existing PostgreSQL installation can also be used by configuring the database connection in `.env`.

### 2. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure the application

Create the environment file:

```bash
cp .env.example .env
```

Edit `.env` and set the database connection parameters and crawler settings.

Do not commit `.env` or any file containing database or Bitcoin Core RPC credentials.

### 4. Add seed URLs

Add starting URLs to `seeds.txt`, one URL per line.

Only crawl websites and content that you are permitted to access. The crawler is intended for publicly available web content and does not bypass authentication or access controls.

### 5. Initialize the database

```bash
python3 main.py --init-db
```

This is also safe to run against a database created by an earlier version of the schema; it adds any missing tables and columns and does not touch existing data.

## Usage

Run a crawl with a page limit:

```bash
python3 main.py --max-pages 200
```

Limit the crawl depth:

```bash
python3 main.py --max-pages 200 --max-depth 3
```

Run continuously, polling for new work when idle:

```bash
python3 main.py --forever --max-pages 200 --poll-interval 60
```

This runs until stopped with Ctrl+C or SIGTERM, finishing its current batch before exiting.

Display database statistics without starting a crawl:

```bash
python3 main.py --stats-only
```

The collector can be run repeatedly, in either mode. Pages are not revisited until their configured revisit interval has elapsed, and a page that failed is not retried until its backoff period has elapsed.

## Database

The database separates unique addresses from individual web observations.

### `bitcoin_addresses`

Stores one record for each unique discovered Bitcoin address.

Typical fields include:

* Address
* Address type
* First observed timestamp
* Last observed timestamp
* First source URL
* Number of observations
* Number of distinct domains

### `address_observations`

Stores each web occurrence of an address.

Typical fields include:

* Address
* Source URL
* Domain
* Page title
* Discovery timestamp
* Surrounding text context
* Source classification

The observation table preserves the history of where an address was found, while the `bitcoin_addresses` table stores the current aggregate information for each address.

### `crawled_pages`

Stores crawl information for discovered pages, including:

* URL
* First and last crawl times
* HTTP status
* Content hash
* Number of links discovered

The content hash can be used to detect changes between crawls.

### `crawl_queue`

Stores URLs waiting to be crawled or scheduled for a future crawl or retry.

The queue tracks information such as:

* URL
* Crawl status
* Priority
* Crawl depth
* Number of attempts
* Outcome of the last attempt
* Last crawl time
* Next scheduled crawl time

A status of `failed` is terminal: the URL will not be picked up again. This happens either after a non-retryable failure (a 404, or a destination rejected by the private-network check) or after a retryable failure has exceeded the configured attempt limit.

### `crawl_runs`

Stores summary statistics for each crawl batch: pages crawled, pages skipped, pages that failed, total requests made, and counts broken down by outcome (robots-disallowed, rate-limited, server errors, other HTTP errors, rejected unsafe destinations), along with candidate and address counts for that run.

This is what makes throughput questions — pages per day, new addresses per day, what fraction of candidates turn out to be checksum-valid — a query instead of something read out of logs.

### `domains`

Stores discovered domains and can be used to track observations across distinct domains.

## Example Queries

Find addresses that have been observed on multiple domains:

```sql
SELECT
    address,
    address_type,
    domain_count,
    observation_count
FROM bitcoin_addresses
WHERE domain_count > 1
ORDER BY domain_count DESC;
```

Find all pages where an address was observed:

```sql
SELECT
    ao.url,
    ao.page_title,
    ao.discovered_at,
    ao.context
FROM address_observations ao
JOIN bitcoin_addresses ba
    ON ba.id = ao.address_id
WHERE ba.address = 'bc1q...'
ORDER BY ao.discovered_at;
```

Find recently discovered addresses:

```sql
SELECT
    address,
    address_type,
    first_seen,
    first_source_url
FROM bitcoin_addresses
ORDER BY first_seen DESC
LIMIT 20;
```

Find domains with the largest number of distinct addresses:

```sql
SELECT
    d.domain,
    COUNT(DISTINCT ao.address_id) AS distinct_addresses
FROM domains d
JOIN address_observations ao
    ON ao.domain_id = d.id
GROUP BY d.domain
ORDER BY distinct_addresses DESC
LIMIT 20;
```

Crawl throughput by day:

```sql
SELECT
    date_trunc('day', started_at) AS day,
    SUM(pages_crawled) AS pages,
    SUM(new_addresses) AS new_addresses
FROM crawl_runs
GROUP BY 1
ORDER BY 1 DESC;
```

## Bitcoin Address Validation

Address candidates are identified using regular expressions and then passed to format-specific validation.

The validator handles:

* Base58Check for legacy P2PKH and P2SH addresses
* Bech32 for native SegWit version 0
* Bech32m for SegWit version 1 and later, including Taproot

A candidate is stored only after the corresponding validation checks succeed.

Validation confirms that the string conforms to the relevant Bitcoin address format and checksum rules. It does not determine who controls the address or whether the address has ever been used on-chain.

## Source Classification

Observations may be assigned a `source_type`, for example:

* `donation`
* `payment`
* `forum`
* `exchange`
* `unknown`

The classification is heuristic and is based on information such as the page URL and title. It is intended as a signal for later analysis and should not be treated as verified information about the purpose of an address.

## Bitcoin Core Integration

Bitcoin Core integration is optional.

Enable it in `.env` and configure the RPC connection:

```text
BTC_RPC_ENABLED=true
BTC_RPC_HOST=...
BTC_RPC_PORT=...
BTC_RPC_USER=...
BTC_RPC_PASSWORD=...
```

An address can then be checked through the Core RPC module.

The collector uses Bitcoin Core's `scantxoutset` RPC to scan the current UTXO set for outputs matching the specified address. This provides current unspent-output information rather than complete transaction history.

A negative result does not mean that an address has never been used. An address may have received and spent funds and therefore have no matching unspent outputs at the time of the scan.

Full historical transaction lookup requires a separate indexing solution or another blockchain data source.

## JavaScript-Rendered Pages

The default crawler uses standard HTTP requests and does not execute client-side JavaScript.

Some websites generate page content dynamically in the browser. Addresses that exist only after JavaScript execution will therefore not be visible to the default fetcher.

For such pages, a browser-based fetcher such as Playwright can be added:

```bash
pip install playwright
playwright install chromium
```

Browser rendering is not enabled by default because it requires substantially more resources than a normal HTTP request.

## Network Safety

Because the crawler follows discovered links with no restriction on which domain they belong to, every link is checked before it is queued and again before it is fetched. A link that resolves to a private, loopback, link-local, or otherwise internal IP address is rejected. This prevents a page anywhere on the public web from directing the crawler at the local machine or an internal network, including cloud metadata endpoints such as `169.254.169.254`.

This check is enabled by default and can be turned off with `BTC_BLOCK_PRIVATE_IPS=false`, which can be used when testing against a local server.

The check resolves DNS at the time a link is discovered or fetched, not at the moment the connection is opened, so it does not protect against a hostname that resolves safely at check time but to a private address by the time the request is sent. Closing that gap would require resolving at the socket layer, which this version does not do.

## Crawling Behaviour

The crawler:

* Honors applicable `robots.txt` rules
* Applies a configurable delay between requests to the same domain
* Follows links to any domain; the only exclusion is the private-network check above
* Limits crawl depth
* Limits the number of pages processed per run, or runs continuously with `--forever`
* Retries transient failures with exponential backoff, and does not retry permanent ones
* Avoids revisiting pages until their scheduled revisit time
* Isolates failures per page, so an unexpected error does not stop the run
* Records crawl results in PostgreSQL so that state is preserved between runs

The crawl queue is persistent, so restarting the program does not require starting the crawl from scratch. This applies to `--forever` mode as well: if the process is stopped and restarted, it resumes from the same queue state.

## Limitations

* The default fetcher does not execute client-side JavaScript.
* The crawler only discovers addresses that are exposed in content reachable from the configured seeds.
* Regex matching is only a candidate-extraction step; it does not establish address validity.
* Checksum validation does not establish ownership or historical use.
* Bitcoin Core `scantxoutset` provides current UTXO information, not complete transaction history.
* `source_type` classification is heuristic and may be incorrect.
* Crawl coverage depends on the chosen seed URLs, crawl depth, link structure, and site accessibility.
* The private-network check resolves DNS at discovery/fetch time, not at connection time, and does not protect against DNS rebinding.
* Discovered URLs are not canonicalized, so equivalent URLs differing only by tracking parameters may be queued and crawled separately.
* The collector does not use search-engine result pages as a crawling backend.

## Testing

The Bitcoin address validator has been tested against valid and invalid address vectors covering:

* Base58Check addresses
* Bech32 SegWit addresses
* Bech32m/Taproot addresses
* Checksum-invalid addresses

The crawler has also been tested end-to-end using a local PostgreSQL database and a local test website containing:

* Linked pages
* Valid Bitcoin addresses
* Invalid or checksum-corrupted address strings
* A `robots.txt` rule
* Responses simulating rate limiting, server errors, and permanent failures

The integration tests verify address extraction and validation, link discovery, database storage, crawler handling of robots-disallowed pages, retry and backoff behaviour, rejection of links resolving to private or internal addresses (including a cloud metadata address), per-page failure isolation, and the schema migration path from an earlier version of the database.

## References

* [BIP 173 — Base32 address format for native v0-16 witness outputs](https://github.com/bitcoin/bips/blob/master/bip-0173.mediawiki)
* [BIP 350 — Bech32m format for v1+ witness addresses](https://github.com/bitcoin/bips/blob/master/bip-0350.mediawiki)
* [Bitcoin Core RPC documentation — `scantxoutset`](https://bitcoincore.org/en/doc/30.0.0/rpc/blockchain/scantxoutset/)
* [RFC 9309 — Robots Exclusion Protocol](https://www.rfc-editor.org/rfc/rfc9309.html)
* [RFC 1918 — Address Allocation for Private Internets](https://www.rfc-editor.org/rfc/rfc1918.html)