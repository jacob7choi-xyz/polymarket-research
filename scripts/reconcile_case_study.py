"""Recompute the case study's principal quantitative claims from frozen evidence.

Read-only. Verifies the working database's SHA-256 against the freeze manifest before
computing anything, so "recomputed from frozen evidence" is literally true rather than
true-because-the-bytes-happen-to-match.

Claims are classified, not lumped together:

    REPRODUCED      recomputed here from the frozen dataset, agrees to quoted precision
    NOT_RERUN       derivable from the frozen dataset but not recomputed by this script
    HISTORICAL      depended on live external API state; cannot be regenerated
    UNRECONCILABLE  provenance insufficient to reconstruct the original derivation

The distinction between NOT_RERUN and HISTORICAL matters: "this script did not compute
it" is not the same as "it cannot be computed."

Usage (from the project root):
    python scripts/reconcile_case_study.py
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKING_DB = REPO_ROOT / "research" / "data" / "markets.db"
MANIFEST = REPO_ROOT / "research" / "archive" / "v1" / "manifest.json"
BOOTSTRAP_ITERATIONS = 10_000
SEED = 42

REPRODUCED = "REPRODUCED"
NOT_RERUN = "NOT_RERUN"
HISTORICAL = "HISTORICAL"
UNRECONCILABLE = "UNRECONCILABLE"

rows_out: list[tuple[str, str, str]] = []


def record(status: str, claim: str, detail: str) -> None:
    rows_out.append((status, claim, detail))


def reproduced(claim: str, quoted: float | int, computed: float | int, tol: float = 0.0005) -> None:
    """Compare a quoted figure against a recomputation.

    Default tolerance covers rounding of a four-decimal quoted value only. A tolerance
    wide enough to hide a real disagreement would defeat the purpose.
    """
    ok = abs(quoted - computed) <= tol if isinstance(quoted, float) else quoted == computed
    record(
        REPRODUCED if ok else "MISMATCH",
        claim,
        f"quoted {quoted} / computed {computed}",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def verify_frozen() -> str:
    """Confirm the database being read is the one the manifest describes."""
    if not MANIFEST.exists():
        print(f"REFUSING: no freeze manifest at {MANIFEST}", file=sys.stderr)
        raise SystemExit(1)
    recorded = json.loads(MANIFEST.read_text())["database"]["sha256"]
    actual = sha256_file(WORKING_DB)
    if recorded != actual:
        print(
            f"REFUSING: {WORKING_DB} does not match the frozen manifest.\n"
            f"  manifest: {recorded}\n  actual:   {actual}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return actual


def main() -> int:
    digest = verify_frozen()
    print(f"frozen dataset verified: sha256 {digest[:16]}...\n")

    conn = sqlite3.connect(f"file:{WORKING_DB}?mode=ro", uri=True)
    rng = np.random.default_rng(SEED)
    one = lambda q, *a: conn.execute(q, a).fetchone()[0]  # noqa: E731

    # ---- cohort sizes ----
    reproduced("dataset markets", 9922, one("SELECT COUNT(*) FROM markets"))
    reproduced("dataset price_history rows", 2091101, one("SELECT COUNT(*) FROM price_history"))
    for label, col, cat, quoted in (
        ("Weather 6h in-band", "price_6h_before", "Weather", 368),
        ("Politics 24h in-band", "price_24h_before", "Politics", 323),
        ("Crypto 24h in-band", "price_24h_before", "Crypto", 497),
    ):
        reproduced(
            f"{label} cohort size",
            quoted,
            one(
                f"SELECT COUNT(*) FROM markets WHERE category=? "
                f"AND {col} BETWEEN 0.05 AND 0.95 AND resolved_yes IS NOT NULL",
                cat,
            ),
        )
    reproduced(
        "1h in-band cohort (vs retracted n=2,523)",
        18,
        one("SELECT COUNT(*) FROM markets WHERE price_1h_before BETWEEN 0.05 AND 0.95"),
    )

    # ---- politics decomposition ----
    prows = conn.execute(
        "SELECT question, price_24h_before, resolved_yes FROM markets "
        "WHERE category='Politics' AND price_24h_before BETWEEN 0.05 AND 0.95 "
        "AND resolved_yes IS NOT NULL ORDER BY market_id"
    ).fetchall()
    buckets: dict[str, list[float]] = defaultdict(list)
    for question, price, outcome in prows:
        low = question.lower()
        if " say " in low or 'say "' in low or "say “" in low:
            key = "say"
        elif "posts from" in low or "approval rating" in low or "number of seats" in low:
            key = "ladder"
        else:
            key = "other"
        buckets[key].append(price - outcome)

    reproduced("politics headline bias", -0.0490, float(np.mean([p - y for _, p, y in prows])))
    reproduced("politics say-market count", 223, len(buckets["say"]))
    reproduced("politics say-market share (%)", 69, round(len(buckets["say"]) / len(prows) * 100))
    reproduced("politics say-market bias", -0.0529, float(np.mean(buckets["say"])))
    reproduced("politics ladder count", 40, len(buckets["ladder"]))
    reproduced("politics ladder bias", 0.0882, float(np.mean(buckets["ladder"])))
    reproduced("politics residual count", 60, len(buckets["other"]))
    reproduced("politics residual bias", -0.1259, float(np.mean(buckets["other"])))
    reproduced(
        "politics bias, band filter removed",
        -0.0238,
        float(
            np.mean(
                [
                    p - y
                    for p, y in conn.execute(
                        "SELECT price_24h_before, resolved_yes FROM markets "
                        "WHERE category='Politics' AND price_24h_before IS NOT NULL "
                        "AND resolved_yes IS NOT NULL"
                    )
                ]
            )
        ),
    )

    # ---- weather ladders ----
    pattern = re.compile(
        r"highest temperature in (?P<city>.+?) be (?P<spec>.+?) on (?P<date>[A-Z][a-z]+ \d+)",
        re.IGNORECASE,
    )
    ladders: dict[tuple[str, str], list[tuple[float, int]]] = defaultdict(list)
    for question, price, outcome in conn.execute(
        "SELECT question, price_6h_before, resolved_yes FROM markets "
        "WHERE category='Weather' AND resolved_yes IS NOT NULL "
        "AND price_6h_before IS NOT NULL ORDER BY market_id"
    ):
        match = pattern.search(question)
        if match:
            ladders[
                (match.group("city").lower().strip(), match.group("date").lower().strip())
            ].append((price, outcome))

    in_band = lambda p: 0.05 <= p <= 0.95  # noqa: E731
    sizes = np.array([len(v) for v in ladders.values()])
    reproduced("weather ladders reconstructed", 348, len(ladders))
    reproduced("weather mean ladder size", 5.17, float(sizes.mean()), tol=0.01)
    reproduced(
        "weather unfiltered mean sum(price)",
        0.983,
        float(np.mean([sum(p for p, _ in v) for v in ladders.values()])),
        tol=0.001,
    )
    reproduced(
        "weather unfiltered mean sum(outcome)",
        0.782,
        float(np.mean([sum(y for _, y in v) for v in ladders.values()])),
        tol=0.001,
    )
    dropped = sum(
        1
        for v in ladders.values()
        if sum(y for _, y in v) > 0 and sum(y for p, y in v if in_band(p)) == 0
    )
    reproduced("weather ladders losing their winner to the filter", 227, dropped)
    reproduced("weather winner-drop rate (%)", 65.2, dropped / len(ladders) * 100, tol=0.1)
    reproduced(
        "weather band-filtered bias",
        0.1718,
        float(np.mean([p - y for v in ladders.values() for p, y in v if in_band(p)])),
    )
    reproduced(
        "weather unfiltered bias",
        0.0390,
        float(np.mean([p - y for v in ladders.values() for p, y in v])),
    )
    reproduced(
        "weather residual arithmetic (0.983-0.782)/5.17",
        0.0389,
        (0.983 - 0.782) / float(sizes.mean()),
        tol=0.0002,
    )

    # ---- crypto null ----
    crypto = np.array(
        [
            p - y
            for p, y in conn.execute(
                "SELECT price_24h_before, resolved_yes FROM markets WHERE category='Crypto' "
                "AND price_24h_before BETWEEN 0.05 AND 0.95 AND resolved_yes IS NOT NULL "
                "ORDER BY market_id"
            )
        ]
    )
    reproduced("crypto bias", 0.0104, float(crypto.mean()))
    boot = [
        rng.choice(crypto, len(crypto), replace=True).mean() for _ in range(BOOTSTRAP_ITERATIONS)
    ]
    reproduced("crypto CI lower bound", -0.0267, float(np.percentile(boot, 2.5)), tol=0.002)
    reproduced("crypto CI upper bound", 0.0475, float(np.percentile(boot, 97.5)), tol=0.002)

    # ---- look-ahead audit: full population, deterministic order ----
    market_rows = conn.execute(
        "SELECT market_id, closed_at FROM markets WHERE price_history_fetched=1 "
        "AND closed_at IS NOT NULL ORDER BY market_id"
    ).fetchall()
    future = total = 0
    for market_id, closed_at in market_rows:
        try:
            close_ts = datetime.fromisoformat(closed_at.replace("Z", "+00:00")).timestamp()
        except (ValueError, AttributeError):
            continue
        target = close_ts - 24 * 3600
        row = conn.execute(
            "SELECT timestamp FROM price_history WHERE market_id=? "
            "ORDER BY ABS(timestamp - ?) LIMIT 1",
            (market_id, target),
        ).fetchone()
        if row:
            total += 1
            future += row[0] > target
    reproduced(
        f"24h snapshots selecting a post-target tick (%) [n={total}]",
        46.1,
        round(future / total * 100, 1),
        tol=0.05,
    )
    conn.close()

    # ---- claims this script does not recompute, and why ----
    record(
        NOT_RERUN,
        "politics +20.5% return calculation",
        "derivable from this dataset via research/analysis/backtest_politics.py; not rerun here",
    )
    record(
        NOT_RERUN,
        "causal re-extraction estimate -0.0495",
        "derivable from price_history; requires the causal as-of extractor, not rerun here",
    )
    record(
        NOT_RERUN,
        "politics subgroup confidence intervals",
        "derivable; only subgroup point estimates are recomputed above",
    )
    for claim, note in (
        (
            "343 live markets, YES+NO = 1.0000",
            "live Gamma sample; recorded in commit 170902c era probes",
        ),
        (
            "close lag median +0.8h, max +11.7h (n=32)",
            "live Gamma sample; recorded in commit a2ae4b9",
        ),
        (
            "negRiskMarketID filter returns 0 of 25 matching",
            "live Gamma probe; recorded in commit 637b819 era",
        ),
        (
            "interval=1m returns 0 points at ~5 months",
            "live CLOB probe; recorded in commit a2ae4b9",
        ),
        (
            "list vs single endpoint contradiction (market 3037521)",
            "live Gamma probe; recorded in commit a2ae4b9",
        ),
        ("CLOB /prices-history matched book midpoint", "live CLOB probe on a tight-spread market"),
    ):
        record(HISTORICAL, claim, note)
    record(
        UNRECONCILABLE,
        "ROADMAP 1h cohort n=2,523",
        "current dataset yields 18; the original derivation cannot be reconstructed",
    )

    width = max(len(c) for _, c, _ in rows_out) + 2
    for status, claim, detail in rows_out:
        print(f"  {status:<15}{claim:<{width}}{detail}")

    counts = {s: sum(1 for st, _, _ in rows_out if st == s) for s in {st for st, _, _ in rows_out}}
    print("\n  " + " | ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    return 1 if counts.get("MISMATCH") else 0


if __name__ == "__main__":
    raise SystemExit(main())
