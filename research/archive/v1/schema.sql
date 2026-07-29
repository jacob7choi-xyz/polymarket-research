-- index sqlite_autoindex_markets_1

-- index sqlite_autoindex_price_history_1

-- table markets
CREATE TABLE markets (
    market_id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    category TEXT,
    created_at TEXT NOT NULL,
    closed_at TEXT,
    volume_usd REAL,
    resolved_yes INTEGER,  -- 1=True, 0=False, NULL=ambiguous/voided
    clob_token_ids TEXT,   -- raw JSON string of CLOB token IDs
    final_yes_price REAL,
    price_history_fetched INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL
, price_24h_before REAL, price_6h_before REAL, price_1h_before REAL)
-- table price_history
CREATE TABLE price_history (
    market_id TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    price REAL NOT NULL,
    PRIMARY KEY (market_id, timestamp),
    FOREIGN KEY (market_id) REFERENCES markets(market_id)
)
