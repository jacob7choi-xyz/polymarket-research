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

from collections.abc import Awaitable, Callable
from functools import wraps
import time
from typing import Any, TypeVar

from prometheus_client import Counter, Gauge, Histogram, Info, start_http_server

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

# ============================================================================
# Histogram Metrics (distribution of values)
# ============================================================================

ARBITRAGE_PROFIT_PER_DOLLAR = Histogram(
    "arbitrage_profit_per_dollar",
    # Measures profit per BUNDLE (1 - (yes + no)), not return on capital invested.
    # At a bundle cost of 0.96 these differ: 0.0400 per bundle vs 0.0417 return on
    # cost. The metric name predates that distinction; renaming it touches 20 call
    # sites across the domain model, strategy and executor, so the correction is
    # recorded in the README rather than bundled into a monitoring change.
    "Arbitrage profit per bundle: 1 - (yes_price + no_price). Not return on cost.",
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


def start_metrics_server(port: int) -> None:
    """Expose the metrics registry over HTTP so Prometheus can scrape it.

    Without this the metrics are recorded in-process and never leave it: every counter and
    gauge below updates correctly, no endpoint serves them, and a Prometheus scrape target
    pointed at this process reports DOWN. Recording a metric and publishing it are separate
    steps, and only the first was previously wired.

    prometheus_client serves on a daemon thread, so this does not block the event loop and
    does not need awaiting.

    Args:
        port: TCP port for the /metrics endpoint. Must match the scrape target in
            monitoring/prometheus.yml.
    """
    start_http_server(port)
    logger.info("metrics_server_started", port=port, endpoint=f"http://0.0.0.0:{port}/metrics")


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
        start = time.monotonic()

        try:
            result = await func(*args, **kwargs)
            return result

        finally:
            duration = time.monotonic() - start
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

    numeric_state = state_map.get(state.lower(), -1)
    if numeric_state == -1:
        logger.warning("unknown_circuit_breaker_state", name=name, state=state)
    CIRCUIT_BREAKER_STATE.labels(circuit_breaker=name).set(numeric_state)


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
