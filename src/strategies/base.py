"""
Base strategy interface and common utilities.

Pattern: Strategy Pattern (Gang of Four)
- Allows swapping arbitrage detection algorithms
- Example strategies: PriceDiscrepancyStrategy, VolatilityArbitrageStrategy
- All strategies share common interface but different implementations

Interview Point - When to use ABC vs Protocol:
- ABC: When you have shared implementation (filtering, scoring logic)
- Protocol: When you need pure interface (repository, executor)
- Here: ABC because strategies share filtering logic
"""

from abc import ABC, abstractmethod
from decimal import Decimal

from ..config.constants import MAX_POSITION_PCT_OF_LIQUIDITY
from ..domain.models import ArbitrageOpportunity, Market
from ..monitoring.logging import get_logger

logger = get_logger(__name__)


class ArbitrageStrategy(ABC):
    """
    Base class for arbitrage detection strategies.

    Why abstract base class?
    - Shared implementation: Filtering and scoring logic
    - Template method pattern: Subclasses implement detect logic
    - Type safety: Ensures all strategies have same interface

    Subclasses must implement:
    - detect_opportunities(): Core detection logic

    Subclasses can override:
    - calculate_opportunity_score(): Custom scoring
    - _should_skip_market(): Custom filtering
    """

    @abstractmethod
    async def detect_opportunities(
        self,
        markets: list[Market],
    ) -> list[ArbitrageOpportunity]:
        """
        Subclasses implement detection logic.

        Args:
            markets: List of markets to analyze

        Returns:
            List of detected opportunities (sorted by quality)

        Interview Point - Template Method Pattern:
        - Base class defines structure (filter → detect → score → sort)
        - Subclasses fill in specific detection algorithm
        - Ensures consistent behavior across strategies
        """
        pass

    def _should_skip_market(self, market: Market, reason_key: str) -> str | None:
        """
        Common market filtering logic.

        Returns reason if should skip, None if should process.

        Interview Point - DRY Principle:
        - Filtering logic shared across all strategies
        - Centralized in base class (single source of truth)
        - Subclasses can extend but shouldn't duplicate
        """
        # Skip inactive markets
        if not market.active:
            return "market_inactive"

        # Skip expired markets
        if market.is_expired:
            return "market_expired"

        # Subclass-specific filtering done in subclass
        return None

    def _calculate_opportunity_score(self, market: Market) -> Decimal:
        """
        Score opportunity quality (0-100).

        Factors:
        - Profit margin: 50 points (most important)
        - Liquidity: 30 points (affects execution)
        - Volume: 20 points (market confidence)

        Interview Point - Multi-criteria Decision Making:
        - Combine multiple factors into single score
        - Weighted scoring: Profit matters most
        - Normalized: Each factor contributes 0-N points

        Why Decimal?
        - Consistency with domain models
        - Exact arithmetic (no float rounding)
        """
        # Profit score: 0-50 points
        # 1% profit = 10 points, 5% profit = 50 points (capped)
        profit_pct = market.arbitrage_profit_per_dollar * 100
        profit_score = min(profit_pct * 10, Decimal("50"))

        # Liquidity score: 0-30 points
        # $10k liquidity = 30 points (capped)
        liquidity_score = min(market.liquidity / Decimal("10000") * Decimal("30"), Decimal("30"))

        # Volume score: 0-20 points
        # $100k volume = 20 points (capped)
        volume_score = min(market.volume / Decimal("100000") * Decimal("20"), Decimal("20"))

        total = profit_score + liquidity_score + volume_score

        logger.debug(
            "opportunity_scored",
            market_id=market.market_id,
            total_score=float(total),
            profit_score=float(profit_score),
            liquidity_score=float(liquidity_score),
            volume_score=float(volume_score),
        )

        return total

    def _calculate_position_size(
        self,
        market: Market,
        max_position_size: Decimal,
    ) -> Decimal:
        """
        Calculate recommended position size.

        Constraints:
        1. Max position size (from config)
        2. Max % of market liquidity (avoid price impact)

        Args:
            market: Market to trade
            max_position_size: Maximum allowed position (USD)

        Returns:
            Recommended position size (USD)

        Interview Point - Risk Management:
        - Don't bet everything on one opportunity
        - Respect market liquidity (avoid moving prices)
        - Kelly Criterion: Optimal position sizing formula
        - Here: Simplified to % of liquidity + max cap
        """
        # Max % of liquidity (default 1% from constants)
        liquidity_limit = market.liquidity * MAX_POSITION_PCT_OF_LIQUIDITY

        # Take minimum of max_position and liquidity_limit
        position_size = min(max_position_size, liquidity_limit)

        # Ensure minimum $1 (too small is not worth fees)
        position_size = max(position_size, Decimal("1"))

        logger.debug(
            "position_sized",
            market_id=market.market_id,
            position_size=float(position_size),
            max_position=float(max_position_size),
            liquidity_limit=float(liquidity_limit),
            market_liquidity=float(market.liquidity),
        )

        return position_size


# Example usage for documentation
if __name__ == "__main__":
    """
    Example: Implementing a custom strategy

    Interview Point - Extensibility:
    - New strategies just inherit from ArbitrageStrategy
    - Implement detect_opportunities()
    - Get filtering and scoring for free
    - Can override scoring if needed
    """

    class SimpleArbitrageStrategy(ArbitrageStrategy):
        """Example strategy implementation."""

        async def detect_opportunities(
            self, markets: list[Market]
        ) -> list[ArbitrageOpportunity]:
            """Detect all markets with profit > 1%."""
            from datetime import datetime

            opportunities = []

            for market in markets:
                # Use base class filtering
                skip_reason = self._should_skip_market(market, "simple_strategy")
                if skip_reason:
                    logger.debug("market_skipped", reason=skip_reason)
                    continue

                # Simple detection: profit > 1%
                if market.arbitrage_profit_per_dollar > Decimal("0.01"):
                    # Use base class position sizing
                    position_size = self._calculate_position_size(
                        market,
                        max_position_size=Decimal("100"),
                    )

                    opportunity = ArbitrageOpportunity(
                        market=market,
                        detected_at=datetime.now(),
                        expected_profit_per_dollar=market.arbitrage_profit_per_dollar,
                        recommended_position_size=position_size,
                    )
                    opportunities.append(opportunity)

            # Sort by score (base class scoring)
            opportunities.sort(
                key=lambda opp: self._calculate_opportunity_score(opp.market),
                reverse=True,
            )

            return opportunities

    print("ArbitrageStrategy base class defined")
    print("Subclasses get filtering and scoring logic for free")
