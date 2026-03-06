"""
Unit tests for arbitrage detection strategies.

Testing:
- Opportunity detection logic
- Market filtering (liquidity, volume, active)
- Opportunity scoring
- Position sizing

Interview Point - Strategy Testing:
- Business logic is most critical to test
- Use fixtures for consistent test data
- Test edge cases (boundaries, empty lists)
- Test sorting (best opportunities first)
"""

from decimal import Decimal

import pytest

from src.domain.models import Market
from src.strategies.price_discrepancy import PriceDiscrepancyStrategy


class TestPriceDiscrepancyStrategy:
    """Test price discrepancy arbitrage strategy."""

    @pytest.fixture
    def strategy(self) -> PriceDiscrepancyStrategy:
        """Create strategy with test configuration."""
        return PriceDiscrepancyStrategy(
            arbitrage_threshold=Decimal("0.99"),
            min_liquidity=Decimal("1000"),
            min_volume=Decimal("10000"),
            max_position_size=Decimal("100"),
        )

    @pytest.mark.asyncio
    async def test_detect_opportunities_finds_arbitrage(
        self, strategy: PriceDiscrepancyStrategy, sample_market: Market
    ) -> None:
        """Test detecting arbitrage opportunity."""
        markets = [sample_market]

        opportunities = await strategy.detect_opportunities(markets)

        assert len(opportunities) == 1
        assert opportunities[0].market.market_id == sample_market.market_id

    @pytest.mark.asyncio
    async def test_detect_opportunities_filters_no_arbitrage(
        self,
        strategy: PriceDiscrepancyStrategy,
        sample_market_no_arbitrage: Market,
    ) -> None:
        """Test filtering markets without arbitrage."""
        markets = [sample_market_no_arbitrage]

        opportunities = await strategy.detect_opportunities(markets)

        assert len(opportunities) == 0

    @pytest.mark.asyncio
    async def test_detect_opportunities_filters_low_liquidity(
        self,
        strategy: PriceDiscrepancyStrategy,
        sample_market_low_liquidity: Market,
    ) -> None:
        """Test filtering markets with insufficient liquidity."""
        markets = [sample_market_low_liquidity]

        opportunities = await strategy.detect_opportunities(markets)

        assert len(opportunities) == 0

    @pytest.mark.asyncio
    async def test_detect_opportunities_sorts_by_score(
        self, strategy: PriceDiscrepancyStrategy
    ) -> None:
        """Test opportunities sorted by quality score."""
        from datetime import datetime

        from src.domain.models import Token

        # Create two arbitrage opportunities with different profits
        market1 = Market(
            market_id="0xmarket1",
            condition_id="0xcond1",
            question="Market 1",
            yes_token=Token(token_id="0xyes1", outcome="Yes", price=Decimal("0.45")),
            no_token=Token(token_id="0xno1", outcome="No", price=Decimal("0.45")),
            volume=Decimal("50000"),
            liquidity=Decimal("10000"),
            end_date=datetime(2025, 12, 31),
            active=True,
        )  # Total: 0.90, profit: 0.10

        market2 = Market(
            market_id="0xmarket2",
            condition_id="0xcond2",
            question="Market 2",
            yes_token=Token(token_id="0xyes2", outcome="Yes", price=Decimal("0.48")),
            no_token=Token(token_id="0xno2", outcome="No", price=Decimal("0.48")),
            volume=Decimal("50000"),
            liquidity=Decimal("10000"),
            end_date=datetime(2025, 12, 31),
            active=True,
        )  # Total: 0.96, profit: 0.04

        markets = [market2, market1]  # market2 first (lower profit)

        opportunities = await strategy.detect_opportunities(markets)

        # Should be sorted by score (market1 has higher profit = higher score)
        assert len(opportunities) == 2
        assert opportunities[0].market.market_id == "0xmarket1"  # Higher profit first
        assert opportunities[1].market.market_id == "0xmarket2"

    @pytest.mark.asyncio
    async def test_detect_opportunities_empty_list(
        self, strategy: PriceDiscrepancyStrategy
    ) -> None:
        """Test handling empty market list."""
        opportunities = await strategy.detect_opportunities([])

        assert len(opportunities) == 0

    def test_calculate_opportunity_score(
        self, strategy: PriceDiscrepancyStrategy, sample_market: Market
    ) -> None:
        """Test opportunity scoring."""
        score = strategy.calculate_opportunity_score(sample_market)

        # Score should be > 0 for arbitrage opportunity
        assert score > 0
        # Score should be <= 100 (max possible)
        assert score <= 100

    def test_position_sizing_respects_max_position(
        self, strategy: PriceDiscrepancyStrategy, sample_market: Market
    ) -> None:
        """Test position sizing doesn't exceed max."""
        position_size = strategy._calculate_position_size(
            sample_market, max_position_size=Decimal("50")
        )

        assert position_size <= Decimal("50")

    def test_position_sizing_respects_liquidity(
        self, strategy: PriceDiscrepancyStrategy
    ) -> None:
        """Test position sizing respects market liquidity."""
        from datetime import datetime

        from src.domain.models import Token

        # Create market with low liquidity
        low_liq_market = Market(
            market_id="0xlow",
            condition_id="0xcond",
            question="Low liquidity",
            yes_token=Token(token_id="0xyes", outcome="Yes", price=Decimal("0.48")),
            no_token=Token(token_id="0xno", outcome="No", price=Decimal("0.48")),
            volume=Decimal("50000"),
            liquidity=Decimal("100"),  # Very low
            end_date=datetime(2025, 12, 31),
            active=True,
        )

        position_size = strategy._calculate_position_size(
            low_liq_market, max_position_size=Decimal("1000")
        )

        # Should be limited by liquidity (1% of 100 = 1)
        assert position_size <= Decimal("1")
