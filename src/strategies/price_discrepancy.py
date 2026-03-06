"""
Price discrepancy arbitrage strategy.

Core Logic: Detect when YES + NO < threshold (default 0.99)

How it works:
1. In efficient market: YES price + NO price ≈ 1.0
2. If YES + NO < 0.99: Arbitrage opportunity exists
3. Buy both outcomes, guaranteed profit when market resolves

Example:
- YES: $0.48, NO: $0.48
- Total cost: $0.96
- Payout: $1.00 (one outcome will win)
- Profit: $1.00 - $0.96 = $0.04 (4% ROI)

Interview Points:
- Financial markets: Market efficiency, arbitrage
- Risk-free profit: No directional bet, guaranteed payout
- Execution risk: Only risk is failure to execute
- Kelly Criterion: Could optimize position sizing (future enhancement)
"""

from datetime import datetime
from decimal import Decimal

from ..config.constants import ARBITRAGE_THRESHOLD, MIN_LIQUIDITY, MIN_VOLUME
from ..domain.models import ArbitrageOpportunity, Market
from ..monitoring.logging import get_logger
from .base import ArbitrageStrategy

logger = get_logger(__name__)


class PriceDiscrepancyStrategy(ArbitrageStrategy):
    """
    Detect arbitrage when total implied probability < threshold.

    Algorithm:
    1. Filter markets by liquidity and volume
    2. Check if YES + NO < threshold
    3. Calculate position sizing
    4. Score by quality metrics
    5. Sort by score (best first)

    Interview Point - Strategy Pattern Implementation:
    - Encapsulates one specific algorithm (price discrepancy)
    - Other strategies possible: Volatility, cross-exchange, etc.
    - Interchangeable: Can swap strategies at runtime
    - Testable: Unit test in isolation
    """

    def __init__(
        self,
        arbitrage_threshold: Decimal | None = None,
        min_liquidity: Decimal | None = None,
        min_volume: Decimal | None = None,
        max_position_size: Decimal = Decimal("100"),
    ):
        """
        Initialize strategy with configuration.

        Args:
            arbitrage_threshold: YES + NO must be < this (default from constants)
            min_liquidity: Minimum market liquidity USD (default from constants)
            min_volume: Minimum 24h volume USD (default from constants)
            max_position_size: Maximum position per opportunity USD

        Interview Point - Dependency Injection:
        - Configuration injected via constructor (not hardcoded)
        - Testability: Can inject test values
        - Flexibility: Different instances with different configs
        """
        self.arbitrage_threshold = arbitrage_threshold or ARBITRAGE_THRESHOLD
        self.min_liquidity = min_liquidity or MIN_LIQUIDITY
        self.min_volume = min_volume or MIN_VOLUME
        self.max_position_size = max_position_size

        logger.info(
            "strategy_initialized",
            strategy="price_discrepancy",
            arbitrage_threshold=float(self.arbitrage_threshold),
            min_liquidity=float(self.min_liquidity),
            min_volume=float(self.min_volume),
            max_position_size=float(self.max_position_size),
        )

    async def detect_opportunities(
        self,
        markets: list[Market],
    ) -> list[ArbitrageOpportunity]:
        """
        Detect arbitrage opportunities in given markets.

        Args:
            markets: List of markets to analyze

        Returns:
            List of opportunities sorted by quality score (best first)

        Interview Point - Why async?
        - Future-proofing: Can add async operations (DB lookups, API calls)
        - Consistency: All strategy methods async
        - Composition: Can chain strategies asynchronously
        - No harm: async/await overhead negligible for computation
        """
        opportunities: list[ArbitrageOpportunity] = []
        markets_analyzed = 0
        markets_filtered = 0

        logger.info(
            "detection_started",
            total_markets=len(markets),
        )

        for market in markets:
            markets_analyzed += 1

            # Filter 1: Use base class filtering (inactive, expired)
            skip_reason = self._should_skip_market(market, "price_discrepancy")
            if skip_reason:
                markets_filtered += 1
                logger.debug(
                    "market_filtered",
                    market_id=market.market_id,
                    reason=skip_reason,
                )
                continue

            # Filter 2: Minimum liquidity (execution risk)
            # Low liquidity → orders move prices → slippage
            if market.liquidity < self.min_liquidity:
                markets_filtered += 1
                logger.debug(
                    "market_filtered.insufficient_liquidity",
                    market_id=market.market_id,
                    liquidity=float(market.liquidity),
                    minimum=float(self.min_liquidity),
                )
                continue

            # Filter 3: Minimum volume (market confidence)
            # Low volume → stale prices → unreliable arbitrage signal
            if market.volume < self.min_volume:
                markets_filtered += 1
                logger.debug(
                    "market_filtered.insufficient_volume",
                    market_id=market.market_id,
                    volume=float(market.volume),
                    minimum=float(self.min_volume),
                )
                continue

            # Core arbitrage check: YES + NO < threshold
            # Interview Point - Why < 0.99 not < 1.0?
            # - Transaction fees: Polymarket charges ~2% on winnings
            # - Slippage: Prices move during execution
            # - Safety buffer: Ensures profit after costs
            if market.total_implied_probability >= self.arbitrage_threshold:
                logger.debug(
                    "market_filtered.no_arbitrage",
                    market_id=market.market_id,
                    total_probability=float(market.total_implied_probability),
                    threshold=float(self.arbitrage_threshold),
                )
                continue

            # Arbitrage detected! Calculate position size
            # Interview Point - Position Sizing:
            # - Don't bet everything on one opportunity
            # - Respect liquidity (max 1% of market liquidity)
            # - Kelly Criterion would be ideal (future enhancement)
            position_size = self._calculate_position_size(
                market,
                self.max_position_size,
            )

            # Create opportunity
            opportunity = ArbitrageOpportunity(
                market=market,
                detected_at=datetime.now(),
                expected_profit_per_dollar=market.arbitrage_profit_per_dollar,
                recommended_position_size=position_size,
            )

            opportunities.append(opportunity)

            # Log discovery
            logger.info(
                "arbitrage_detected",
                market_id=market.market_id,
                question=market.question,
                yes_price=float(market.yes_token.price),
                no_price=float(market.no_token.price),
                total_probability=float(market.total_implied_probability),
                expected_profit_per_dollar=float(market.arbitrage_profit_per_dollar),
                expected_roi_percent=float(market.arbitrage_profit_per_dollar * 100),
                position_size=float(position_size),
                total_expected_profit=float(opportunity.total_expected_profit),
                liquidity=float(market.liquidity),
                volume=float(market.volume),
            )

        # Sort by quality score (best opportunities first)
        # Interview Point - Prioritization:
        # - Limited capital: Can't execute all opportunities
        # - Execute highest quality first
        # - Score considers profit, liquidity, volume
        opportunities.sort(
            key=lambda opp: self._calculate_opportunity_score(opp.market),
            reverse=True,  # Highest score first
        )

        logger.info(
            "detection_completed",
            markets_analyzed=markets_analyzed,
            markets_filtered=markets_filtered,
            opportunities_found=len(opportunities),
            top_opportunity_score=float(
                self._calculate_opportunity_score(opportunities[0].market)
            )
            if opportunities
            else 0,
        )

        return opportunities

    def calculate_opportunity_score(self, market: Market) -> float:
        """
        Public method for scoring (returns float for external use).

        Delegates to base class implementation.
        """
        return float(self._calculate_opportunity_score(market))


# Example usage for documentation
if __name__ == "__main__":
    """
    Example: Using PriceDiscrepancyStrategy

    Interview Point - Clean API:
    - Simple to instantiate
    - Clear configuration
    - Easy to test
    """
    import asyncio
    from decimal import Decimal
    from datetime import datetime
    from ..domain.models import Token, Market

    async def demo_strategy() -> None:
        print("=== Price Discrepancy Strategy Demo ===\n")

        # Create test markets
        # Market 1: Arbitrage opportunity (YES + NO = 0.96)
        market1 = Market(
            market_id="0xarb1",
            condition_id="0xcond1",
            question="Will Bitcoin reach $100k in 2025?",
            yes_token=Token(
                token_id="0xyes1",
                outcome="Yes",
                price=Decimal("0.48"),
            ),
            no_token=Token(
                token_id="0xno1",
                outcome="No",
                price=Decimal("0.48"),
            ),
            volume=Decimal("50000"),
            liquidity=Decimal("10000"),
            end_date=datetime(2025, 12, 31, 23, 59, 59),
            active=True,
            category="crypto",
        )

        # Market 2: No arbitrage (YES + NO = 1.00)
        market2 = Market(
            market_id="0xnoarb1",
            condition_id="0xcond2",
            question="Will ETH flip BTC?",
            yes_token=Token(
                token_id="0xyes2",
                outcome="Yes",
                price=Decimal("0.50"),
            ),
            no_token=Token(
                token_id="0xno2",
                outcome="No",
                price=Decimal("0.50"),
            ),
            volume=Decimal("30000"),
            liquidity=Decimal("8000"),
            end_date=datetime(2025, 12, 31),
            active=True,
            category="crypto",
        )

        # Market 3: Low liquidity (should be filtered)
        market3 = Market(
            market_id="0xlow_liq",
            condition_id="0xcond3",
            question="Obscure prediction",
            yes_token=Token(
                token_id="0xyes3",
                outcome="Yes",
                price=Decimal("0.45"),
            ),
            no_token=Token(
                token_id="0xno3",
                outcome="No",
                price=Decimal("0.45"),
            ),
            volume=Decimal("100"),  # Low volume
            liquidity=Decimal("50"),  # Low liquidity
            end_date=datetime(2025, 12, 31),
            active=True,
        )

        markets = [market1, market2, market3]

        # Initialize strategy
        strategy = PriceDiscrepancyStrategy(
            arbitrage_threshold=Decimal("0.99"),
            min_liquidity=Decimal("1000"),
            min_volume=Decimal("10000"),
            max_position_size=Decimal("100"),
        )

        # Detect opportunities
        opportunities = await strategy.detect_opportunities(markets)

        # Display results
        print(f"Analyzed {len(markets)} markets")
        print(f"Found {len(opportunities)} opportunities\n")

        for i, opp in enumerate(opportunities, 1):
            market = opp.market
            print(f"Opportunity {i}:")
            print(f"  Market: {market.question}")
            print(f"  YES: ${market.yes_token.price}")
            print(f"  NO: ${market.no_token.price}")
            print(f"  Total: ${market.total_implied_probability}")
            print(f"  Profit/dollar: ${opp.expected_profit_per_dollar}")
            print(f"  Position size: ${opp.recommended_position_size}")
            print(f"  Expected profit: ${opp.total_expected_profit}")
            print(
                f"  Score: {strategy.calculate_opportunity_score(market):.2f}/100"
            )
            print()

    # Run demo
    asyncio.run(demo_strategy())
