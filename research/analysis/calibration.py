"""Calibration analysis: predicted probability vs. actual resolution rate."""

import os
import sqlite3

import matplotlib.pyplot as plt

from research.pipeline.storage import DB_PATH


def load_resolved_markets(db_path: str) -> list[tuple[float, int]]:
    """Return (final_yes_price, resolved_yes) for all resolved markets."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """
        SELECT final_yes_price, resolved_yes
        FROM markets
        WHERE final_yes_price IS NOT NULL AND resolved_yes IS NOT NULL
        """
    ).fetchall()
    conn.close()
    return rows


def build_calibration_table(
    rows: list[tuple[float, int]],
) -> list[dict[str, str | float | int | None]]:
    """Bucket markets into 10 bins by final_yes_price and compute stats."""
    bins: list[dict[str, str | float | int | None]] = []
    for i in range(10):
        lo = i / 10
        hi = (i + 1) / 10
        # Include right edge in the last bin
        bucket = [
            (price, outcome)
            for price, outcome in rows
            if (lo <= price < hi) or (i == 9 and price == 1.0)
        ]
        count = len(bucket)
        if count == 0:
            bins.append(
                {
                    "range": f"{lo:.0%}-{hi:.0%}",
                    "count": 0,
                    "avg_predicted": None,
                    "actual_rate": None,
                }
            )
        else:
            avg_predicted = sum(p for p, _ in bucket) / count
            actual_rate = sum(o for _, o in bucket) / count
            bins.append(
                {
                    "range": f"{lo:.0%}-{hi:.0%}",
                    "count": count,
                    "avg_predicted": avg_predicted,
                    "actual_rate": actual_rate,
                }
            )
    return bins


def print_table(bins: list[dict[str, str | float | int | None]]) -> None:
    """Print a text-based calibration table."""
    header = f"{'Bin':<12} {'Count':>6} {'Avg Predicted':>14} {'Actual Rate':>12}"
    print(header)
    print("-" * len(header))
    for b in bins:
        count = b["count"]
        if count == 0:
            print(f"{b['range']:<12} {0:>6}            -            -")
        else:
            print(
                f"{b['range']:<12} {count:>6} {b['avg_predicted']:>13.1%} {b['actual_rate']:>11.1%}"
            )


def save_calibration_plot(
    bins: list[dict[str, str | float | int | None]], output_path: str
) -> None:
    """Save a calibration curve plot."""
    predicted: list[float] = []
    actual: list[float] = []
    for b in bins:
        cnt = b["count"]
        if isinstance(cnt, int) and cnt > 0:
            predicted.append(float(b["avg_predicted"]))  # type: ignore[arg-type]
            actual.append(float(b["actual_rate"]))  # type: ignore[arg-type]

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.plot([0, 1], [0, 1], "k--", linewidth=1, label="Perfect calibration")
    ax.plot(predicted, actual, "o-", color="#5865F2", linewidth=2, label="Model")
    ax.set_xlabel("Average Predicted Probability")
    ax.set_ylabel("Actual Resolution Rate")
    ax.set_title("Polymarket Calibration Curve")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal")
    ax.legend()
    ax.grid(True, alpha=0.3)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\nPlot saved to {output_path}")


def load_preresolution_markets(
    db_path: str,
) -> dict[str, list[tuple[float, int]]]:
    """Return {horizon: [(price, resolved_yes), ...]} for pre-resolution horizons.

    Only includes markets where the price at that horizon is between 0.05 and 0.95.
    """
    conn = sqlite3.connect(db_path)
    horizons = {
        "24h before": "price_24h_before",
        "6h before": "price_6h_before",
        "1h before": "price_1h_before",
    }
    result: dict[str, list[tuple[float, int]]] = {}
    for label, col in horizons.items():
        rows = conn.execute(
            f"""
            SELECT {col}, resolved_yes
            FROM markets
            WHERE {col} IS NOT NULL AND resolved_yes IS NOT NULL
              AND {col} BETWEEN 0.05 AND 0.95
            """
        ).fetchall()
        result[label] = rows
    conn.close()
    return result


def save_preresolution_calibration_plot(
    data: dict[str, list[tuple[float, int]]], output_path: str
) -> None:
    """Save a calibration plot with curves for each pre-resolution time horizon."""
    colors = {"24h before": "#E74C3C", "6h before": "#F39C12", "1h before": "#2ECC71"}

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.plot([0, 1], [0, 1], "k--", linewidth=1, label="Perfect calibration")

    for label in ("24h before", "6h before", "1h before"):
        rows = data[label]
        bins = build_calibration_table(rows)
        predicted: list[float] = []
        actual: list[float] = []
        counts: list[int] = []
        for b in bins:
            cnt = b["count"]
            if isinstance(cnt, int) and cnt > 0:
                predicted.append(float(b["avg_predicted"]))  # type: ignore[arg-type]
                actual.append(float(b["actual_rate"]))  # type: ignore[arg-type]
                counts.append(cnt)

        n = len(rows)
        ax.plot(
            predicted,
            actual,
            "o-",
            color=colors[label],
            linewidth=2,
            label=f"{label} (n={n})",
        )
        for px, py, c in zip(predicted, actual, counts, strict=True):
            ax.annotate(
                str(c),
                (px, py),
                textcoords="offset points",
                xytext=(0, 8),
                ha="center",
                fontsize=7,
                color=colors[label],
            )

    ax.set_xlabel("Average Predicted Probability")
    ax.set_ylabel("Actual Resolution Rate")
    ax.set_title("Polymarket Calibration: Pre-Resolution Prices")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal")
    ax.legend()
    ax.grid(True, alpha=0.3)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\nPlot saved to {output_path}")


def save_category_calibration_plot(db_path: str, output_path: str) -> None:
    """Save a calibration plot with a separate curve per category (min 50 markets)."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """
        SELECT category, price_24h_before, resolved_yes
        FROM markets
        WHERE price_24h_before BETWEEN 0.05 AND 0.95
          AND resolved_yes IS NOT NULL
        ORDER BY category
        """
    ).fetchall()
    conn.close()

    # Group by category
    by_category: dict[str, list[tuple[float, int]]] = {}
    for category, price, outcome in rows:
        by_category.setdefault(category, []).append((price, outcome))

    # Filter to categories with >= 50 markets
    eligible = {cat: pts for cat, pts in by_category.items() if len(pts) >= 50}
    if not eligible:
        print("No categories with >= 50 markets; skipping category calibration plot.")
        return

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.plot([0, 1], [0, 1], "k--", linewidth=1, label="Perfect calibration")

    for cat in sorted(eligible):
        bins = build_calibration_table(eligible[cat])
        predicted: list[float] = []
        actual: list[float] = []
        for b in bins:
            cnt = b["count"]
            if isinstance(cnt, int) and cnt > 0:
                predicted.append(float(b["avg_predicted"]))  # type: ignore[arg-type]
                actual.append(float(b["actual_rate"]))  # type: ignore[arg-type]
        n = len(eligible[cat])
        ax.plot(predicted, actual, "o-", linewidth=2, label=f"{cat} (n={n})")

    ax.set_xlabel("Average Predicted Probability")
    ax.set_ylabel("Actual Resolution Rate")
    ax.set_title("Polymarket Calibration by Category (24h before)")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\nPlot saved to {output_path}")


def main() -> None:
    rows = load_resolved_markets(DB_PATH)
    print(f"Loaded {len(rows)} resolved markets\n")
    bins = build_calibration_table(rows)
    print_table(bins)

    plot_path = os.path.join(os.path.dirname(__file__), "calibration_curve.png")
    save_calibration_plot(bins, plot_path)

    # Pre-resolution calibration curves
    preresolution_data = load_preresolution_markets(DB_PATH)
    for label, horizon_rows in preresolution_data.items():
        print(f"\n{label}: {len(horizon_rows)} markets (filtered 0.05-0.95)")

    preresolution_path = os.path.join(
        os.path.dirname(__file__), "calibration_curve_preresolution.png"
    )
    save_preresolution_calibration_plot(preresolution_data, preresolution_path)

    # Category-level calibration curves
    category_path = os.path.join(os.path.dirname(__file__), "calibration_curve_by_category.png")
    save_category_calibration_plot(DB_PATH, category_path)


if __name__ == "__main__":
    main()
