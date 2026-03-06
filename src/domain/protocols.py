"""
Protocol (PEP 544) interfaces for dependency injection.

Why Protocols over ABC?
- Duck typing: No inheritance required, easier mocking in tests
- Gradual typing: Can add protocols to existing code without refactoring
- Pythonic: Aligns with Python's duck typing philosophy
- Flexibility: Classes automatically satisfy protocols without explicit declaration

When to use ABC instead:
- When you have shared implementation to inherit
- When you want runtime checks for inheritance
- Example: Strategy base classes with shared filtering logic

Interview Point - SOLID Principles in Python:
- Dependency Inversion: Depend on abstractions (protocols), not concrete classes
- Interface Segregation: Small, focused protocols
- Open/Closed: New implementations without modifying existing code
"""

from typing import AsyncIterator, Protocol

from .models import ArbitrageOpportunity, Market


class IMarketRepository(Protocol):
    """
    Repository interface for fetching market data.

    Why Repository Pattern?
    - Abstraction: Hide data source details (API, database, cache)
    - Testability: Easy to inject mock repositories
    - Flexibility: Swap implementations (live API, cached, test fixtures)

    Interview Point - Repository vs DAO:
    - Repository: Domain-focused, returns domain objects
    - DAO: Database-focused, returns database records
    - We use Repository because we work with domain models (Market)
    """

    async def get_market(self, market_id: str) -> Market | None:
        """
        Fetch single market by ID.

        Args:
            market_id: Unique market identifier

        Returns:
            Market domain object or None if not found

        Why async?
        - Network I/O is inherently async
        - Allows concurrent fetching of multiple markets
        - Non-blocking: Other tasks can run while waiting
        """
        ...

    async def get_markets_by_condition(self, condition_id: str) -> list[Market]:
        """
        Fetch all markets for a given condition.

        Args:
            condition_id: Condition identifier

        Returns:
            List of Market objects (empty if none found)

        Interview Point - Error Handling Design:
        - Return empty list instead of raising exception (expected case)
        - Exceptions for unexpected errors (API down, network failure)
        - Makes caller code cleaner (no try/except for common case)
        """
        ...

    async def stream_active_markets(
        self,
        categories: list[str] | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[Market]:
        """
        Stream active markets, optionally filtered by category.

        Args:
            categories: Filter by categories (e.g., ["politics", "crypto"])
            limit: Maximum number of markets to fetch

        Yields:
            Market objects one at a time

        Why AsyncIterator?
        - Memory efficient: Don't load all markets into memory
        - Progressive processing: Start analyzing before all fetched
        - Backpressure: Fetching pauses if processing is slow

        Interview Point - Iterator Pattern + Async:
        - Lazy evaluation: Fetch on demand
        - Lower latency: Process first results while fetching rest
        - Real-world: Polymarket has 1000s of markets, don't fetch all at once
        """
        ...
        yield  # Make this a generator


class IArbitrageStrategy(Protocol):
    """
    Strategy interface for detecting arbitrage opportunities.

    Why Strategy Pattern?
    - Multiple algorithms: Price discrepancy, volatility, cross-exchange
    - Runtime selection: Choose strategy based on configuration
    - Testability: Easy to test each strategy independently

    Interview Point - Strategy Pattern:
    - Family of algorithms (different arbitrage detection methods)
    - Encapsulated and interchangeable
    - Client code doesn't care which strategy is used
    """

    async def detect_opportunities(
        self,
        markets: list[Market],
    ) -> list[ArbitrageOpportunity]:
        """
        Analyze markets and detect arbitrage opportunities.

        Args:
            markets: List of markets to analyze

        Returns:
            List of detected opportunities (sorted by quality/profit)

        Why async?
        - Future-proofing: Can add async filtering (database lookups)
        - Consistency: All strategy methods are async
        - Composition: Can chain async strategies
        """
        ...

    def calculate_opportunity_score(self, market: Market) -> float:
        """
        Score opportunity quality (0-100).

        Factors:
        - Profit margin: Higher = better
        - Liquidity: Higher = easier execution
        - Volume: Higher = more market confidence
        - Time to expiry: More time = more risk

        Returns:
            Score from 0 (worst) to 100 (best)

        Interview Point - Multi-criteria Decision Making:
        - Combine multiple factors into single score
        - Weighted scoring: Some factors more important than others
        - Helps prioritize: Execute highest scoring opportunities first
        """
        ...


class ITradeExecutor(Protocol):
    """
    Interface for trade execution (paper or live).

    Why separate interface?
    - Polymorphism: Same code works for paper and live trading
    - Safety: Start with paper, switch to live when confident
    - Testing: Use mock executor for tests

    Interview Point - Strategy Pattern (different execution modes):
    - PaperTrader: Simulates execution, logs trades
    - LiveTrader: Real execution on exchange (future)
    - BacktestExecutor: Historical simulation (future)
    """

    async def execute_arbitrage(
        self,
        opportunity: ArbitrageOpportunity,
    ) -> bool:
        """
        Execute arbitrage trade.

        Args:
            opportunity: Detected arbitrage opportunity

        Returns:
            True if execution successful, False otherwise

        Why bool return?
        - Simple success/failure indication
        - Caller decides what to do on failure (retry, log, alert)
        - Exceptions for unexpected errors (network, API down)

        Interview Point - Error Handling Design:
        - Return bool: Expected failures (insufficient capital, market closed)
        - Raise exception: Unexpected failures (API error, network timeout)
        - Helps caller distinguish recoverable from non-recoverable
        """
        ...

    def get_performance_summary(self) -> dict[str, float]:
        """
        Get performance metrics.

        Returns:
            Dict with metrics:
            - initial_capital: Starting capital
            - current_capital: Current capital
            - trades_executed: Number of trades
            - total_profit: Total profit/loss
            - roi_percent: Return on investment %

        Interview Point - Observability:
        - Metrics for monitoring performance
        - Track P&L over time
        - Helps evaluate strategy effectiveness
        """
        ...


class IPositionTracker(Protocol):
    """
    Interface for tracking open positions.

    Why separate from executor?
    - Single Responsibility: Tracking vs execution
    - Reusability: Multiple executors can share tracker
    - Persistence: Can implement database-backed tracker
    """

    def add_position(
        self,
        market_id: str,
        position_size: float,
        yes_price: float,
        no_price: float,
    ) -> None:
        """Add new position."""
        ...

    def close_position(self, market_id: str, realized_pnl: float) -> None:
        """Close position and realize P&L."""
        ...

    def get_open_positions(self) -> list[dict[str, float]]:
        """Get all open positions."""
        ...


# Example usage for documentation
if __name__ == "__main__":
    """
    Example: Using protocols for dependency injection

    Interview Point - Dependency Injection Benefits:
    - Testability: Inject mocks in tests
    - Flexibility: Swap implementations without changing code
    - SOLID: Depend on abstractions, not concretions
    """

    # Example 1: Mock repository for testing
    class MockMarketRepository:
        """Satisfies IMarketRepository without inheriting."""

        async def get_market(self, market_id: str) -> Market | None:
            # Return test fixture
            from decimal import Decimal
            from datetime import datetime
            from .models import Token, Market

            return Market(
                market_id=market_id,
                condition_id="0xtest",
                question="Test market",
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
                volume=Decimal("10000"),
                liquidity=Decimal("5000"),
                end_date=datetime(2025, 12, 31),
                active=True,
            )

        async def get_markets_by_condition(self, condition_id: str) -> list[Market]:
            return []

        async def stream_active_markets(
            self,
            categories: list[str] | None = None,
            limit: int | None = None,
        ) -> AsyncIterator[Market]:
            # Empty stream for testing
            return
            yield  # type: ignore

    # Example 2: Using protocol in type hints
    async def process_markets(repository: IMarketRepository) -> None:
        """
        Accepts any object that satisfies IMarketRepository.

        No inheritance required! Duck typing with type safety.
        """
        market = await repository.get_market("0x123")
        print(f"Fetched market: {market.question if market else 'Not found'}")

    # Example 3: Mock strategy for testing
    class AlwaysArbitrageStrategy:
        """Mock strategy that always finds opportunities."""

        async def detect_opportunities(
            self, markets: list[Market]
        ) -> list[ArbitrageOpportunity]:
            # Return mock opportunities for testing
            return []

        def calculate_opportunity_score(self, market: Market) -> float:
            return 100.0  # Perfect score for all markets

    print("Protocols defined successfully!")
    print("Use for dependency injection and testing")
