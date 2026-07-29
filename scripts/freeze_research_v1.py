"""Freeze the exploratory research dataset as immutable evidence.

Produces a one-shot integrity manifest for the v1 research database and a verified
byte-for-byte canonical copy outside the repository. The manifest is the integrity
anchor: any later modification of the working database produces a hash mismatch.

Refuses unconditionally if a manifest already exists. There is no override and no
concept of re-freezing: a dataset version's identity is immutable once established.
A corrected or recollected dataset is a new version with its own identifier, not a
replacement anchor for this one.

Usage (from the project root):
    python scripts/freeze_research_v1.py [--canonical-dir PATH]
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DB = REPO_ROOT / "research" / "data" / "markets.db"
ARCHIVE_DIR = REPO_ROOT / "research" / "archive" / "v1"
MANIFEST_PATH = ARCHIVE_DIR / "manifest.json"
DEFAULT_CANONICAL_DIR = Path.home() / "polymarket-research-archive" / "v1"

# Analysis outputs whose provenance we want recorded alongside the dataset
TRACKED_OUTPUTS = (
    "research/ROADMAP.md",
    "research/analysis/calibration_curve.png",
    "research/analysis/calibration_curve_preresolution.png",
    "research/analysis/calibration_curve_by_category.png",
)

CHUNK = 1 << 20


def sha256_file(path: Path) -> str:
    """Hash a file in chunks so large databases do not load into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return out.stdout.strip()


def git_provenance() -> dict[str, str | bool | None]:
    """HEAD plus worktree cleanliness.

    A commit SHA alone does not establish that the working tree matched it. Record
    dirtiness so the manifest carries that fact rather than leaving a future reader to
    reconstruct it from a shell transcript.
    """
    porcelain = _git("status", "--porcelain", "--untracked-files=no")
    return {
        "commit": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "is_dirty": bool(porcelain) if porcelain is not None else None,
        "status_porcelain": porcelain,
    }


def schema_dump(db: Path) -> str:
    """Full CREATE statements, ordered, so the schema itself is hashable."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
    finally:
        conn.close()
    return "\n".join(f"-- {t} {n}\n{sql or ''}" for t, n, sql in rows)


def integrity_check(db: Path) -> str:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        conn.close()


def table_counts(db: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        names = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        # Identifiers cannot be bound as parameters; quote them rather than
        # interpolating raw names, even though these come from sqlite_master
        return {
            n: conn.execute(f'SELECT COUNT(*) FROM "{n.replace(chr(34), chr(34) * 2)}"').fetchone()[
                0
            ]
            for n in names
        }
    finally:
        conn.close()


def runtime_identity() -> dict[str, str | None]:
    lock = REPO_ROOT / "uv.lock"
    return {
        "python_version": sys.version.split()[0],
        "sqlite_version": sqlite3.sqlite_version,
        "platform": platform.platform(),
        "uv_lock_sha256": sha256_file(lock) if lock.exists() else None,
    }


def output_hashes() -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for rel in TRACKED_OUTPUTS:
        path = REPO_ROOT / rel
        result[rel] = sha256_file(path) if path.exists() else None
    return result


def freeze(canonical_dir: Path) -> int:
    # A documented invariant the program can violate is not an enforced invariant.
    # The canonical copy must live outside the repository, symlinks resolved.
    canonical_dir = canonical_dir.resolve()
    repo = REPO_ROOT.resolve()
    if canonical_dir == repo or repo in canonical_dir.parents:
        print(
            f"REFUSING: canonical directory {canonical_dir} is inside the repository. "
            "The canonical copy must be stored outside it.",
            file=sys.stderr,
        )
        return 1

    if MANIFEST_PATH.exists():
        print(f"REFUSING: manifest already exists at {MANIFEST_PATH}", file=sys.stderr)
        print(
            "A dataset version's identity is immutable. There is no re-freeze. "
            "A corrected dataset is a new version with its own identifier.",
            file=sys.stderr,
        )
        return 1
    if not SOURCE_DB.exists():
        print(f"REFUSING: source database not found at {SOURCE_DB}", file=sys.stderr)
        return 1

    print(f"source: {SOURCE_DB}")
    integrity = integrity_check(SOURCE_DB)
    print(f"  integrity_check: {integrity}")
    if integrity != "ok":
        print("REFUSING: integrity check did not return 'ok'", file=sys.stderr)
        return 1

    source_sha = sha256_file(SOURCE_DB)
    size = SOURCE_DB.stat().st_size
    print(f"  sha256: {source_sha}")
    print(f"  bytes:  {size:,}")

    schema = schema_dump(SOURCE_DB)
    counts = table_counts(SOURCE_DB)
    print(f"  tables: {counts}")

    # Canonical copy, then verify the copy independently rather than trusting the copy call
    canonical_dir.mkdir(parents=True, exist_ok=True)
    canonical_db = canonical_dir / "markets.db"
    if canonical_db.resolve() == SOURCE_DB.resolve():
        print("REFUSING: canonical copy path resolves to the source database", file=sys.stderr)
        return 1
    if canonical_db.exists():
        print(f"REFUSING: canonical copy already exists at {canonical_db}", file=sys.stderr)
        return 1
    print(f"copying to canonical archive: {canonical_db}")
    shutil.copy2(SOURCE_DB, canonical_db)
    canonical_sha = sha256_file(canonical_db)
    print(f"  canonical sha256: {canonical_sha}")
    if canonical_sha != source_sha:
        print("REFUSING: canonical copy hash does not match source", file=sys.stderr)
        return 1
    print("  VERIFIED: canonical copy is byte-for-byte identical")

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    schema_path = ARCHIVE_DIR / "schema.sql"
    schema_path.write_text(schema + "\n")
    # Hash the file as written, so "file hash" needs no normalisation convention
    schema_sha = sha256_file(schema_path)

    manifest = {
        # Explicit so readers never infer the format from which keys happen to be
        # present. Format 1 recorded a bare `git_commit` and hashed a normalised
        # schema string; format 2 records full git provenance and hashes the file.
        "manifest_format_version": 2,
        "dataset": "research-v1-exploratory",
        "status": "FROZEN",
        "frozen_at_utc": datetime.now(UTC).isoformat(),
        "source_path": str(SOURCE_DB.relative_to(REPO_ROOT)),
        "canonical_copy_path": str(canonical_db),
        "database": {
            "sha256": source_sha,
            "size_bytes": size,
            "integrity_check": integrity,
            "schema_sha256": schema_sha,
            "table_row_counts": counts,
        },
        "git": git_provenance(),
        "runtime": runtime_identity(),
        "analysis_output_sha256": output_hashes(),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"wrote manifest: {MANIFEST_PATH}")
    print(f"wrote schema:   {ARCHIVE_DIR / 'schema.sql'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--canonical-dir",
        type=Path,
        default=DEFAULT_CANONICAL_DIR,
        help="Directory outside the repository for the canonical copy",
    )
    args = parser.parse_args()
    return freeze(args.canonical_dir)


if __name__ == "__main__":
    raise SystemExit(main())
