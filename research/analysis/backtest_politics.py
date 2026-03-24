"""Backtest a strategy that exploits political market underconfidence.

Strategy: At 24h before resolution, buy YES on political markets priced
in the 0.20-0.80 range (where underconfidence is strongest). Measure
net returns after Polymarket's ~2% fee on winnings.

Run from project root:
    python -m research.analysis.backtest_politics
"""

from dataclasses import dataclass, field
import sqlite3

import numpy as np

from research.pipeline.storage import DB_PATH

RNG = np.random.default_rng(42)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Trade:
    """A single simulated trade."""

    market_id: str
    question: str
    entry_price: float
    resolved_yes: int
    volume_usd: float
    closed_at: str


def load_politics_trades(
    db_path: str,
    price_lo: float = 0.20,
    price_hi: float = 0.80,
) -> list[Trade]:
    """Load political markets eligible for the strategy."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """
        SELECT market_id, question, price_24h_before, resolved_yes,
               volume_usd, closed_at
        FROM markets
        WHERE category = 'Politics'
          AND price_24h_before BETWEEN ? AND ?
          AND resolved_yes IS NOT NULL
          AND closed_at IS NOT NULL
          AND volume_usd IS NOT NULL
        ORDER BY closed_at
        """,
        (price_lo, price_hi),
    ).fetchall()
    conn.close()
    return [
        Trade(
            market_id=r[0],
            question=r[1],
            entry_price=r[2],
            resolved_yes=r[3],
            volume_usd=r[4],
            closed_at=r[5],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

FEE_RATE = 0.02  # Polymarket ~2% fee on winnings
BET_SIZE = 100.0  # $100 per trade (flat sizing)


@dataclass
class BacktestResult:
    """Results of a backtest run."""

    n_trades: int = 0
    n_wins: int = 0
    gross_pnl: float = 0.0
    total_fees: float = 0.0
    net_pnl: float = 0.0
    trade_pnls: list[float] = field(default_factory=list)
    capital_curve: list[float] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return self.n_wins / self.n_trades if self.n_trades > 0 else 0.0

    @property
    def net_roi_pct(self) -> float:
        total_risked = self.n_trades * BET_SIZE
        return (self.net_pnl / total_risked * 100) if total_risked > 0 else 0.0

    @property
    def avg_trade_pnl(self) -> float:
        return self.net_pnl / self.n_trades if self.n_trades > 0 else 0.0

    @property
    def sharpe_ratio(self) -> float:
        if len(self.trade_pnls) < 2:
            return 0.0
        arr = np.array(self.trade_pnls)
        std = float(arr.std())
        if std == 0:
            return 0.0
        return float(arr.mean() / std)

    @property
    def max_drawdown_pct(self) -> float:
        if not self.capital_curve:
            return 0.0
        curve = np.array(self.capital_curve)
        peak = np.maximum.accumulate(curve)
        drawdown = (peak - curve) / np.where(peak == 0, 1.0, peak)
        return float(drawdown.max() * 100)


def run_backtest(
    trades: list[Trade],
    bet_size: float = BET_SIZE,
    fee_rate: float = FEE_RATE,
) -> BacktestResult:
    """Simulate buying YES on each trade at entry_price.

    Payoff per trade:
    - WIN (resolved YES):  payout = bet_size / entry_price
                           gross_profit = payout - bet_size
                           fee = gross_profit * fee_rate
                           net = gross_profit - fee
    - LOSE (resolved NO):  net = -bet_size
    """
    result = BacktestResult()
    cumulative_pnl = 0.0

    for trade in trades:
        result.n_trades += 1

        if trade.resolved_yes == 1:
            # Win: bought at entry_price, pays out $1 per share
            payout = bet_size / trade.entry_price
            gross_profit = payout - bet_size
            fee = gross_profit * fee_rate
            net = gross_profit - fee

            result.n_wins += 1
            result.gross_pnl += gross_profit
            result.total_fees += fee
        else:
            # Lose: lose entire bet
            net = -bet_size
            result.gross_pnl -= bet_size

        result.net_pnl += net
        result.trade_pnls.append(net)
        cumulative_pnl += net
        result.capital_curve.append(cumulative_pnl)

    return result


# ---------------------------------------------------------------------------
# Bootstrap confidence interval on net ROI
# ---------------------------------------------------------------------------


def bootstrap_net_roi(
    trade_pnls: list[float],
    n_iterations: int = 10_000,
) -> tuple[float, float, float]:
    """Bootstrap the net ROI. Returns (mean, ci_lower, ci_upper)."""
    arr = np.array(trade_pnls)
    n = len(arr)
    idx = RNG.integers(0, n, size=(n_iterations, n))
    means = arr[idx].mean(axis=1)
    roi_pcts = means / BET_SIZE * 100

    return (
        float(np.mean(roi_pcts)),
        float(np.percentile(roi_pcts, 2.5)),
        float(np.percentile(roi_pcts, 97.5)),
    )


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def print_results(result: BacktestResult, label: str = "BACKTEST") -> None:
    """Print backtest results."""
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    print(f"  Trades:          {result.n_trades}")
    print(f"  Wins:            {result.n_wins} ({result.win_rate:.1%})")
    print(f"  Gross P&L:       ${result.gross_pnl:>+,.2f}")
    print(f"  Fees paid:       ${result.total_fees:>,.2f}")
    print(f"  Net P&L:         ${result.net_pnl:>+,.2f}")
    print(f"  Net ROI:         {result.net_roi_pct:>+.2f}%")
    print(f"  Avg trade P&L:   ${result.avg_trade_pnl:>+.2f}")
    print(f"  Sharpe ratio:    {result.sharpe_ratio:.3f}")
    print(f"  Max drawdown:    {result.max_drawdown_pct:.1f}%")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("Politics Underconfidence Backtest")
    print("Strategy: Buy YES on political markets priced 0.20-0.80")
    print(f"Bet size: ${BET_SIZE:.0f} flat | Fee: {FEE_RATE:.0%} on winnings")

    # --- Full backtest ---
    trades = load_politics_trades(DB_PATH, price_lo=0.20, price_hi=0.80)
    print(f"\nLoaded {len(trades)} eligible trades")

    if len(trades) < 10:
        print("ERROR: Not enough trades for meaningful backtest.")
        return

    result = run_backtest(trades)
    print_results(result, "FULL BACKTEST (0.20-0.80)")

    # Bootstrap CI on net ROI
    mean_roi, ci_lo, ci_hi = bootstrap_net_roi(result.trade_pnls)
    print(f"\n  Bootstrap ROI:   {mean_roi:>+.2f}%")
    print(f"  95% CI:          [{ci_lo:>+.2f}%, {ci_hi:>+.2f}%]")
    if ci_lo > 0:
        print("  >> PROFITABLE: CI does not include zero.")
    else:
        print("  >> NOT PROFITABLE: CI includes zero.")

    # --- Sweet spot: 0.40-0.80 where edge is strongest ---
    sweet_trades = load_politics_trades(DB_PATH, price_lo=0.40, price_hi=0.80)
    if len(sweet_trades) >= 10:
        sweet_result = run_backtest(sweet_trades)
        print_results(sweet_result, "SWEET SPOT (0.40-0.80)")

        mean_roi_s, ci_lo_s, ci_hi_s = bootstrap_net_roi(
            sweet_result.trade_pnls,
        )
        print(f"\n  Bootstrap ROI:   {mean_roi_s:>+.2f}%")
        print(f"  95% CI:          [{ci_lo_s:>+.2f}%, {ci_hi_s:>+.2f}%]")
        if ci_lo_s > 0:
            print("  >> PROFITABLE: CI does not include zero.")
        else:
            print("  >> NOT PROFITABLE: CI includes zero.")

    # --- Monthly breakdown ---
    print(f"\n{'=' * 60}")
    print("  MONTHLY BREAKDOWN")
    print(f"{'=' * 60}")
    by_month: dict[str, list[Trade]] = {}
    for t in trades:
        month = t.closed_at[:7]
        by_month.setdefault(month, []).append(t)

    print(f"\n  {'Month':<10} {'N':>5} {'Win%':>6} {'Net P&L':>10} {'ROI':>8}")
    print("  " + "-" * 43)
    for month in sorted(by_month):
        month_trades = by_month[month]
        r = run_backtest(month_trades)
        print(
            f"  {month:<10} {r.n_trades:>5} {r.win_rate:>5.0%}"
            f" ${r.net_pnl:>+9.2f} {r.net_roi_pct:>+7.2f}%"
        )

    print(f"\n{'=' * 60}")
    print("  BACKTEST COMPLETE")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
