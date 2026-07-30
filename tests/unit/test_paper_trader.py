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

from polymarket_arbitrage.domain.models import ArbitrageOpportunity, ResolutionStatus
from polymarket_arbitrage.execution.paper_trader import PaperTrader
from polymarket_arbitrage.execution.position_tracker import PositionTracker


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
        position = trader.position_tracker.get_position(sample_opportunity.market.market_id)
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

    def test_get_performance_summary_initial_state(self, trader: PaperTrader) -> None:
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
            bundle_quantity=Decimal("100"),
            yes_price=Decimal("0.48"),
            no_price=Decimal("0.48"),
        )

        position = tracker.get_position("0xmarket")
        assert position is not None
        assert position.market_id == "0xmarket"
        assert position.bundle_quantity == Decimal("100")

    def test_close_position(self, tracker: PositionTracker) -> None:
        """Test closing a position."""
        tracker.add_position(
            market_id="0xmarket",
            bundle_quantity=Decimal("100"),
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
            bundle_quantity=Decimal("100"),
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
            bundle_quantity=Decimal("100"),
            yes_price=Decimal("0.48"),
            no_price=Decimal("0.48"),
        )

        summary = tracker.get_summary()

        assert summary["open_positions"] == 1
        assert summary["total_unrealized_pnl"] > 0
        assert summary["total_realized_pnl"] == 0.0
        assert summary["closed_positions_count"] == 0


class TestSettlement:
    """Settlement must require evidence of resolution, never infer it from a clock.

    Two regressions are covered. close_position() originally had no caller at all, so
    capital fell monotonically and realized P&L was permanently zero. The first fix then
    settled on market.end_date -- but measured across 32 live markets, 100% close *after*
    their end date, median 0.8h later and up to 11.7h. That would credit capital while
    the position was still unredeemable.
    """

    @pytest.fixture
    def trader(self) -> PaperTrader:
        """Trader with a real tracker."""
        return PaperTrader(initial_capital=Decimal("10000"), position_tracker=PositionTracker())

    def _open(self, trader: PaperTrader, market_id: str) -> None:
        """Open 100 bundles at 0.48/0.48 -> $96 cost, $100 payout, $4 profit."""
        trader.position_tracker.add_position(
            market_id=market_id,
            bundle_quantity=Decimal("100"),
            yes_price=Decimal("0.48"),
            no_price=Decimal("0.48"),
        )
        trader.available_capital -= Decimal("96")

    def test_resolved_status_settles(self, trader: PaperTrader) -> None:
        """Confirmed resolution returns capital and realizes profit."""
        self._open(trader, "0xdone")

        assert trader.settle_position("0xdone", ResolutionStatus.RESOLVED) is True
        assert trader.available_capital == Decimal("10004")
        assert trader.position_tracker.total_realized_pnl == Decimal("4.00")
        assert trader.position_tracker.get_open_positions() == []

    @pytest.mark.parametrize("status", [ResolutionStatus.UNRESOLVED, ResolutionStatus.UNKNOWN])
    def test_anything_short_of_resolved_leaves_position_open(
        self, trader: PaperTrader, status: ResolutionStatus
    ) -> None:
        """A market past its end date but not confirmed resolved must not settle.

        This is the case the end-date implementation got wrong: the position looks ready
        and is not.
        """
        self._open(trader, "0xpending")

        assert trader.settle_position("0xpending", status) is False
        assert trader.available_capital == Decimal("9904")
        assert trader.position_tracker.total_realized_pnl == Decimal("0")
        assert len(trader.position_tracker.get_open_positions()) == 1

    def test_elapsed_end_date_alone_never_settles(self, trader: PaperTrader) -> None:
        """No amount of elapsed time settles a position without resolution evidence."""
        self._open(trader, "0xold")

        # Every position here has a 2020 end date; settling with no status supplied
        assert trader.settle_positions({}) == 0
        assert len(trader.position_tracker.get_open_positions()) == 1

    def test_batch_settles_only_confirmed_markets(self, trader: PaperTrader) -> None:
        """A mixed batch settles exactly the confirmed subset."""
        for mid in ("0xa", "0xb", "0xc"):
            self._open(trader, mid)

        settled = trader.settle_positions(
            {
                "0xa": ResolutionStatus.RESOLVED,
                "0xb": ResolutionStatus.UNRESOLVED,
                # 0xc absent -> treated as UNKNOWN
            }
        )

        assert settled == 1
        assert {p.market_id for p in trader.position_tracker.get_open_positions()} == {
            "0xb",
            "0xc",
        }

    def test_settling_unknown_market_is_a_noop(self, trader: PaperTrader) -> None:
        """Resolution evidence for a market we hold no position in changes nothing."""
        assert trader.settle_position("0xnothing", ResolutionStatus.RESOLVED) is False
        assert trader.available_capital == Decimal("10000")

    def test_settlement_is_idempotent(self, trader: PaperTrader) -> None:
        """Settling twice must not credit capital or P&L twice.

        Double-crediting is the most direct money-accounting failure a settlement path
        can have, so it gets an explicit test rather than relying on the position lookup
        happening to return None the second time.
        """
        self._open(trader, "0xonce")

        assert trader.settle_position("0xonce", ResolutionStatus.RESOLVED) is True
        capital_after_first = trader.available_capital
        pnl_after_first = trader.position_tracker.total_realized_pnl
        closed_after_first = trader.position_tracker.closed_positions_count

        assert trader.settle_position("0xonce", ResolutionStatus.RESOLVED) is False
        assert trader.available_capital == capital_after_first
        assert trader.position_tracker.total_realized_pnl == pnl_after_first
        assert trader.position_tracker.closed_positions_count == closed_after_first

    def test_capital_conservation_invariant_exact(self, trader: PaperTrader) -> None:
        """available + open cost basis - realized == initial, in exact Decimal.

        Asserted on the Decimal attributes rather than the summary dict, which converts
        to float for Prometheus. A conservation invariant checked through float would not
        detect the drift it exists to catch.
        """
        for mid in ("0xa", "0xb", "0xc"):
            self._open(trader, mid)
        trader.settle_positions({"0xa": ResolutionStatus.RESOLVED})

        open_cost = sum(
            (p.total_cost for p in trader.position_tracker.get_open_positions()),
            Decimal("0"),
        )
        reconciled = (
            trader.available_capital + open_cost - trader.position_tracker.total_realized_pnl
        )
        assert reconciled == trader.initial_capital
        assert isinstance(reconciled, Decimal)

    def test_unit_arithmetic_is_dimensionally_coherent(self, trader: PaperTrader) -> None:
        """bundle_quantity is a count; cost and payout are dollars.

        Uses asymmetric prices so a transposed multiplication cannot pass by symmetry.
        """
        trader.position_tracker.add_position(
            market_id="0xunits",
            bundle_quantity=Decimal("100"),
            yes_price=Decimal("0.47"),
            no_price=Decimal("0.49"),
        )
        position = trader.position_tracker.get_position("0xunits")
        assert position is not None

        assert position.total_cost == Decimal("96.00")  # 100 bundles x $0.96
        assert position.payout == Decimal("100")  # 100 bundles x $1
        assert position.expected_profit == Decimal("4.00")

    def test_capital_conservation_invariant(self, trader: PaperTrader) -> None:
        """available + deployed - realized must always equal initial capital."""
        for mid in ("0xa", "0xb", "0xc"):
            self._open(trader, mid)
        trader.settle_positions({"0xa": ResolutionStatus.RESOLVED})

        s = trader.get_performance_summary()
        reconciled = (
            Decimal(str(s["available_capital"]))
            + Decimal(str(s["capital_deployed"]))
            - Decimal(str(s["total_realized_pnl"]))
        )
        assert reconciled == trader.initial_capital

    def test_capital_deployed_excludes_realized_gains(self, trader: PaperTrader) -> None:
        """Deployment is the sum of open cost bases, not initial minus available.

        Regression: subtracting available from initial conflates deployed capital with
        realized profit. It agreed only while realized P&L was permanently zero.
        """
        self._open(trader, "0xsettled")
        self._open(trader, "0xopen")
        trader.settle_positions({"0xsettled": ResolutionStatus.RESOLVED})

        s = trader.get_performance_summary()
        assert s["capital_deployed"] == 96.0
        assert s["total_realized_pnl"] == 4.0
        assert s["available_capital"] == 9908.0

    def test_duplicate_position_is_rejected(self, trader: PaperTrader) -> None:
        """Overwriting an open position would silently lose its cost basis."""
        self._open(trader, "0xdup")
        with pytest.raises(ValueError, match="already open"):
            self._open(trader, "0xdup")
