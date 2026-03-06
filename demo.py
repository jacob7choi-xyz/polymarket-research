#!/usr/bin/env python3
"""
Simple demonstration of the Polymarket Arbitrage Detection System

This script:
1. Creates mock Polymarket markets (some with arbitrage opportunities)
2. Runs one detection cycle
3. Shows structured logging output
4. Displays detected opportunities

Usage:
    python demo.py
"""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

from src.config.settings import Settings
from src.domain.models import Market, Token
from src.execution.paper_trader import PaperTrader
from src.execution.position_tracker import PositionTracker
from src.monitoring.logging import configure_logging, get_logger
from src.strategies.price_discrepancy import PriceDiscrepancyStrategy


def create_mock_markets() -> list[Market]:
    """Create sample markets for demonstration."""

    # Future end date for all markets
    end_date = datetime.now() + timedelta(days=30)

    # Market 1: Clear arbitrage opportunity (YES=0.48, NO=0.48, total=0.96)
    market1 = Market(
        market_id="0xabc123",
        question="Will Bitcoin reach $100k by end of 2025?",
        condition_id="0xcond1",
        yes_token=Token(token_id="yes_btc_100k", outcome="Yes", price=Decimal("0.48")),
        no_token=Token(token_id="no_btc_100k", outcome="No", price=Decimal("0.48")),
        volume=Decimal("25000.00"),
        liquidity=Decimal("50000.00"),
        end_date=end_date,
        active=True,
    )

    # Market 2: Small arbitrage (YES=0.52, NO=0.46, total=0.98)
    market2 = Market(
        market_id="0xdef456",
        question="Will the S&P 500 end 2025 above 6000?",
        condition_id="0xcond2",
        yes_token=Token(token_id="yes_sp500_6k", outcome="Yes", price=Decimal("0.52")),
        no_token=Token(token_id="no_sp500_6k", outcome="No", price=Decimal("0.46")),
        volume=Decimal("15000.00"),
        liquidity=Decimal("30000.00"),
        end_date=end_date,
        active=True,
    )

    # Market 3: No arbitrage (YES=0.60, NO=0.39, total=0.99 - at threshold)
    market3 = Market(
        market_id="0xghi789",
        question="Will there be a recession in 2025?",
        condition_id="0xcond3",
        yes_token=Token(token_id="yes_recession", outcome="Yes", price=Decimal("0.60")),
        no_token=Token(token_id="no_recession", outcome="No", price=Decimal("0.39")),
        volume=Decimal("50000.00"),
        liquidity=Decimal("100000.00"),
        end_date=end_date,
        active=True,
    )

    # Market 4: Over-priced market (YES=0.55, NO=0.50, total=1.05 - no arbitrage)
    market4 = Market(
        market_id="0xjkl012",
        question="Will AI surpass human intelligence in 2025?",
        condition_id="0xcond4",
        yes_token=Token(token_id="yes_agi", outcome="Yes", price=Decimal("0.55")),
        no_token=Token(token_id="no_agi", outcome="No", price=Decimal("0.50")),
        volume=Decimal("8000.00"),
        liquidity=Decimal("20000.00"),
        end_date=end_date,
        active=True,
    )

    # Market 5: Low liquidity arbitrage (should be filtered out)
    market5 = Market(
        market_id="0xmno345",
        question="Will Claude Code reach 1M users in 2025?",
        condition_id="0xcond5",
        yes_token=Token(token_id="yes_claude", outcome="Yes", price=Decimal("0.45")),
        no_token=Token(token_id="no_claude", outcome="No", price=Decimal("0.45")),
        volume=Decimal("100.00"),
        liquidity=Decimal("500.00"),  # Very low liquidity
        end_date=end_date,
        active=True,
    )

    return [market1, market2, market3, market4, market5]


async def run_demo() -> None:
    """Run a single arbitrage detection cycle with mock data."""

    # Initialize settings
    settings = Settings()

    # Setup structured logging
    configure_logging(
        log_level=settings.log_level,
        json_logs=False,  # Human-readable for demo
    )
    logger = get_logger(__name__)

    logger.info(
        "arbitrage_demo_started",
        initial_capital=float(settings.initial_capital_usd),
        arbitrage_threshold=float(settings.arbitrage_threshold),
    )

    # Create mock markets
    markets = create_mock_markets()
    logger.info("mock_markets_created", market_count=len(markets))

    print("\n" + "=" * 80)
    print("POLYMARKET ARBITRAGE DETECTION - DEMO")
    print("=" * 80)
    print(f"\nInitial Capital: ${settings.initial_capital_usd:,.2f}")
    print(f"Arbitrage Threshold: {settings.arbitrage_threshold}")
    print(f"Markets to analyze: {len(markets)}\n")

    # Display markets
    print("-" * 80)
    print("MOCK MARKETS:")
    print("-" * 80)
    for i, market in enumerate(markets, 1):
        total = market.total_implied_probability
        is_arb = market.is_arbitrage_opportunity
        status = "✓ ARBITRAGE" if is_arb else "✗ No arbitrage"

        print(f"\n{i}. {market.question}")
        print(f"   Market ID: {market.market_id}")
        print(f"   YES: ${market.yes_token.price:.2f} | NO: ${market.no_token.price:.2f} | Total: ${total:.4f}")
        print(f"   Liquidity: ${market.liquidity:,.0f}")
        print(f"   Status: {status}")

    # Initialize components
    position_tracker = PositionTracker()
    paper_trader = PaperTrader(
        initial_capital=settings.initial_capital_usd,
        position_tracker=position_tracker,
    )
    strategy = PriceDiscrepancyStrategy(
        arbitrage_threshold=settings.arbitrage_threshold,
        min_liquidity=settings.min_liquidity_usd,
        min_volume=settings.min_volume_usd,
        max_position_size=settings.max_position_size_usd,
    )

    # Detect opportunities
    print("\n" + "=" * 80)
    print("RUNNING DETECTION CYCLE")
    print("=" * 80)

    opportunities = await strategy.detect_opportunities(markets)

    logger.info(
        "detection_cycle_completed",
        opportunities_found=len(opportunities),
        markets_analyzed=len(markets),
    )

    # Display results
    if not opportunities:
        print("\n❌ No arbitrage opportunities detected after filtering.")
        print("\nPossible reasons:")
        print("  • Markets don't meet minimum liquidity threshold")
        print("  • Price spreads too small")
        print("  • Markets inactive or closed")
    else:
        print(f"\n✅ Found {len(opportunities)} arbitrage opportunity/opportunities!\n")
        print("-" * 80)
        print("DETECTED OPPORTUNITIES (sorted by profit potential):")
        print("-" * 80)

        for i, opp in enumerate(opportunities, 1):
            print(f"\n{i}. {opp.market_question}")
            print(f"   Market ID: {opp.market_id}")
            print(f"   YES Price: ${opp.yes_price:.4f}")
            print(f"   NO Price: ${opp.no_price:.4f}")
            print(f"   Total Cost: ${opp.total_cost:.4f}")
            print(f"   Expected Profit: ${opp.expected_profit_per_dollar:.4f} per dollar")
            print(f"   Profit %: {float(opp.expected_profit_per_dollar) * 100:.2f}%")
            print(f"   Recommended Position: ${opp.position_size_usd:.2f}")
            print(f"   Score: {opp.score:.2f}")

        # Execute trades
        print("\n" + "=" * 80)
        print("EXECUTING PAPER TRADES")
        print("=" * 80)

        executed_count = 0
        failed_count = 0

        for opp in opportunities:
            success = await paper_trader.execute_arbitrage(opp)
            if success:
                executed_count += 1
                print(f"✅ Executed: {opp.market_question[:60]}...")
            else:
                failed_count += 1
                print(f"❌ Failed: {opp.market_question[:60]}...")

        logger.info(
            "paper_trades_completed",
            executed=executed_count,
            failed=failed_count,
        )

        # Display final state
        print("\n" + "=" * 80)
        print("FINAL STATE")
        print("=" * 80)

        summary = paper_trader.get_performance_summary()

        print(f"\nAvailable Capital: ${summary['available_capital_usd']:,.2f}")
        print(f"Total Capital: ${summary['total_capital_usd']:,.2f}")
        print(f"Open Positions: {summary['open_positions_count']}")
        print(f"Total Trades: {summary['total_trades']}")
        print(f"Successful Trades: {summary['successful_trades']}")
        print(f"Failed Trades: {summary['failed_trades']}")

        if summary['open_positions_count'] > 0:
            print(f"\nUnrealized P&L: ${summary['unrealized_pnl_usd']:,.2f}")
            print(f"Total Invested: ${summary['total_invested_usd']:,.2f}")

        # Show positions
        if position_tracker.positions:
            print("\n" + "-" * 80)
            print("OPEN POSITIONS:")
            print("-" * 80)
            for position in position_tracker.positions.values():
                print(f"\n• {position.market_question[:60]}...")
                print(f"  Market ID: {position.market_id}")
                print(f"  YES: {position.yes_shares:.2f} @ ${position.yes_entry_price:.4f}")
                print(f"  NO: {position.no_shares:.2f} @ ${position.no_entry_price:.4f}")
                print(f"  Total Cost: ${position.total_cost_usd:.2f}")
                print(f"  Expected Profit: ${position.expected_profit_usd:.2f}")
                print(f"  Opened: {position.opened_at.strftime('%Y-%m-%d %H:%M:%S')}")

    print("\n" + "=" * 80)
    logger.info("arbitrage_demo_completed")
    print("Demo completed successfully!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(run_demo())
