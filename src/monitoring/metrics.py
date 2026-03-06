"""
Prometheus-style metrics for observability.

Why Prometheus?
- Industry standard: Used by Kubernetes, Grafana, etc.
- Pull model: Scrapes metrics endpoint (doesn't slow app)
- Time series: Analyze trends over time
- Rich query language: PromQL for complex analysis

Interview Points:
- Golden Signals (Google SRE): Latency, Traffic, Errors, Saturation
- Business metrics: Opportunities detected, trades executed, P&L
- Labels: Dimensions for filtering (endpoint, status, strategy)
- Histogram vs Counter vs Gauge: Different metric types for different use cases
"""

import time
from functools import wraps
from typing import Any, Awaitable, Callable, TypeVar

from prometheus_client import Counter, Gauge, Histogram, Info

from ..monitoring.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

# ============================================================================
# Counter Metrics (monotonically increasing)
# ============================================================================

OPPORTUNITIES_DETECTED = Counter(
    "arbitrage_opportunities_detected_total",
    "Total number of arbitrage opportunities detected",
    ["strategy"],  # Label: which strategy detected it
)

TRADES_EXECUTED = Counter(
    "trades_executed_total",
    "Total number of trades executed",
    ["status"],  # Labels: success, failure
)

API_REQUESTS = Counter(
    "polymarket_api_requests_total",
    "Total number of API requests",
    ["endpoint", "status_code"],  # Labels: which endpoint, what status
)

MARKETS_ANALYZED = Counter(
    "markets_analyzed_total",
    "Total number of markets analyzed for arbitrage",
)

MARKETS_FILTERED = Counter(
    "markets_filtered_total",
    "Total number of markets filtered out",
    ["reason"],  # Label: why filtered (low_liquidity, expired, etc.)
)

# ============================================================================
# Histogram Metrics (distribution of values)
# ============================================================================

API_LATENCY = Histogram(
    "polymarket_api_latency_seconds",
    "API request latency in seconds",
    ["endpoint"],
    # Buckets: Expected latencies for API requests
    # Interview Point: Bucket design matters
    # - Too few: Poor resolution
    # - Too many: High cardinality, storage cost
    # - Tailored to expected values (API typically 0.1-10s)
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

ARBITRAGE_PROFIT_PER_DOLLAR = Histogram(
    "arbitrage_profit_per_dollar",
    "Profit per dollar invested in arbitrage",
    # Buckets: Typical arbitrage profits (0.1% to 10%)
    buckets=[0.001, 0.005, 0.01, 0.02, 0.05, 0.1],
)

DETECTION_CYCLE_DURATION = Histogram(
    "detection_cycle_duration_seconds",
    "Time to complete one detection cycle (fetch + analyze)",
    buckets=[1, 5, 10, 30, 60, 120, 300],
)

# ============================================================================
# Gauge Metrics (current value, can go up or down)
# ============================================================================

OPEN_POSITIONS = Gauge(
    "open_positions",
    "Number of currently open arbitrage positions",
)

AVAILABLE_CAPITAL = Gauge(
    "available_capital_usd",
    "Available capital for trading in USD",
)

CAPITAL_DEPLOYED = Gauge(
    "capital_deployed_usd",
    "Capital currently deployed in positions in USD",
)

TOTAL_PNL = Gauge(
    "total_pnl_usd",
    "Total profit/loss (realized + unrealized) in USD",
)

UNREALIZED_PNL = Gauge(
    "unrealized_pnl_usd",
    "Unrealized profit/loss from open positions in USD",
)

REALIZED_PNL = Gauge(
    "realized_pnl_usd",
    "Realized profit/loss from closed positions in USD",
)

CIRCUIT_BREAKER_STATE = Gauge(
    "circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=half_open, 2=open)",
    ["circuit_breaker"],  # Label: which circuit breaker
)

# ============================================================================
# Info Metrics (metadata, doesn't change)
# ============================================================================

APP_INFO = Info(
    "arbitrage_detector_info",
    "Information about the arbitrage detector application",
)

# Initialize app info
# Interview Point: Helps correlate metrics with versions
APP_INFO.info(
    {
        "app_name": "polymarket-arbitrage-detector",
        "mode": "paper_trading",
    }
)


# ============================================================================
# Metric Decorators
# ============================================================================


def track_api_call(endpoint: str) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """
    Decorator to track API call metrics.

    Tracks:
    - Request count (by endpoint, status code)
    - Latency (by endpoint)

    Usage:
        @track_api_call("/markets")
        async def get_markets():
            ...

    Interview Point - Decorator Pattern for Cross-Cutting Concerns:
    - Metrics collection is cross-cutting (needed everywhere)
    - Decorator separates concerns (business logic vs metrics)
    - Easy to add/remove without touching business code
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            start = time.time()
            status_code = "200"  # Default success

            try:
                result = await func(*args, **kwargs)
                return result

            except Exception as e:
                # Extract status code from exception if available
                status_code = str(getattr(e, "status_code", "500"))
                raise

            finally:
                # Record request
                API_REQUESTS.labels(endpoint=endpoint, status_code=status_code).inc()

                # Record latency
                duration = time.time() - start
                API_LATENCY.labels(endpoint=endpoint).observe(duration)

                logger.debug(
                    "api_call_tracked",
                    endpoint=endpoint,
                    status_code=status_code,
                    duration_seconds=duration,
                )

        return wrapper

    return decorator


def track_detection_cycle(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    """
    Decorator to track detection cycle duration.

    Usage:
        @track_detection_cycle
        async def run_detection_cycle():
            ...

    Interview Point - Performance Monitoring:
    - Track how long each cycle takes
    - Alert if cycles take too long (degraded performance)
    - Identify bottlenecks (is fetching or analysis slow?)
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> T:
        start = time.time()

        try:
            result = await func(*args, **kwargs)
            return result

        finally:
            duration = time.time() - start
            DETECTION_CYCLE_DURATION.observe(duration)

            logger.debug(
                "detection_cycle_tracked",
                duration_seconds=duration,
            )

    return wrapper


# ============================================================================
# Metric Update Functions
# ============================================================================


def record_opportunity_detected(strategy: str, profit_per_dollar: float) -> None:
    """
    Record arbitrage opportunity detection.

    Args:
        strategy: Strategy name (e.g., "price_discrepancy")
        profit_per_dollar: Profit per dollar invested
    """
    OPPORTUNITIES_DETECTED.labels(strategy=strategy).inc()
    ARBITRAGE_PROFIT_PER_DOLLAR.observe(profit_per_dollar)

    logger.debug(
        "opportunity_metric_recorded",
        strategy=strategy,
        profit_per_dollar=profit_per_dollar,
    )


def record_trade_executed(success: bool) -> None:
    """
    Record trade execution.

    Args:
        success: Whether trade was successful
    """
    status = "success" if success else "failure"
    TRADES_EXECUTED.labels(status=status).inc()

    logger.debug(
        "trade_metric_recorded",
        status=status,
    )


def record_market_analyzed() -> None:
    """Record that a market was analyzed."""
    MARKETS_ANALYZED.inc()


def record_market_filtered(reason: str) -> None:
    """
    Record that a market was filtered out.

    Args:
        reason: Why market was filtered (e.g., "low_liquidity", "expired")
    """
    MARKETS_FILTERED.labels(reason=reason).inc()


def update_capital_metrics(
    available: float,
    deployed: float,
    total_pnl: float,
    unrealized_pnl: float,
    realized_pnl: float,
) -> None:
    """
    Update capital and P&L metrics.

    Args:
        available: Available capital (USD)
        deployed: Capital deployed in positions (USD)
        total_pnl: Total P&L (realized + unrealized)
        unrealized_pnl: Unrealized P&L
        realized_pnl: Realized P&L

    Interview Point - Gauge Metrics:
    - Can go up or down (unlike counters)
    - Represent current state
    - Useful for dashboards (current capital, P&L)
    """
    AVAILABLE_CAPITAL.set(available)
    CAPITAL_DEPLOYED.set(deployed)
    TOTAL_PNL.set(total_pnl)
    UNREALIZED_PNL.set(unrealized_pnl)
    REALIZED_PNL.set(realized_pnl)

    logger.debug(
        "capital_metrics_updated",
        available_capital=available,
        capital_deployed=deployed,
        total_pnl=total_pnl,
    )


def update_position_count(count: int) -> None:
    """
    Update open position count.

    Args:
        count: Number of open positions
    """
    OPEN_POSITIONS.set(count)


def update_circuit_breaker_state(name: str, state: str) -> None:
    """
    Update circuit breaker state.

    Args:
        name: Circuit breaker name
        state: State (closed, half_open, open)

    Maps to numeric:
    - closed: 0
    - half_open: 1
    - open: 2

    Interview Point - Enum to Number Mapping:
    - Prometheus doesn't support string values in gauges
    - Map enum to number for storage
    - Label provides human-readable context
    """
    state_map = {
        "closed": 0,
        "half_open": 1,
        "open": 2,
    }

    CIRCUIT_BREAKER_STATE.labels(circuit_breaker=name).set(
        state_map.get(state.lower(), -1)
    )


# Example usage for documentation
if __name__ == "__main__":
    """
    Example: Using metrics

    Interview Point - Observability Philosophy:
    - Metrics: What is happening (quantitative)
    - Logs: Why it happened (qualitative)
    - Traces: How it happened (flow)
    - All three needed for complete observability
    """

    print("=== Metrics Demo ===\n")

    # Record some metrics
    record_opportunity_detected("price_discrepancy", 0.04)
    record_opportunity_detected("price_discrepancy", 0.02)
    record_trade_executed(success=True)
    record_trade_executed(success=True)
    record_trade_executed(success=False)

    # Update gauges
    update_capital_metrics(
        available=9500.0,
        deployed=500.0,
        total_pnl=20.0,
        unrealized_pnl=20.0,
        realized_pnl=0.0,
    )

    update_position_count(5)

    # Circuit breaker
    update_circuit_breaker_state("polymarket_api", "closed")

    print("Metrics recorded successfully!")
    print("\nTo view metrics:")
    print("1. Start Prometheus")
    print("2. Expose metrics endpoint: GET /metrics")
    print("3. Prometheus scrapes endpoint periodically")
    print("4. Query with PromQL in Grafana")
    print("\nExample queries:")
    print("  - rate(trades_executed_total[5m])")
    print("  - histogram_quantile(0.95, api_latency_seconds)")
    print("  - available_capital_usd")
