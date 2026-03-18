"""Validate the crypto overconfidence signal with statistical rigor.

Tests whether the observed miscalibration in crypto markets is:
1. Statistically significant (bootstrap confidence intervals)
2. Robust to volume weighting
3. Consistent across time periods
4. Present across price ranges

Run from project root:
    python -m research.analysis.validate_crypto_signal
"""

from dataclasses import dataclass
import sqlite3

import numpy as np

from research.pipeline.storage import DB_PATH

RNG = np.random.default_rng(42)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarketRow:
    """A single market observation for calibration analysis."""

    price: float
    resolved_yes: int
    volume_usd: float
    closed_at: str


@dataclass(frozen=True)
class CalibrationBin:
    """A single bin in a calibration breakdown."""

    range: str
    count: int
    avg_price: float
    actual_rate: float
    error: float


def load_crypto_markets(db_path: str) -> list[MarketRow]:
    """Load crypto markets with 24h-before prices in the uncertain range."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """
        SELECT price_24h_before, resolved_yes, volume_usd, closed_at
        FROM markets
        WHERE category = 'Crypto'
          AND price_24h_before BETWEEN 0.05 AND 0.95
          AND resolved_yes IS NOT NULL
          AND closed_at IS NOT NULL
          AND volume_usd IS NOT NULL
        """
    ).fetchall()
    conn.close()
    return [MarketRow(price=r[0], resolved_yes=r[1], volume_usd=r[2], closed_at=r[3]) for r in rows]


def load_all_categories(db_path: str) -> dict[str, list[MarketRow]]:
    """Load all categories for comparison."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """
        SELECT category, price_24h_before, resolved_yes, volume_usd, closed_at
        FROM markets
        WHERE price_24h_before BETWEEN 0.05 AND 0.95
          AND resolved_yes IS NOT NULL
          AND closed_at IS NOT NULL
          AND volume_usd IS NOT NULL
        """
    ).fetchall()
    conn.close()

    by_cat: dict[str, list[MarketRow]] = {}
    for cat, price, outcome, volume, closed_at in rows:
        by_cat.setdefault(cat, []).append(
            MarketRow(price=price, resolved_yes=outcome, volume_usd=volume, closed_at=closed_at)
        )
    return by_cat


# ---------------------------------------------------------------------------
# Calibration metrics
# ---------------------------------------------------------------------------


def calibration_error(
    markets: list[MarketRow],
    weights: np.ndarray | None = None,
) -> float:
    """Compute weighted mean calibration error (predicted - actual).

    Positive = overconfident (prices too high relative to outcomes).
    Negative = underconfident.
    """
    prices = np.array([m.price for m in markets])
    outcomes = np.array([m.resolved_yes for m in markets])

    if weights is None:
        return float(np.mean(prices - outcomes))
    else:
        if weights.sum() == 0:
            return float(np.mean(prices - outcomes))
        w = weights / weights.sum()
        return float(np.sum(w * (prices - outcomes)))


def calibration_error_by_bin(
    markets: list[MarketRow],
    n_bins: int = 5,
) -> list[CalibrationBin]:
    """Compute calibration error per price bin."""
    prices = np.array([m.price for m in markets])
    outcomes = np.array([m.resolved_yes for m in markets])

    bin_edges = np.linspace(0.05, 0.95, n_bins + 1)
    bins: list[CalibrationBin] = []
    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        mask = (prices >= lo) & (prices < hi) if i < n_bins - 1 else (prices >= lo) & (prices <= hi)
        if mask.sum() == 0:
            continue
        avg_price = float(prices[mask].mean())
        actual_rate = float(outcomes[mask].mean())
        bins.append(
            CalibrationBin(
                range=f"{lo:.0%}-{hi:.0%}",
                count=int(mask.sum()),
                avg_price=avg_price,
                actual_rate=actual_rate,
                error=avg_price - actual_rate,
            )
        )
    return bins


# ---------------------------------------------------------------------------
# Bootstrap confidence intervals
# ---------------------------------------------------------------------------


def bootstrap_calibration_error(
    markets: list[MarketRow],
    n_iterations: int = 10_000,
    weights: np.ndarray | None = None,
) -> tuple[float, float, float]:
    """Bootstrap the mean calibration error. Returns (mean, ci_lower, ci_upper)."""
    n = len(markets)

    prices = np.array([m.price for m in markets])
    outcomes = np.array([m.resolved_yes for m in markets])
    diffs = prices - outcomes

    idx = RNG.integers(0, n, size=(n_iterations, n))
    if weights is None:
        errors = diffs[idx].mean(axis=1)
    else:
        w = weights[idx]
        w_sums = w.sum(axis=1, keepdims=True)
        w_sums = np.where(w_sums == 0, 1.0, w_sums)
        w = w / w_sums
        errors = (w * diffs[idx]).sum(axis=1)

    mean = float(np.mean(errors))
    ci_lower = float(np.percentile(errors, 2.5))
    ci_upper = float(np.percentile(errors, 97.5))
    return mean, ci_lower, ci_upper


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------


def test_statistical_significance(markets: list[MarketRow]) -> None:
    """Test 1: Is the overconfidence statistically significant?"""
    print("=" * 70)
    print("TEST 1: Statistical Significance (Bootstrap CI)")
    print("=" * 70)

    raw_error = calibration_error(markets)
    mean, ci_lo, ci_hi = bootstrap_calibration_error(markets)

    print(f"\n  Crypto markets (n={len(markets)})")
    print(f"  Raw calibration error:  {raw_error:+.4f}")
    print(f"  Bootstrap mean:         {mean:+.4f}")
    print(f"  95% CI:                 [{ci_lo:+.4f}, {ci_hi:+.4f}]")

    if ci_lo > 0:
        print("\n  >> SIGNIFICANT: CI does not include zero.")
        print("     Crypto markets are systematically overconfident.")
    elif ci_hi < 0:
        print("\n  >> SIGNIFICANT: CI does not include zero.")
        print("     Crypto markets are systematically underconfident.")
    else:
        print("\n  >> NOT SIGNIFICANT: CI includes zero.")
        print("     Cannot reject null hypothesis of perfect calibration.")


def test_volume_weighting(markets: list[MarketRow]) -> None:
    """Test 2: Does the signal survive volume weighting?"""
    print("\n" + "=" * 70)
    print("TEST 2: Volume-Weighted Calibration Error")
    print("=" * 70)

    volumes = np.array([m.volume_usd for m in markets])

    # Unweighted
    raw_error = calibration_error(markets)
    mean_uw, ci_lo_uw, ci_hi_uw = bootstrap_calibration_error(markets)

    # Volume-weighted
    vw_error = calibration_error(markets, weights=volumes)
    mean_vw, ci_lo_vw, ci_hi_vw = bootstrap_calibration_error(markets, weights=volumes)

    print(f"\n  Unweighted:       {raw_error:+.4f}  95% CI [{ci_lo_uw:+.4f}, {ci_hi_uw:+.4f}]")
    print(f"  Volume-weighted:  {vw_error:+.4f}  95% CI [{ci_lo_vw:+.4f}, {ci_hi_vw:+.4f}]")

    if ci_lo_vw > 0:
        print("\n  >> Signal SURVIVES volume weighting.")
        print("     Not driven by low-liquidity ghost markets.")
    else:
        print("\n  >> Signal WEAKENS with volume weighting.")
        print("     Overconfidence may be concentrated in thin markets.")


def test_time_periods(markets: list[MarketRow]) -> None:
    """Test 3: Is the signal consistent across time periods?"""
    print("\n" + "=" * 70)
    print("TEST 3: Consistency Across Time Periods")
    print("=" * 70)

    # Split by month
    by_month: dict[str, list[MarketRow]] = {}
    for m in markets:
        month = m.closed_at[:7]  # "2026-01"
        by_month.setdefault(month, []).append(m)

    print(f"\n  {'Month':<10} {'N':>5} {'Error':>8} {'95% CI':>22} {'Sig?':>6}")
    print("  " + "-" * 55)

    for month in sorted(by_month):
        month_markets = by_month[month]
        if len(month_markets) < 10:
            continue
        error = calibration_error(month_markets)
        mean, ci_lo, ci_hi = bootstrap_calibration_error(month_markets, n_iterations=5000)
        sig = "YES" if ci_lo > 0 else ("yes*" if ci_hi < 0 else "no")
        n = len(month_markets)
        ci = f"[{ci_lo:>+.4f}, {ci_hi:>+.4f}]"
        print(f"  {month:<10} {n:>5} {error:>+.4f} {ci:>22} {sig:>6}")


def test_by_price_range(markets: list[MarketRow]) -> None:
    """Test 4: Where in the probability spectrum is the bias strongest?"""
    print("\n" + "=" * 70)
    print("TEST 4: Calibration Error by Price Bin")
    print("=" * 70)

    bins = calibration_error_by_bin(markets)

    print(f"\n  {'Bin':<12} {'N':>5} {'Avg Price':>10} {'Actual':>8} {'Error':>8}")
    print("  " + "-" * 47)
    for b in bins:
        print(
            f"  {b.range:<12} {b.count:>5} {b.avg_price:>9.3f} "
            f"{b.actual_rate:>7.3f} {b.error:>+7.3f}"
        )


def test_vs_other_categories(db_path: str) -> None:
    """Test 5: How does crypto compare to other categories?"""
    print("\n" + "=" * 70)
    print("TEST 5: Cross-Category Comparison")
    print("=" * 70)

    by_cat = load_all_categories(db_path)

    print(f"\n  {'Category':<12} {'N':>5} {'Error':>8} {'95% CI':>22} {'Sig?':>6}")
    print("  " + "-" * 57)

    for cat in sorted(by_cat):
        cat_markets = by_cat[cat]
        if len(cat_markets) < 30:
            continue
        error = calibration_error(cat_markets)
        mean, ci_lo, ci_hi = bootstrap_calibration_error(cat_markets, n_iterations=5000)
        sig = "YES" if ci_lo > 0 else ("yes*" if ci_hi < 0 else "no")
        ci = f"[{ci_lo:>+.4f}, {ci_hi:>+.4f}]"
        print(f"  {cat:<12} {len(cat_markets):>5} {error:>+.4f} {ci:>22} {sig:>6}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("Crypto Overconfidence Signal Validation")
    print("Data: 24h-before prices, filtered to 0.05-0.95\n")

    markets = load_crypto_markets(DB_PATH)
    print(f"Loaded {len(markets)} crypto markets\n")

    if len(markets) < 30:
        print("ERROR: Not enough crypto markets for meaningful analysis.")
        return

    test_statistical_significance(markets)
    test_volume_weighting(markets)
    test_time_periods(markets)
    test_by_price_range(markets)
    test_vs_other_categories(DB_PATH)

    print("\n" + "=" * 70)
    print("VALIDATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
