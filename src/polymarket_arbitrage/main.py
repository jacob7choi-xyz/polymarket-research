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
from decimal import Decimal
import json
import signal
import sys
from typing import Any, NoReturn
import uuid

from .api.client import DEPENDENCY_FAULTS, PolymarketClient
from .api.resilience import CircuitBreaker, RateLimiter
from .config.constants import MAX_MARKET_PAGES
from .config.settings import Settings, get_settings
from .domain.exceptions import APIError, PolymarketError
from .domain.models import Market, ResolutionStatus, Token
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

        The API client is injected by the caller, which owns its lifecycle via
        `async with`. Building one here would discard the entered client and
        leave an instance with no underlying session.

        Raises:
            RuntimeError: If api_client was not injected before startup.

        Interview Point - Initialization Order:
        - Bottom-up: Build from dependencies to dependents
        - Fail fast: Validate everything before starting
        - Health checks: Verify external dependencies work
        """
        if self.api_client is None:
            raise RuntimeError(
                "api_client must be injected before startup(). "
                "Enter PolymarketClient as an async context manager and assign it."
            )

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

        # Layer 2: Resilience -- owned by the injected client, which applies it to every
        # request. Read the references rather than constructing parallel instances, so the
        # breaker reported in metrics is the one actually gating requests.
        self.rate_limiter = self.api_client.rate_limiter
        self.circuit_breaker = self.api_client.circuit_breaker

        # Layer 3: API Client is injected by the caller (see docstring)

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
        3. Save state / log final metrics

        The API client is closed by whoever entered it, not here -- closing an
        injected resource we do not own would break a caller that intends to
        reuse it.

        Interview Point - Graceful Shutdown:
        - Kubernetes sends SIGTERM, waits, then SIGKILL
        - Complete current work before exiting
        - Log final state for debugging
        """
        logger.info("application_shutting_down")
        self.running = False

        # Log final performance
        if self.paper_trader:
            performance = self.paper_trader.get_performance_summary()
            logger.info("final_performance", **performance)

        logger.info("application_stopped")

    async def _fetch_markets(self) -> list[Market]:
        """
        Fetch active markets from Polymarket Gamma API.

        Fetches paginated market data, filters for binary YES/NO markets
        with meaningful volume, and converts to domain models.

        Returns:
            List of Market domain objects
        """
        markets: list[Market] = []

        if not self.api_client:
            logger.error("api_client_not_initialized")
            return markets

        try:
            # Fetch markets with pagination
            # Gamma API returns a flat list, supports limit/offset
            all_raw_markets: list[dict[str, Any]] = []
            offset = 0
            limit = 100  # Max per request

            for _page in range(MAX_MARKET_PAGES):
                params: dict[str, Any] = {
                    "active": "true",
                    "closed": "false",
                    "limit": str(limit),
                    "offset": str(offset),
                }

                try:
                    data = await self.api_client.get_json("/markets", params=params)
                except APIError as e:
                    # Gamma rejects deep offsets with HTTP 422. Stop paging and
                    # keep what we already have rather than losing the cycle.
                    logger.warning(
                        "market_pagination_stopped",
                        offset=offset,
                        collected=len(all_raw_markets),
                        error=str(e),
                    )
                    break

                # API returns a flat list
                if isinstance(data, list):
                    batch = data
                elif isinstance(data, dict) and "markets" in data:
                    batch = data["markets"]
                else:
                    logger.warning("unexpected_response_format", type=type(data).__name__)
                    break

                if not batch:
                    break

                all_raw_markets.extend(batch)
                logger.debug(
                    "markets_batch_fetched", batch_size=len(batch), total=len(all_raw_markets)
                )

                # Stop if we got fewer than the limit (last page)
                if len(batch) < limit:
                    break

                offset += limit

            logger.info("raw_markets_fetched", total=len(all_raw_markets))

            # Convert to domain models, filtering for valid binary markets
            for raw in all_raw_markets:
                market = self._parse_gamma_market(raw)
                if market is not None:
                    markets.append(market)

            logger.info("markets_parsed", valid=len(markets), total=len(all_raw_markets))

        except Exception as e:
            logger.error("market_fetch_failed", error=str(e), error_type=type(e).__name__)

        return markets

    async def _settle_open_positions(self) -> int:
        """Settle open positions whose markets are confirmed resolved.

        The composition root does this because it owns both the API client and the
        trader; the execution layer has no API dependency and must not acquire one.

        Resolution is read from Gamma's own fields rather than inferred from the end
        date. Measured across 32 markets, 100% closed *after* their end date -- median
        0.8 hours later, up to 11.7 hours -- so settling on the end date would credit
        capital while the position was still unredeemable.

        Any market whose status cannot be established is reported UNKNOWN and its
        position stays open. Failing to reach the API must not look like resolution.

        Returns:
            Number of positions settled.
        """
        if not self.paper_trader or not self.api_client:
            return 0

        open_positions = self.paper_trader.position_tracker.get_open_positions()
        if not open_positions:
            return 0

        statuses: dict[str, ResolutionStatus] = {}
        for position in open_positions:
            statuses[position.market_id] = await self._fetch_resolution_status(position.market_id)

        settled = self.paper_trader.settle_positions(statuses)
        logger.info(
            "settlement_checked",
            positions_open=len(open_positions),
            positions_settled=settled,
            unknown=sum(1 for s in statuses.values() if s is ResolutionStatus.UNKNOWN),
        )
        return settled

    async def _fetch_resolution_status(self, market_id: str) -> ResolutionStatus:
        """Read a market's resolution status from Gamma's oracle field.

        RESOLVED requires ``umaResolutionStatus == "resolved"`` and nothing else. Two
        measured facts drove that choice:

        1. The oracle has intermediate states. A market observed live reported
           ``umaResolutionStatus="proposed"`` -- a resolution has been proposed but not
           finalised, so the position is not yet redeemable. Only "resolved" is terminal.
        2. ``closed`` is not usable as a second signal, because the list and single-market
           endpoints contradict each other. For market 3037521 at the same moment, the
           list endpoint returned ``closed=True, umaResolutionStatus="resolved"`` while
           ``/markets/{id}`` returned ``closed=False, umaResolutionStatus="proposed"``.
           Requiring a field whose value depends on which endpoint you ask would either
           settle early or strand positions forever, depending on the direction of the
           disagreement.

        Any failure to establish the status returns UNKNOWN, which leaves the position
        open. Catching PolymarketError rather than APIError matters: MarketNotFoundError
        descends from DataValidationError, so a 404 on a delisted market would otherwise
        escape and abort settlement for every other position in the cycle.
        """
        if not self.api_client:
            return ResolutionStatus.UNKNOWN
        try:
            raw = await self.api_client.get_json(f"/markets/{market_id}")
        except PolymarketError as e:
            logger.warning(
                "resolution_status_unavailable",
                market_id=market_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return ResolutionStatus.UNKNOWN

        if not isinstance(raw, dict):
            logger.warning("resolution_status_unexpected_shape", market_id=market_id)
            return ResolutionStatus.UNKNOWN

        uma_status = str(raw.get("umaResolutionStatus") or "").lower()
        if uma_status == "resolved":
            return ResolutionStatus.RESOLVED
        if not uma_status:
            # Never entered the oracle process; we cannot assert either state
            logger.debug("resolution_status_absent", market_id=market_id)
            return ResolutionStatus.UNKNOWN
        return ResolutionStatus.UNRESOLVED

    def _parse_gamma_market(self, raw: dict[str, Any]) -> Market | None:
        """
        Parse a raw Gamma API market dict into a domain Market.

        The Gamma API returns a flat structure with parallel arrays:
        - outcomes: ["Yes", "No"]
        - outcomePrices: ["0.48", "0.52"]
        - clobTokenIds: ["<yes_token_id>", "<no_token_id>"]

        Returns None for markets that are not valid binary markets
        or don't meet volume/liquidity thresholds.
        """
        try:
            # Must be a binary market with outcomes and prices
            # Gamma API returns these as JSON strings, not lists
            outcomes_raw = raw.get("outcomes", "[]")
            prices_raw = raw.get("outcomePrices", "[]")
            token_ids_raw = raw.get("clobTokenIds", "[]")

            outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            token_ids = (
                json.loads(token_ids_raw) if isinstance(token_ids_raw, str) else token_ids_raw
            )

            if not outcomes or not prices or len(outcomes) != 2 or len(prices) != 2:
                return None

            # Must have token IDs for order book trading
            if not token_ids or len(token_ids) != 2:
                return None

            # Must be accepting orders
            if not raw.get("acceptingOrders", False):
                return None

            # Parse volume (use 24hr volume for activity check)
            volume_24hr = Decimal(str(raw.get("volume24hr", 0) or 0))
            liquidity = Decimal(str(raw.get("liquidity", 0) or 0))

            # Filter: skip low-volume/low-liquidity markets
            if volume_24hr < self.settings.min_volume_usd:
                return None
            if liquidity < self.settings.min_liquidity_usd:
                return None

            # Map outcomes to YES/NO tokens
            # outcomes[0] corresponds to prices[0] and token_ids[0]
            yes_token = None
            no_token = None

            for i, outcome in enumerate(outcomes):
                outcome_upper = outcome.strip().upper()
                price = Decimal(str(prices[i]))
                tid = str(token_ids[i])

                if outcome_upper in ("YES", "Y"):
                    yes_token = Token(token_id=tid, outcome="Yes", price=price)
                elif outcome_upper in ("NO", "N"):
                    no_token = Token(token_id=tid, outcome="No", price=price)

            if not yes_token or not no_token:
                return None

            return Market(
                market_id=str(raw.get("id", "")),
                condition_id=raw.get("conditionId", ""),
                question=raw.get("question", ""),
                yes_token=yes_token,
                no_token=no_token,
                volume=volume_24hr,
                liquidity=liquidity,
                end_date=raw.get("endDate", "2099-01-01T00:00:00Z"),
                active=raw.get("active", True),
            )

        except (ValueError, KeyError, IndexError) as e:
            logger.debug(
                "market_parse_skipped",
                market_id=raw.get("id", "unknown"),
                error=str(e),
            )
            return None

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

            # Settle first, so capital returned by resolved positions is available to
            # this cycle's trades rather than idling until the next one
            await self._settle_open_positions()

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
            update_position_count(int(performance["open_positions"]))

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

    # Resilience is constructed here and injected into the client, which applies it to
    # every request rather than relying on each call site to remember.
    rate_limiter = RateLimiter(
        rate=settings.rate_limit_requests_per_second,
        burst=settings.rate_limit_burst,
    )
    circuit_breaker = CircuitBreaker(
        failure_threshold=settings.circuit_breaker_failure_threshold,
        recovery_timeout=settings.circuit_breaker_recovery_timeout_seconds,
        # Only dependency-health faults count. A deterministic 4xx means this request was
        # unacceptable, not that Gamma is down -- and Gamma returns a routine 422 at its
        # pagination ceiling on every cycle.
        expected_exception=DEPENDENCY_FAULTS,
    )

    # Startup
    try:
        async with PolymarketClient(
            base_url=str(settings.polymarket_api_url),
            rate_limiter=rate_limiter,
            circuit_breaker=circuit_breaker,
            retry_max_attempts=settings.retry_max_attempts,
            retry_base_delay=settings.retry_base_delay_seconds,
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
