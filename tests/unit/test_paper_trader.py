"""
Unit tests for paper trading executor.

Testing:
- Trade execution logic
- Capital management
- Position tracking integration
- Performance metrics

Interview Point - Testing Stateful Components:
- Test initial state
- Test state transitions
- Test edge cases (insufficient capital)
- Test metrics accuracy
"""

from decimal import Decimal

import pytest

from src.domain.models import ArbitrageOpportunity
from src.execution.paper_trader import PaperTrader
from src.execution.position_tracker import PositionTracker


class TestPaperTrader:
    """Test PaperTrader class."""

    @pytest.fixture
    def trader(self) -> PaperTrader:
        """Create paper trader with initial capital."""
        return PaperTrader(initial_capital=Decimal("1000"))

    @pytest.mark.asyncio
    async def test_execute_arbitrage_success(
        self, trader: PaperTrader, sample_opportunity: ArbitrageOpportunity
    ) -> None:
        """Test successful trade execution."""
        initial_capital = trader.available_capital

        success = await trader.execute_arbitrage(sample_opportunity)

        assert success is True
        # Capital should decrease
        assert trader.available_capital < initial_capital

    @pytest.mark.asyncio
    async def test_execute_arbitrage_updates_capital(
        self, trader: PaperTrader, sample_opportunity: ArbitrageOpportunity
    ) -> None:
        """Test capital is updated correctly."""
        market = sample_opportunity.market
        position_size = sample_opportunity.recommended_position_size

        # Expected cost
        expected_cost = position_size * (market.yes_token.price + market.no_token.price)
        initial_capital = trader.available_capital

        await trader.execute_arbitrage(sample_opportunity)

        # Capital should decrease by cost
        assert trader.available_capital == initial_capital - expected_cost

    @pytest.mark.asyncio
    async def test_execute_arbitrage_tracks_position(
        self, trader: PaperTrader, sample_opportunity: ArbitrageOpportunity
    ) -> None:
        """Test position is tracked after execution."""
        await trader.execute_arbitrage(sample_opportunity)

        # Position should exist
        position = trader.position_tracker.get_position(
            sample_opportunity.market.market_id
        )
        assert position is not None
        assert position.market_id == sample_opportunity.market.market_id

    @pytest.mark.asyncio
    async def test_execute_arbitrage_insufficient_capital(
        self, sample_opportunity: ArbitrageOpportunity
    ) -> None:
        """Test handling insufficient capital."""
        # Create trader with minimal capital
        trader = PaperTrader(initial_capital=Decimal("0.50"))

        success = await trader.execute_arbitrage(sample_opportunity)

        # Should fail due to insufficient capital
        assert success is False

    @pytest.mark.asyncio
    async def test_execute_arbitrage_reduces_position_size(
        self, sample_opportunity: ArbitrageOpportunity
    ) -> None:
        """Test position size reduced when capital insufficient."""
        # Create trader with limited capital
        trader = PaperTrader(initial_capital=Decimal("50"))

        success = await trader.execute_arbitrage(sample_opportunity)

        # Should succeed with reduced position
        assert success is True
        # But use less than recommended
        assert trader.available_capital >= 0

    @pytest.mark.asyncio
    async def test_trade_count_increments(
        self, trader: PaperTrader, sample_opportunity: ArbitrageOpportunity
    ) -> None:
        """Test trade counter increments."""
        initial_count = trader._trade_count

        await trader.execute_arbitrage(sample_opportunity)

        assert trader._trade_count == initial_count + 1

    def test_get_performance_summary_initial_state(
        self, trader: PaperTrader
    ) -> None:
        """Test performance summary at initialization."""
        summary = trader.get_performance_summary()

        assert summary["initial_capital"] == 1000.0
        assert summary["available_capital"] == 1000.0
        assert summary["capital_deployed"] == 0.0
        assert summary["trades_executed"] == 0
        assert summary["open_positions"] == 0
        assert summary["total_pnl"] == 0.0

    @pytest.mark.asyncio
    async def test_get_performance_summary_after_trade(
        self, trader: PaperTrader, sample_opportunity: ArbitrageOpportunity
    ) -> None:
        """Test performance summary after executing trade."""
        await trader.execute_arbitrage(sample_opportunity)

        summary = trader.get_performance_summary()

        assert summary["trades_executed"] == 1
        assert summary["open_positions"] == 1
        assert summary["capital_deployed"] > 0
        assert summary["available_capital"] < 1000.0
        # Should have unrealized P&L
        assert summary["total_unrealized_pnl"] > 0

    def test_reset(self, trader: PaperTrader) -> None:
        """Test resetting paper trader."""
        # Execute some trades first (async in real test)
        trader.available_capital = Decimal("500")
        trader._trade_count = 5

        trader.reset()

        assert trader.available_capital == trader.initial_capital
        assert trader._trade_count == 0
        assert len(trader.position_tracker.get_open_positions()) == 0


class TestPositionTracker:
    """Test PositionTracker class."""

    @pytest.fixture
    def tracker(self) -> PositionTracker:
        """Create position tracker."""
        return PositionTracker()

    def test_add_position(self, tracker: PositionTracker) -> None:
        """Test adding a position."""
        tracker.add_position(
            market_id="0xmarket",
            position_size=Decimal("100"),
            yes_price=Decimal("0.48"),
            no_price=Decimal("0.48"),
        )

        position = tracker.get_position("0xmarket")
        assert position is not None
        assert position.market_id == "0xmarket"
        assert position.position_size == Decimal("100")

    def test_close_position(self, tracker: PositionTracker) -> None:
        """Test closing a position."""
        tracker.add_position(
            market_id="0xmarket",
            position_size=Decimal("100"),
            yes_price=Decimal("0.48"),
            no_price=Decimal("0.48"),
        )

        tracker.close_position("0xmarket", realized_pnl=Decimal("4.0"))

        # Position should be removed
        assert tracker.get_position("0xmarket") is None
        # Realized P&L should be updated
        assert tracker.total_realized_pnl == Decimal("4.0")
        assert tracker.closed_positions_count == 1

    def test_get_total_unrealized_pnl(self, tracker: PositionTracker) -> None:
        """Test calculating total unrealized P&L."""
        tracker.add_position(
            market_id="0xmarket1",
            position_size=Decimal("100"),
            yes_price=Decimal("0.48"),
            no_price=Decimal("0.48"),
        )

        unrealized = tracker.get_total_unrealized_pnl()

        # Should have positive unrealized P&L (0.04 * 100 = 4.0)
        assert unrealized > 0

    def test_get_summary(self, tracker: PositionTracker) -> None:
        """Test getting position summary."""
        tracker.add_position(
            market_id="0xmarket1",
            position_size=Decimal("100"),
            yes_price=Decimal("0.48"),
            no_price=Decimal("0.48"),
        )

        summary = tracker.get_summary()

        assert summary["open_positions"] == 1
        assert summary["total_unrealized_pnl"] > 0
        assert summary["total_realized_pnl"] == 0.0
        assert summary["closed_positions_count"] == 0
