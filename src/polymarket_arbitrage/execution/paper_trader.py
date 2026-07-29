"""
Paper trading executor - simulates trade execution without real money.

Why Paper Trading?
- Safety: Test strategy without financial risk
- Validation: Prove system works before risking capital
- Tuning: Optimize parameters based on simulated performance
- Learning: Build confidence in system

Interview Point - Staged Rollout:
1. Paper trading (simulated)
2. Live trading with small capital
3. Full production with larger capital
- Each stage builds confidence
- Fail fast without big losses
"""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from ..domain.models import ArbitrageOpportunity, ResolutionStatus
from ..monitoring.logging import get_logger
from .position_tracker import PositionTracker

logger = get_logger(__name__)


class PaperTrader:
    """
    Simulates arbitrage trade execution and tracks P&L.

    Interview Point - Why Separate Paper/Live Trader?
    - Polymorphism: Same interface, different implementations
    - Safety: Clear distinction between real and simulated
    - Testing: Use paper trader in tests
    - Gradual rollout: Start paper, switch to live when confident
    """

    def __init__(
        self,
        initial_capital: Decimal = Decimal("10000"),
        position_tracker: PositionTracker | None = None,
    ):
        """
        Initialize paper trader.

        Args:
            initial_capital: Starting capital in USD
            position_tracker: Optional position tracker (creates new if None)

        Interview Point - Dependency Injection:
        - position_tracker injected (not created internally)
        - Testability: Can inject mock tracker
        - Flexibility: Share tracker across multiple executors
        """
        self.initial_capital = initial_capital
        self.available_capital = initial_capital
        self.position_tracker = position_tracker or PositionTracker()
        self._trade_count = 0

        logger.info(
            "paper_trader_initialized",
            initial_capital=float(initial_capital),
        )

    async def execute_arbitrage(
        self,
        opportunity: ArbitrageOpportunity,
    ) -> bool:
        """
        Simulate arbitrage execution.

        Process:
        1. Check capital available
        2. Calculate costs
        3. Update capital
        4. Record position
        5. Log trade

        Args:
            opportunity: Detected arbitrage opportunity

        Returns:
            True if execution successful, False otherwise

        Interview Point - Why async?
        - Interface consistency: Live trader needs async (API calls)
        - Polymorphism: Paper and live traders same signature
        - Future-proofing: Can add async operations (DB writes)
        """
        market = opportunity.market
        position_size = opportunity.recommended_position_size

        # Adjust position size to available capital
        # Interview Point - Capital Management:
        # - Don't overcommit capital
        # - Graceful degradation (take smaller position if needed)
        # - Better partial execution than none
        if position_size > self.available_capital:
            if self.available_capital < Decimal("1"):
                # Insufficient capital even for minimum trade
                logger.warning(
                    "insufficient_capital",
                    required=float(position_size),
                    available=float(self.available_capital),
                    market_id=market.market_id,
                )
                return False

            # Reduce position to available capital
            original_size = position_size
            position_size = self.available_capital
            logger.info(
                "position_size_reduced",
                original=float(original_size),
                adjusted=float(position_size),
                available_capital=float(self.available_capital),
            )

        # Calculate costs
        # Interview Point - Arbitrage Execution:
        # - Buy YES token: position_size * yes_price
        # - Buy NO token: position_size * no_price
        # - Total cost: position_size * (yes_price + no_price)
        # - Expected payout: position_size (one outcome wins)
        # - Profit: payout - cost
        yes_cost = position_size * market.yes_token.price
        no_cost = position_size * market.no_token.price
        total_cost = yes_cost + no_cost

        # Expected payout when market resolves
        # One of YES or NO will win → receive position_size
        expected_payout = position_size
        expected_profit = expected_payout - total_cost
        expected_roi = (expected_profit / total_cost * 100) if total_cost > 0 else Decimal("0")

        # Update capital
        self.available_capital -= total_cost
        self._trade_count += 1

        # Record position
        self.position_tracker.add_position(
            market_id=market.market_id,
            bundle_quantity=position_size,
            yes_price=market.yes_token.price,
            no_price=market.no_token.price,
            entry_time=opportunity.detected_at,
            market_end_at=market.end_date,
        )

        # Log execution
        # Interview Point - Structured Logging for Analysis:
        # - JSON format → easy to parse and analyze
        # - All trade details → can reconstruct performance
        # - Exportable → can analyze in spreadsheet/database
        logger.info(
            "paper_trade_executed",
            trade_id=self._trade_count,
            market_id=market.market_id,
            question=market.question,
            yes_price=float(market.yes_token.price),
            no_price=float(market.no_token.price),
            total_probability=float(market.total_implied_probability),
            position_size=float(position_size),
            yes_cost=float(yes_cost),
            no_cost=float(no_cost),
            total_cost=float(total_cost),
            expected_payout=float(expected_payout),
            expected_profit=float(expected_profit),
            expected_roi_percent=float(expected_roi),
            remaining_capital=float(self.available_capital),
            liquidity=float(market.liquidity),
            volume=float(market.volume),
        )

        return True

    def settle_position(self, market_id: str, status: ResolutionStatus) -> bool:
        """Settle one position, but only on evidence that its market actually resolved.

        Settlement requires ``ResolutionStatus.RESOLVED`` and nothing weaker. A market's
        end date will not do: measured against the live API, 100% of markets close
        *after* their end date, median 0.8 hours later and up to 11.7 hours in a
        32-market sample. Settling on the end date would credit capital and realize P&L
        while the position was still unredeemable, manufacturing capital the portfolio
        does not have and inflating capacity for subsequent trades.

        The bundle *amount* needs no outcome data -- YES + NO redeems for $1 either way.
        The *timing* is what needs evidence, and this method refuses to guess it. An
        UNRESOLVED or UNKNOWN status leaves the position open.

        Obtaining the status is the caller's job. This module has no API dependency, and
        inventing an oracle here would put the same unverified assumption back one layer
        down.

        Args:
            market_id: Market whose position should settle.
            status: Authoritative resolution status for that market.

        Returns:
            True if the position settled, False if it was left open or does not exist.
        """
        if status is not ResolutionStatus.RESOLVED:
            logger.debug(
                "settlement_skipped",
                market_id=market_id,
                status=str(status),
                reason="market not confirmed resolved",
            )
            return False

        position = self.position_tracker.get_position(market_id)
        if position is None:
            logger.warning("settlement_no_position", market_id=market_id)
            return False

        payout = position.payout
        realized_pnl = payout - position.total_cost
        self.available_capital += payout
        self.position_tracker.close_position(market_id, realized_pnl)
        logger.info(
            "position_settled",
            market_id=market_id,
            payout=float(payout),
            cost_basis=float(position.total_cost),
            realized_pnl=float(realized_pnl),
            available_capital=float(self.available_capital),
        )
        return True

    def settle_positions(self, statuses: Mapping[str, ResolutionStatus]) -> int:
        """Settle every position whose market is confirmed resolved.

        Args:
            statuses: Resolution status per market id. Markets absent from the mapping
                are treated as UNKNOWN and left open.

        Returns:
            Number of positions settled.
        """
        settled = 0
        for position in self.position_tracker.get_open_positions():
            status = statuses.get(position.market_id, ResolutionStatus.UNKNOWN)
            if self.settle_position(position.market_id, status):
                settled += 1

        if settled:
            logger.info(
                "settlement_cycle_complete",
                positions_settled=settled,
                total_realized_pnl=float(self.position_tracker.total_realized_pnl),
                available_capital=float(self.available_capital),
            )
        return settled

    def get_performance_summary(self) -> dict[str, float]:
        """
        Get performance metrics for analysis.

        Returns:
            Dict with:
            - initial_capital: Starting capital
            - available_capital: Current available capital
            - capital_deployed: Amount currently in positions
            - trades_executed: Number of trades
            - open_positions: Number of open positions
            - total_unrealized_pnl: Unrealized profit
            - total_realized_pnl: Realized profit
            - total_pnl: Total profit (realized + unrealized)
            - roi_percent: Return on investment %

        Interview Point - Performance Metrics:
        - Track multiple dimensions (capital, trades, P&L, ROI)
        - Helps evaluate strategy effectiveness
        - Can export for analysis (Excel, Jupyter, etc.)
        """
        position_summary = self.position_tracker.get_summary()

        # Sum the open cost bases rather than subtracting available from initial. The
        # subtraction only agrees while realized P&L is zero: once a position settles at a
        # profit, available capital exceeds initial minus deployed, and the difference is
        # gains rather than deployment. That error was unreachable before settlement
        # existed, because realized P&L was permanently zero.
        capital_deployed = sum(
            (p.total_cost for p in self.position_tracker.get_open_positions()),
            Decimal("0"),
        )
        total_pnl = Decimal(str(position_summary["total_pnl"]))
        roi_percent = (
            (total_pnl / self.initial_capital * 100) if self.initial_capital > 0 else Decimal("0")
        )

        summary = {
            "initial_capital": float(self.initial_capital),
            "available_capital": float(self.available_capital),
            "capital_deployed": float(capital_deployed),
            "capital_utilization_percent": float(
                (capital_deployed / self.initial_capital * 100) if self.initial_capital > 0 else 0
            ),
            "trades_executed": self._trade_count,
            "open_positions": position_summary["open_positions"],
            "total_unrealized_pnl": position_summary["total_unrealized_pnl"],
            "total_realized_pnl": position_summary["total_realized_pnl"],
            "total_pnl": position_summary["total_pnl"],
            "roi_percent": float(roi_percent),
        }

        logger.debug("performance_summary", **summary)

        return summary

    def reset(self) -> None:
        """
        Reset paper trader to initial state.

        Use cases:
        - Testing different strategies
        - Restarting simulation
        - Backtesting with fresh capital
        """
        self.available_capital = self.initial_capital
        self._trade_count = 0
        self.position_tracker = PositionTracker()

        logger.info(
            "paper_trader_reset",
            initial_capital=float(self.initial_capital),
        )


# Example usage for documentation
if __name__ == "__main__":
    """
    Example: Using PaperTrader to simulate trades

    Interview Point - Realistic Simulation:
    - Matches real trading constraints (capital, sizing)
    - Tracks all metrics (P&L, ROI, positions)
    - Logs for analysis
    - Can validate strategy before risking capital
    """
    import asyncio

    from ..domain.models import Market, Token

    async def demo_paper_trading() -> None:
        print("=== Paper Trading Demo ===\n")

        # Initialize trader
        trader = PaperTrader(initial_capital=Decimal("1000"))

        # Create arbitrage opportunity
        market = Market(
            market_id="0xdemo",
            condition_id="0xcond",
            question="Will BTC reach $100k?",
            yes_token=Token(
                token_id="0xyes",
                outcome="Yes",
                price=Decimal("0.48"),
            ),
            no_token=Token(
                token_id="0xno",
                outcome="No",
                price=Decimal("0.48"),
            ),
            volume=Decimal("50000"),
            liquidity=Decimal("10000"),
            end_date=datetime(2025, 12, 31),
            active=True,
        )

        opportunity = ArbitrageOpportunity(
            market=market,
            detected_at=datetime.now(),
            expected_profit_per_dollar=market.arbitrage_profit_per_dollar,
            recommended_position_size=Decimal("100"),
        )

        # Execute trade
        print("Executing arbitrage trade...")
        success = await trader.execute_arbitrage(opportunity)
        print(f"Execution successful: {success}\n")

        # Get performance
        performance = trader.get_performance_summary()
        print("Performance Summary:")
        print(f"  Initial capital: ${performance['initial_capital']:.2f}")
        print(f"  Available capital: ${performance['available_capital']:.2f}")
        print(f"  Capital deployed: ${performance['capital_deployed']:.2f}")
        print(f"  Trades executed: {performance['trades_executed']}")
        print(f"  Open positions: {performance['open_positions']}")
        print(f"  Total P&L: ${performance['total_pnl']:.2f}")
        print(f"  ROI: {performance['roi_percent']:.2f}%")

    # Run demo
    asyncio.run(demo_paper_trading())
