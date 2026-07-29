"""SQLite storage interface for research data.

The v1 dataset is frozen evidence (see research/archive/v1/). Two capability boundaries
enforce that:

- ``open_readonly`` opens a connection that cannot write and never runs migrations
- ``get_connection``, the writable path, refuses any protected dataset

Both compare fully resolved paths so a symlink or an alternate spelling cannot route a
writer at frozen evidence.
"""

import os
from pathlib import Path
import sqlite3
from typing import Any

DB_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "markets.db"))

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Datasets that must never be written again. The v1 database stays at its original path
# so existing analysis keeps reading it; only its write capability is revoked.
PROTECTED_DATASETS: frozenset[Path] = frozenset(
    {
        Path(DB_PATH).resolve(),
    }
)
# Anything under the archive root is frozen evidence by definition.
PROTECTED_ROOTS: frozenset[Path] = frozenset({(_REPO_ROOT / "research" / "archive").resolve()})


class FrozenDatasetError(RuntimeError):
    """Raised when a write path targets a frozen dataset.

    A distinct type rather than a bare RuntimeError: this is a domain invariant, and a
    future failure here should be unmistakable rather than blending into ordinary errors.
    """


def _is_protected(path: Path) -> bool:
    """True if the resolved path is frozen evidence.

    Resolution matters: a symlink, a relative spelling, or a path through ``..`` must not
    be able to present frozen evidence as a fresh target.
    """
    resolved = path.resolve()
    if resolved in PROTECTED_DATASETS:
        return True
    return any(root == resolved or root in resolved.parents for root in PROTECTED_ROOTS)


def assert_writable(path: str | Path) -> None:
    """Refuse to hand out write access to a frozen dataset.

    There is deliberately no override parameter. No normal workflow modifies frozen
    evidence, so an escape hatch would only ever be used by accident.
    """
    target = Path(path)
    if _is_protected(target):
        raise FrozenDatasetError(
            f"{target} is a frozen dataset and cannot be opened for writing. "
            "Frozen evidence is read-only; collect into a new dataset version instead."
        )


def open_readonly(path: str | Path = DB_PATH) -> sqlite3.Connection:
    """Open a dataset for querying only.

    Three properties, each of which the previous single accessor violated:

    - ``mode=ro`` so SQLite never opens the file writable
    - ``query_only=ON`` so the connection rejects writes even if opened otherwise
    - no schema migration; a read must not mutate what it reads

    Raises:
        FileNotFoundError: If the database does not exist. A missing evidence store must
            never be silently replaced by a newly created empty one.
    """
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(
            f"No database at {target}. Refusing to create one: a read path must not "
            "turn missing evidence into an empty dataset."
        )
    conn = sqlite3.connect(f"file:{target.resolve().as_posix()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn


def open_v1_readonly() -> sqlite3.Connection:
    """Open the frozen v1 research dataset for forensic querying."""
    return open_readonly(DB_PATH)


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
    price_24h_before REAL,
    price_6h_before REAL,
    price_1h_before REAL,
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


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Add columns that may not exist in older databases."""
    cursor = conn.execute("PRAGMA table_info(markets)")
    existing = {row[1] for row in cursor.fetchall()}
    if "category" not in existing:
        conn.execute("ALTER TABLE markets ADD COLUMN category TEXT")
    for col in ("price_24h_before", "price_6h_before", "price_1h_before"):
        if col not in existing:
            conn.execute(f"ALTER TABLE markets ADD COLUMN {col} REAL")


def get_connection(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    """Open (or create) a writable database and ensure schema exists.

    Raises:
        FrozenDatasetError: If the target is a frozen dataset.
    """
    assert_writable(db_path)
    target = Path(db_path)
    os.makedirs(target.parent, exist_ok=True)
    conn = sqlite3.connect(str(target))
    conn.executescript(_SCHEMA)
    _ensure_columns(conn)
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
