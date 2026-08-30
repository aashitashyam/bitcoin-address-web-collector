-- Bitcoin Web Address Collector - schema
-- Safe to re-run (IF NOT EXISTS everywhere).

CREATE TABLE IF NOT EXISTS bitcoin_addresses (
    id                  BIGSERIAL PRIMARY KEY,
    address             TEXT NOT NULL UNIQUE,
    address_type        TEXT,                     -- p2pkh, p2sh, p2wpkh, p2wsh, p2tr
    network             TEXT DEFAULT 'mainnet',
    first_seen          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    first_source_url    TEXT,
    last_source_url     TEXT,
    domain_count        INTEGER DEFAULT 0,         -- how many distinct domains published it
    observation_count   INTEGER DEFAULT 0,         -- how many times we've seen it
    onchain_checked_at  TIMESTAMPTZ,                -- last time we asked Bitcoin Core about it
    onchain_has_utxo    BOOLEAN,
    active              BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS domains (
    id              BIGSERIAL PRIMARY KEY,
    domain          TEXT NOT NULL UNIQUE,
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS address_observations (
    id              BIGSERIAL PRIMARY KEY,
    address_id      BIGINT NOT NULL REFERENCES bitcoin_addresses(id) ON DELETE CASCADE,
    url             TEXT NOT NULL,
    domain          TEXT,
    domain_id       BIGINT REFERENCES domains(id),
    page_title      TEXT,
    source_type     TEXT DEFAULT 'unknown',  -- heuristic label: donation, payment, forum, ... (see crawler/classify.py)
    discovered_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    context         TEXT,
    content_hash    TEXT
);

CREATE TABLE IF NOT EXISTS crawled_pages (
    id              BIGSERIAL PRIMARY KEY,
    url             TEXT NOT NULL UNIQUE,
    domain          TEXT,
    first_crawled   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_crawled    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    content_hash    TEXT,
    http_status     INTEGER,
    links_found     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS crawl_queue (
    id              BIGSERIAL PRIMARY KEY,
    url             TEXT NOT NULL UNIQUE,
    domain          TEXT,
    priority        INTEGER DEFAULT 0,
    depth           INTEGER DEFAULT 0,
    attempts        INTEGER DEFAULT 0,
    last_crawled    TIMESTAMPTZ,
    next_crawl      TIMESTAMPTZ DEFAULT NOW(),
    status          TEXT DEFAULT 'pending',  -- pending | processing | failed (terminal)
    last_outcome    TEXT                     -- see workers/crawl_worker.py outcomes
);

-- Migration safety net for databases created before this version: add
-- any columns/tables the old schema didn't have. Safe to run repeatedly.
ALTER TABLE crawl_queue ADD COLUMN IF NOT EXISTS attempts INTEGER DEFAULT 0;
ALTER TABLE crawl_queue ADD COLUMN IF NOT EXISTS last_outcome TEXT;

-- Older versions of this schema set status to 'done'/'skipped' after a
-- crawl, but get_next_url() only ever selects status = 'pending' - so
-- those rows could never be revisited regardless of next_crawl. Reset
-- them back into rotation. This only has an effect once; it's a no-op
-- on every run after that.
UPDATE crawl_queue SET status = 'pending' WHERE status IN ('done', 'skipped');

CREATE TABLE IF NOT EXISTS crawl_runs (
    id                          BIGSERIAL PRIMARY KEY,
    started_at                  TIMESTAMPTZ NOT NULL,
    finished_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    pages_crawled               INTEGER DEFAULT 0,
    pages_skipped               INTEGER DEFAULT 0,
    pages_failed                INTEGER DEFAULT 0,
    requests_total              INTEGER DEFAULT 0,
    robots_skipped              INTEGER DEFAULT 0,
    rate_limited                INTEGER DEFAULT 0,
    server_errors_or_timeouts   INTEGER DEFAULT 0,
    http_errors                 INTEGER DEFAULT 0,
    unsafe_urls_rejected        INTEGER DEFAULT 0,
    candidates_found            INTEGER DEFAULT 0,
    valid_candidates            INTEGER DEFAULT 0,
    new_addresses                INTEGER DEFAULT 0,
    duplicate_observations       INTEGER DEFAULT 0,
    new_domains                   INTEGER DEFAULT 0,
    links_enqueued                 INTEGER DEFAULT 0,
    unexpected_errors               INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_address_observations_address ON address_observations(address_id);
CREATE INDEX IF NOT EXISTS idx_address_observations_time    ON address_observations(discovered_at);
CREATE INDEX IF NOT EXISTS idx_addresses_last_seen           ON bitcoin_addresses(last_seen);
CREATE INDEX IF NOT EXISTS idx_addresses_domain_count         ON bitcoin_addresses(domain_count);
CREATE INDEX IF NOT EXISTS idx_crawl_queue_next               ON crawl_queue(next_crawl, priority);
CREATE INDEX IF NOT EXISTS idx_crawl_queue_status_next         ON crawl_queue(status, next_crawl);
CREATE INDEX IF NOT EXISTS idx_crawl_queue_domain             ON crawl_queue(domain);
CREATE INDEX IF NOT EXISTS idx_observations_domain_id          ON address_observations(domain_id);
CREATE INDEX IF NOT EXISTS idx_observations_source_type        ON address_observations(source_type);
