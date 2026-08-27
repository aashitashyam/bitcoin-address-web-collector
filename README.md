# Bitcoin Address Web Collector

A web crawler for discovering publicly exposed Bitcoin addresses and storing them with their source URL, page context, and observation history.

The collector identifies candidate Bitcoin addresses in HTML pages, validates them using the appropriate address encoding and checksum rules, and stores the results in PostgreSQL. It can optionally query a Bitcoin Core node to check whether a matching unspent output currently exists.

## Features

* Breadth-first crawling from configurable seed URLs
* `robots.txt` support
* Configurable per-domain request delays
* Configurable crawl depth and page limits
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
* Optional Bitcoin Core `scantxoutset` integration

## How It Works

The crawler follows links starting from a configurable set of seed URLs.

For each page, it:

1. Checks the site's `robots.txt` rules.
2. Applies the configured delay for the domain.
3. Fetches the page using a standard HTTP client.
4. Extracts visible page text and links.
5. Searches the text for strings that match Bitcoin address patterns.
6. Validates each candidate using the appropriate Bitcoin address encoding and checksum rules.
7. Stores valid addresses and their web observations in PostgreSQL.
8. Adds newly discovered links to the crawl queue.
9. Records crawl metadata and schedules the page for a future revisit.

Regex matching is used only to identify candidates. A regex match alone is not considered a valid Bitcoin address.

A checksum-valid address establishes that the string is a valid address encoding. It does not establish ownership, historical use, or a relationship between the address and the entity operating the webpage.

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
│   └── robots.py
├── workers/
│   └── crawl_worker.py
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

## Usage

Run a crawl with a page limit:

```bash
python3 main.py --max-pages 200
```

Limit the crawl depth:

```bash
python3 main.py --max-pages 200 --max-depth 3
```

Display database statistics without starting a crawl:

```bash
python3 main.py --stats-only
```

The collector can be run repeatedly. Pages are not revisited until their configured revisit interval has elapsed.

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

Stores URLs waiting to be crawled or scheduled for a future crawl.

The queue tracks information such as:

* URL
* Crawl status
* Priority
* Crawl depth
* Last crawl time
* Next scheduled crawl time

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

## Crawling Behaviour

The crawler:

* Honors applicable `robots.txt` rules
* Applies a configurable delay between requests to the same domain
* Limits crawl depth
* Limits the number of pages processed per run
* Avoids revisiting pages until their scheduled revisit time
* Records crawl results in PostgreSQL so that state is preserved between runs

The crawl queue is persistent, so restarting the program does not require starting the crawl from scratch.

## Limitations

* The default fetcher does not execute client-side JavaScript.
* The crawler only discovers addresses that are exposed in content reachable from the configured seeds.
* Regex matching is only a candidate-extraction step; it does not establish address validity.
* Checksum validation does not establish ownership or historical use.
* Bitcoin Core `scantxoutset` provides current UTXO information, not complete transaction history.
* `source_type` classification is heuristic and may be incorrect.
* Crawl coverage depends on the chosen seed URLs, crawl depth, link structure, and site accessibility.
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

The integration test verifies address extraction and validation, link discovery, database storage, and crawler handling of robots-disallowed pages.

## Responsible Use

This project is intended for research and analysis of publicly available information.

Users are responsible for complying with applicable laws, website terms of service, `robots.txt` directives, and reasonable crawl-rate limits.

The collector does not bypass authentication or access controls and is not intended to access private resources.

## References

* [BIP 173 — Base32 address format for native v0-16 witness outputs](https://github.com/bitcoin/bips/blob/master/bip-0173.mediawiki)
* [BIP 350 — Bech32m format for v1+ witness addresses](https://github.com/bitcoin/bips/blob/master/bip-0350.mediawiki)
* [Bitcoin Core RPC documentation — `scantxoutset`](https://bitcoincore.org/en/doc/30.0.0/rpc/blockchain/scantxoutset/)
* [RFC 9309 — Robots Exclusion Protocol](https://www.rfc-editor.org/rfc/rfc9309.html)


