"""
Main application orchestrator with dependency injection.

Responsibilities:
- Build dependency graph (Composition Root pattern)
- Lifecycle management (startup, shutdown)
- Main event loop (detection cycles)
- Signal handling (graceful shutdown)

Interview Points:
- Dependency Injection: All dependencies created here, injected via constructor
- Composition Root: Single place where entire object graph is built
- Lifecycle management: Proper startup/shutdown sequence
- Graceful shutdown: Handle SIGTERM/SIGINT without data loss
"""

import asyncio
import signal
import sys
import uuid
from typing import NoReturn

from .api.client import PolymarketClient
from .api.endpoints import PolymarketEndpoints
from .api.parsers import ResponseParser
from .api.resilience import CircuitBreaker, RateLimiter
from .config.settings import Settings, get_settings
from .domain.models import Market
from .execution.paper_trader import PaperTrader
from .execution.position_tracker import PositionTracker
from .monitoring.logging import bind_context, clear_context, configure_logging, get_logger
from .monitoring.metrics import (
    record_opportunity_detected,
    record_trade_executed,
    track_detection_cycle,
    update_capital_metrics,
    update_circuit_breaker_state,
    update_position_count,
)
from .strategies.price_discrepancy import PriceDiscrepancyStrategy

logger = get_logger(__name__)


class Application:
    """
    Main application orchestrator.

    Design Pattern: Composition Root (Dependency Injection)
    - All dependencies created here
    - Passed to components via constructor
    - Makes testing easy (inject mocks)
    - Clear dependency graph

    Interview Point - Why Composition Root?
    - Single place to configure entire application
    - Easy to swap implementations (mock vs real)
    - No hidden dependencies (all explicit)
    - SOLID: Dependency Inversion Principle
    """

    def __init__(self, settings: Settings):
        """
        Initialize application with settings.

        Interview Point - Construction vs Initialization:
        - Constructor: Simple assignment, no I/O
        - startup(): Async initialization, I/O operations
        - Separation allows sync construction, async startup
        """
        self.settings = settings
        self.running = False

        # Components initialized in startup()
        self.position_tracker: PositionTracker | None = None
        self.paper_trader: PaperTrader | None = None
        self.rate_limiter: RateLimiter | None = None
        self.circuit_breaker: CircuitBreaker | None = None
        self.api_client: PolymarketClient | None = None
        self.strategy: PriceDiscrepancyStrategy | None = None

    async def startup(self) -> None:
        """
        Initialize application components.

        Order matters:
        1. Core infrastructure (logging, metrics)
        2. External dependencies (API client)
        3. Business logic (strategy)
        4. Execution layer (trader)

        Interview Point - Initialization Order:
        - Bottom-up: Build from dependencies to dependents
        - Fail fast: Validate everything before starting
        - Health checks: Verify external dependencies work
        """
        logger.info(
            "application_starting",
            config={
                "arbitrage_threshold": float(self.settings.arbitrage_threshold),
                "poll_interval": self.settings.poll_interval_seconds,
                "paper_trading": self.settings.paper_trading_enabled,
                "initial_capital": float(self.settings.initial_capital_usd),
            },
        )

        # Build dependency graph
        # Interview Point: Dependency Injection (manual, not framework)
        # - Simple, explicit, no magic
        # - Easy to understand, debug, test
        # - No framework lock-in

        # Layer 1: Infrastructure
        self.position_tracker = PositionTracker()
        self.paper_trader = PaperTrader(
            initial_capital=self.settings.initial_capital_usd,
            position_tracker=self.position_tracker,
        )

        # Layer 2: Resilience
        self.rate_limiter = RateLimiter(
            rate=self.settings.rate_limit_requests_per_second,
            burst=self.settings.rate_limit_burst,
        )

        self.circuit_breaker = CircuitBreaker(
            failure_threshold=self.settings.circuit_breaker_failure_threshold,
            recovery_timeout=self.settings.circuit_breaker_recovery_timeout_seconds,
        )

        # Layer 3: API Client
        self.api_client = PolymarketClient(
            base_url=str(self.settings.polymarket_api_url),
        )

        # Layer 4: Strategy
        self.strategy = PriceDiscrepancyStrategy(
            arbitrage_threshold=self.settings.arbitrage_threshold,
            min_liquidity=self.settings.min_liquidity_usd,
            min_volume=self.settings.min_volume_usd,
            max_position_size=self.settings.max_position_size_usd,
        )

        logger.info("application_ready")

    async def shutdown(self) -> None:
        """
        Graceful shutdown sequence.

        Order matters (reverse of startup):
        1. Stop accepting new work (set running = False)
        2. Finish current work (detection cycle completes)
        3. Close external connections (API client)
        4. Save state / log final metrics

        Interview Point - Graceful Shutdown:
        - Kubernetes sends SIGTERM, waits, then SIGKILL
        - Complete current work before exiting
        - Close connections properly (no resource leaks)
        - Log final state for debugging
        """
        logger.info("application_shutting_down")
        self.running = False

        # Close API client
        if self.api_client:
            await self.api_client.__aexit__(None, None, None)

        # Log final performance
        if self.paper_trader:
            performance = self.paper_trader.get_performance_summary()
            logger.info("final_performance", **performance)

        logger.info("application_stopped")

    async def _fetch_markets(self) -> list[Market]:
        """
        Fetch markets from Polymarket API.

        Uses multi-endpoint fallback strategy from reference code.
        Converts API responses to domain models.

        Returns:
            List of Market domain objects

        Interview Point - API Integration:
        - Multi-endpoint fallback (resilience)
        - Flexible parsing (handle format variations)
        - Domain model conversion (separation of concerns)
        """
        markets: list[Market] = []

        if not self.api_client:
            logger.error("api_client_not_initialized")
            return markets

        # For demo/MVP: Fetch sample market
        # In production: Fetch markets list, paginate, filter by category
        # TODO: Implement full market fetching with pagination

        logger.info("market_fetching_skipped_mvp")
        return markets

    @track_detection_cycle
    async def run_detection_cycle(self) -> None:
        """
        Single detection cycle: fetch → detect → execute.

        Flow:
        1. Bind cycle ID (for log correlation)
        2. Fetch markets from API
        3. Detect arbitrage opportunities
        4. Execute top opportunities (paper trading)
        5. Update metrics
        6. Clear context

        Interview Point - Error Handling Strategy:
        - Catch exceptions (don't crash on API errors)
        - Log errors with context
        - Continue running (one failure shouldn't stop system)
        - Circuit breaker handles cascading failures
        """
        cycle_id = str(uuid.uuid4())
        bind_context(cycle_id=cycle_id)

        try:
            logger.info("detection_cycle_started")

            # Fetch markets
            markets = await self._fetch_markets()
            logger.info("markets_fetched", count=len(markets))

            if not markets:
                logger.info("no_markets_to_analyze")
                return

            # Detect opportunities
            if not self.strategy:
                logger.error("strategy_not_initialized")
                return

            opportunities = await self.strategy.detect_opportunities(markets)

            # Record metrics
            for opp in opportunities:
                record_opportunity_detected(
                    strategy="price_discrepancy",
                    profit_per_dollar=float(opp.expected_profit_per_dollar),
                )

            logger.info("opportunities_detected", count=len(opportunities))

            # Execute top opportunities
            # Interview Point: Capital allocation strategy
            # - Execute until capital exhausted
            # - Or execute top N (limit exposure)
            # - Here: Execute all (paper trading has no real limit)
            if not self.paper_trader:
                logger.error("paper_trader_not_initialized")
                return

            executed_count = 0
            for opp in opportunities:
                success = await self.paper_trader.execute_arbitrage(opp)
                record_trade_executed(success)
                if success:
                    executed_count += 1

            logger.info("trades_executed", count=executed_count)

            # Update metrics
            performance = self.paper_trader.get_performance_summary()
            update_capital_metrics(
                available=performance["available_capital"],
                deployed=performance["capital_deployed"],
                total_pnl=performance["total_pnl"],
                unrealized_pnl=performance["total_unrealized_pnl"],
                realized_pnl=performance["total_realized_pnl"],
            )
            update_position_count(performance["open_positions"])

            # Update circuit breaker metrics
            if self.circuit_breaker:
                update_circuit_breaker_state(
                    "polymarket_api",
                    self.circuit_breaker.state.value,
                )

            logger.info("detection_cycle_completed", cycle_id=cycle_id)

        except Exception as e:
            logger.error(
                "detection_cycle_failed",
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True,
            )

        finally:
            clear_context()

    async def run(self) -> None:
        """
        Main event loop.

        Runs detection cycles at configured interval until stopped.

        Interview Point - Event Loop Design:
        - Check self.running flag (graceful shutdown)
        - Configurable interval (balance speed vs API load)
        - Error recovery (continue on failure)
        - Backpressure (don't start new cycle if previous running)
        """
        self.running = True

        logger.info(
            "event_loop_started",
            poll_interval=self.settings.poll_interval_seconds,
        )

        while self.running:
            try:
                await self.run_detection_cycle()

                # Sleep until next cycle
                # Interview Point: Why sleep instead of schedule?
                # - Simple: No external scheduler needed
                # - Backpressure: If cycle takes > interval, next starts immediately
                # - Production: Could use APScheduler, Celery, etc.
                await asyncio.sleep(self.settings.poll_interval_seconds)

            except KeyboardInterrupt:
                logger.info("keyboard_interrupt_received")
                break

            except Exception as e:
                logger.error(
                    "unexpected_error",
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True,
                )
                # Continue running despite errors
                # Interview Point: Resilience
                # - One error shouldn't kill entire system
                # - Log and continue
                # - Alert ops team (in production)
                await asyncio.sleep(5)


def setup_signal_handlers(app: Application, loop: asyncio.AbstractEventLoop) -> None:
    """
    Handle SIGTERM, SIGINT for graceful shutdown.

    Why?
    - Kubernetes sends SIGTERM before killing pod
    - Gives time to finish current cycle, close connections
    - Prevents data loss, connection leaks

    Interview Point - Signal Handling:
    - SIGTERM: Graceful shutdown (finish work)
    - SIGKILL: Immediate kill (no cleanup)
    - Always handle SIGTERM in production
    """

    def signal_handler(sig: int) -> None:
        logger.info("signal_received", signal=sig)

        # Schedule shutdown on event loop
        loop.create_task(app.shutdown())

    # Register handlers
    signal.signal(signal.SIGTERM, lambda s, f: signal_handler(s))
    signal.signal(signal.SIGINT, lambda s, f: signal_handler(s))


async def async_main() -> None:
    """
    Async entry point.

    Interview Point - Startup Sequence:
    1. Load config (fail fast on invalid config)
    2. Configure logging
    3. Build application
    4. Setup signal handlers
    5. Run startup checks
    6. Start main loop
    7. Graceful shutdown
    """
    # Load and validate configuration
    settings = get_settings()

    # Configure logging
    configure_logging(
        log_level=settings.log_level,
        json_logs=settings.json_logs,
    )

    # Create application
    app = Application(settings)

    # Setup signal handlers
    loop = asyncio.get_event_loop()
    setup_signal_handlers(app, loop)

    # Startup
    try:
        async with PolymarketClient(
            base_url=str(settings.polymarket_api_url)
        ) as client:
            app.api_client = client
            await app.startup()

            # Run main loop
            await app.run()

    except Exception as e:
        logger.error(
            "application_error",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        sys.exit(1)

    finally:
        await app.shutdown()


def main() -> NoReturn:
    """
    Synchronous entry point.

    Interview Point - Why separate sync/async entry?
    - main(): Synchronous (called by __main__)
    - async_main(): Asynchronous (actual logic)
    - Allows clean async/await usage
    """
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.info("keyboard_interrupt_main")
    except Exception as e:
        logger.error("fatal_error", error=str(e), exc_info=True)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
