"""SQLite storage interface for research data.

The v1 dataset is frozen evidence (see research/archive/v1/). Two capability boundaries
enforce that:

- ``open_readonly`` opens a connection that cannot write and never runs migrations
- ``get_connection``, the writable path, refuses any protected dataset

Both compare fully resolved paths so a symlink or an alternate spelling cannot route a
writer at frozen evidence.
"""

import json
import os
from pathlib import Path
import sqlite3
from typing import Any
from urllib.parse import quote

DB_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "markets.db"))

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ARCHIVE_ROOT = (_REPO_ROOT / "research" / "archive").resolve()


class EvidenceManifestError(RuntimeError):
    """Raised when a freeze manifest exists but cannot be interpreted.

    Distinct from a missing manifest, which simply means there is nothing to discover.
    """


def _canonical_path_from_manifest(manifest: Path) -> Path:
    """Read and fully validate the canonical evidence path a manifest declares.

    Every failure mode raises ``EvidenceManifestError``. Parsing successfully is not the
    same as being interpretable: valid JSON that is a list, a scalar, or an object whose
    ``canonical_copy_path`` is not a usable absolute path all mean the identity of an
    evidence asset is unknown, which must refuse rather than protect fewer paths.

    Two validations exist for reasons beyond type hygiene:

    - a relative path would resolve against the process working directory, so the same
      manifest would protect different assets depending on where it ran
    - a path directly beneath the filesystem root would put ``/`` into the protected
      roots and make every path on the machine unwritable through this module

    Raises:
        EvidenceManifestError: On any unreadable, unparseable, or unusable manifest.
    """

    def refuse(reason: str) -> EvidenceManifestError:
        return EvidenceManifestError(
            f"{manifest}: {reason}. Refusing to initialise storage with an unknown "
            "evidence identity."
        )

    try:
        payload = json.loads(manifest.read_text())
    except (OSError, ValueError) as exc:
        raise refuse("could not be read or parsed as a freeze manifest") from exc

    if not isinstance(payload, dict):
        raise refuse(f"parsed as {type(payload).__name__}, not a JSON object")

    recorded = payload.get("canonical_copy_path")
    if not isinstance(recorded, str) or not recorded.strip():
        raise refuse("canonical_copy_path is missing or not a non-empty string")

    canonical = Path(recorded).expanduser()
    if not canonical.is_absolute():
        raise refuse(f"canonical_copy_path {recorded!r} is not absolute")

    canonical = canonical.resolve()
    # anchor is a str while parent is a Path, so compare like with like
    if canonical.parent == Path(canonical.anchor):
        raise refuse(
            f"canonical_copy_path {recorded!r} sits directly beneath the filesystem "
            "root, which would protect every path on the machine"
        )
    return canonical


def _canonical_copies() -> tuple[set[Path], set[Path]]:
    """Canonical evidence assets and their containing directories.

    Protection must attach to the asset, not only to its in-repo working copy. Each
    manifest records where its canonical copy lives, so the protected set derives from
    the evidence record rather than from a hardcoded guess at the archive layout.

    Returns:
        (datasets, roots) -- the canonical database files, and the directories holding
        them. Kept separate so each protected set means what its name says.
    """
    datasets: set[Path] = set()
    roots: set[Path] = set()
    if not _ARCHIVE_ROOT.exists():
        return datasets, roots
    for manifest in sorted(_ARCHIVE_ROOT.glob("*/manifest.json")):
        canonical = _canonical_path_from_manifest(manifest)
        datasets.add(canonical)
        roots.add(canonical.parent)
    return datasets, roots


_CANONICAL_DATASETS, _CANONICAL_ROOTS = _canonical_copies()

# Individual database files that must never be written again. The v1 database stays at
# its original path so existing analysis keeps reading it; only write capability is
# revoked.
PROTECTED_DATASETS: frozenset[Path] = frozenset({Path(DB_PATH).resolve()} | _CANONICAL_DATASETS)

# Directory trees that are frozen in their entirety. research/archive/ is, by
# architectural convention, permanent immutable evidence: every path beneath it is
# frozen. Staging or scratch space for a new dataset version belongs outside this root,
# not under it. Narrowing this to specific files would invite exactly the "just put the
# mutable copy in archive/" workaround that erodes the invariant.
PROTECTED_ROOTS: frozenset[Path] = frozenset({_ARCHIVE_ROOT} | _CANONICAL_ROOTS)


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
    # Percent-encode the path: '?', '#' and '%' are URI syntax, so an unescaped
    # filename containing them would be parsed as query/fragment rather than as a name
    quoted = quote(target.resolve().as_posix(), safe="/")
    conn = sqlite3.connect(f"file:{quoted}?mode=ro", uri=True)
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
