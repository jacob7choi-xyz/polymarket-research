"""
Position tracking for arbitrage trades.

Responsibilities:
- Track open positions (active arbitrage trades)
- Calculate unrealized P&L
- Track realized P&L (closed positions)
- Provide position summaries

Interview Point - Why Separate from Executor?
- Single Responsibility: Tracking vs executing
- Reusability: Multiple executors can share tracker
- Persistence: Easy to swap in database-backed tracker
- Testability: Can test tracking logic independently
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from ..monitoring.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Position:
    """
    Represents an open arbitrage position.

    Interview Point - Dataclass vs Pydantic:
    - Dataclass: Simpler, no validation overhead
    - Pydantic: Validation, serialization, API responses
    - Use dataclass for internal state
    - Use Pydantic for boundaries (API, config, DB)
    """

    market_id: str
    position_size: Decimal  # USD invested
    yes_price: Decimal  # Price paid for YES token
    no_price: Decimal  # Price paid for NO token
    entry_time: datetime
    total_cost: Decimal = field(init=False)

    def __post_init__(self) -> None:
        """
        Calculate total cost after initialization.

        Why post_init?
        - Derived field (calculated from other fields)
        - Don't require caller to provide
        - Ensures consistency (cost = size * (yes + no))
        """
        self.total_cost = self.position_size * (self.yes_price + self.no_price)

    @property
    def expected_profit(self) -> Decimal:
        """
        Expected profit when market resolves.

        Arbitrage math:
        - Buy YES for yes_price
        - Buy NO for no_price
        - One outcome wins → payout = position_size
        - Profit = payout - total_cost

        Interview Point - Guaranteed Profit:
        - No market risk (don't care which outcome wins)
        - Only execution risk (failure to execute)
        - If YES + NO < 1.0 → guaranteed profit
        """
        return self.position_size - self.total_cost

    @property
    def roi_percent(self) -> Decimal:
        """Return on investment as percentage."""
        if self.total_cost == 0:
            return Decimal("0")
        return (self.expected_profit / self.total_cost) * Decimal("100")


class PositionTracker:
    """
    Tracks all arbitrage positions and calculates P&L.

    Interview Point - State Management:
    - In-memory: Fast, simple, good for single instance
    - Database: Persistent, scalable, survives restarts
    - Redis: Fast, distributed, shared across instances
    - Start simple (in-memory), add persistence later
    """

    def __init__(self) -> None:
        """Initialize position tracker."""
        self.positions: dict[str, Position] = {}
        self.total_realized_pnl: Decimal = Decimal("0")
        self.closed_positions_count: int = 0

        logger.info("position_tracker_initialized")

    def add_position(
        self,
        market_id: str,
        position_size: Decimal,
        yes_price: Decimal,
        no_price: Decimal,
        entry_time: datetime | None = None,
    ) -> None:
        """
        Add new position.

        Args:
            market_id: Unique market identifier
            position_size: Position size in USD
            yes_price: Price paid for YES token
            no_price: Price paid for NO token
            entry_time: When position was opened (defaults to now)
        """
        entry_time = entry_time or datetime.now()

        position = Position(
            market_id=market_id,
            position_size=position_size,
            yes_price=yes_price,
            no_price=no_price,
            entry_time=entry_time,
        )

        self.positions[market_id] = position

        logger.info(
            "position_opened",
            market_id=market_id,
            position_size=float(position_size),
            yes_price=float(yes_price),
            no_price=float(no_price),
            total_cost=float(position.total_cost),
            expected_profit=float(position.expected_profit),
            roi_percent=float(position.roi_percent),
        )

    def close_position(self, market_id: str, realized_pnl: Decimal) -> None:
        """
        Close position and realize P&L.

        Args:
            market_id: Market identifier
            realized_pnl: Actual profit/loss (may differ from expected)

        Interview Point - Realized vs Unrealized P&L:
        - Unrealized: Paper profit (position still open)
        - Realized: Actual profit (position closed, money in hand)
        - Important for accounting and performance tracking
        """
        if market_id not in self.positions:
            logger.warning(
                "position_not_found",
                market_id=market_id,
                action="close_position",
            )
            return

        position = self.positions[market_id]
        del self.positions[market_id]

        self.total_realized_pnl += realized_pnl
        self.closed_positions_count += 1

        logger.info(
            "position_closed",
            market_id=market_id,
            realized_pnl=float(realized_pnl),
            expected_pnl=float(position.expected_profit),
            difference=float(realized_pnl - position.expected_profit),
            total_realized_pnl=float(self.total_realized_pnl),
            closed_count=self.closed_positions_count,
        )

    def get_position(self, market_id: str) -> Position | None:
        """Get position by market ID."""
        return self.positions.get(market_id)

    def get_open_positions(self) -> list[Position]:
        """Get all open positions."""
        return list(self.positions.values())

    def get_total_unrealized_pnl(self) -> Decimal:
        """
        Calculate total unrealized P&L across all open positions.

        Interview Point - Portfolio Management:
        - Track total exposure
        - Monitor aggregate risk
        - Helpful for capital allocation decisions
        """
        total = Decimal("0")
        for position in self.positions.values():
            total += position.expected_profit
        return total

    def get_summary(self) -> dict[str, float]:
        """
        Get summary statistics.

        Returns:
            Dict with:
            - open_positions: Number of open positions
            - total_unrealized_pnl: Unrealized profit
            - total_realized_pnl: Realized profit
            - closed_positions_count: Number of closed positions
            - total_pnl: Realized + unrealized
        """
        unrealized = self.get_total_unrealized_pnl()
        total = self.total_realized_pnl + unrealized

        summary = {
            "open_positions": len(self.positions),
            "total_unrealized_pnl": float(unrealized),
            "total_realized_pnl": float(self.total_realized_pnl),
            "closed_positions_count": self.closed_positions_count,
            "total_pnl": float(total),
        }

        logger.debug("position_summary", **summary)

        return summary


# Example usage for documentation
if __name__ == "__main__":
    print("=== Position Tracker Demo ===\n")

    tracker = PositionTracker()

    # Add positions
    tracker.add_position(
        market_id="0xmarket1",
        position_size=Decimal("100"),
        yes_price=Decimal("0.48"),
        no_price=Decimal("0.48"),
    )

    tracker.add_position(
        market_id="0xmarket2",
        position_size=Decimal("50"),
        yes_price=Decimal("0.45"),
        no_price=Decimal("0.50"),
    )

    # Get summary
    summary = tracker.get_summary()
    print(f"Open positions: {summary['open_positions']}")
    print(f"Total unrealized P&L: ${summary['total_unrealized_pnl']:.2f}")

    # List positions
    print("\nOpen Positions:")
    for position in tracker.get_open_positions():
        print(f"  {position.market_id}:")
        print(f"    Size: ${position.position_size}")
        print(f"    Cost: ${position.total_cost}")
        print(f"    Expected profit: ${position.expected_profit} ({position.roi_percent:.2f}%)")

    # Close position
    print("\nClosing market1...")
    tracker.close_position("0xmarket1", realized_pnl=Decimal("4.00"))

    # Updated summary
    summary = tracker.get_summary()
    print(f"\nAfter closing:")
    print(f"Open positions: {summary['open_positions']}")
    print(f"Realized P&L: ${summary['total_realized_pnl']:.2f}")
    print(f"Unrealized P&L: ${summary['total_unrealized_pnl']:.2f}")
    print(f"Total P&L: ${summary['total_pnl']:.2f}")
