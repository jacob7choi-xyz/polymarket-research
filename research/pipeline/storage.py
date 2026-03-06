"""SQLite storage interface for research data."""

import os
import sqlite3
from typing import Any

DB_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "markets.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
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
);

CREATE TABLE IF NOT EXISTS price_history (
    market_id TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    price REAL NOT NULL,
    PRIMARY KEY (market_id, timestamp),
    FOREIGN KEY (market_id) REFERENCES markets(market_id)
);
"""


def get_connection() -> sqlite3.Connection:
    """Open (or create) the SQLite database and ensure schema exists."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(_SCHEMA)
    return conn


def upsert_market(conn: sqlite3.Connection, market: dict[str, Any]) -> None:
    """Insert or replace a market row."""
    conn.execute(
        """
        INSERT OR REPLACE INTO markets
            (market_id, question, category, created_at, closed_at,
             volume_usd, resolved_yes, clob_token_ids, final_yes_price,
             price_history_fetched, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            market["market_id"],
            market["question"],
            market["category"],
            market["created_at"],
            market["closed_at"],
            market["volume_usd"],
            market["resolved_yes"],
            market.get("clob_token_ids"),
            market.get("final_yes_price"),
            market.get("price_history_fetched", 0),
            market["fetched_at"],
        ),
    )


def upsert_price_history(
    conn: sqlite3.Connection, market_id: str, prices: list[dict[str, Any]]
) -> None:
    """Insert or replace price history rows for a market."""
    conn.executemany(
        """
        INSERT OR REPLACE INTO price_history (market_id, timestamp, price)
        VALUES (?, ?, ?)
        """,
        [(market_id, p["timestamp"], p["price"]) for p in prices],
    )


def mark_price_history_fetched(
    conn: sqlite3.Connection, market_id: str, final_price: float | None
) -> None:
    """Mark a market's price history as fetched and store the final price."""
    conn.execute(
        """
        UPDATE markets
        SET price_history_fetched = 1, final_yes_price = ?
        WHERE market_id = ?
        """,
        (final_price, market_id),
    )


def get_unfetched_markets(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return markets whose price history has not yet been fetched."""
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        """
        SELECT market_id, question, closed_at, clob_token_ids
        FROM markets
        WHERE price_history_fetched = 0
        ORDER BY created_at
        """
    )
    rows = cursor.fetchall()
    conn.row_factory = None
    return [dict(row) for row in rows]
