"""
Structured logging configuration using structlog.

Why structlog over stdlib logging?
- Structured output: JSON logs are machine-parseable (splunk, datadog, etc.)
- Context binding: Attach request_id, user_id to all logs in a context
- Performance: Faster than stdlib logging (lazy evaluation)
- Type safety: Structured data instead of string interpolation

Interview Points:
- Production logs should be JSON (not human-readable strings)
- Context binding enables distributed tracing
- Log levels: DEBUG < INFO < WARNING < ERROR < CRITICAL
- Never log sensitive data (passwords, API keys, PII)
"""

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger


def add_app_context(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """
    Add application-wide context to all log messages.

    Adds:
    - app_name: Helps filter logs in centralized logging (e.g., Datadog)
    - environment: dev/staging/prod
    - version: For debugging issues in specific releases

    Why custom processor?
    - Consistent metadata across all logs
    - Easier filtering in log aggregation tools
    - Helps correlate logs across microservices
    """
    event_dict["app_name"] = "polymarket-arbitrage-detector"
    # TODO: Add environment and version from settings or env vars
    return event_dict


def drop_color_message_key(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """
    Remove color codes from event_dict.

    Why?
    - JSON logs don't need colors (consumed by machines)
    - Color codes create noise in log aggregation tools
    - Only useful for human-readable console output
    """
    event_dict.pop("color_message", None)
    return event_dict


def configure_logging(log_level: str = "INFO", json_logs: bool = True) -> None:
    """
    Configure structlog with production-ready settings.

    Args:
        log_level: Minimum log level to output (DEBUG, INFO, WARNING, ERROR)
        json_logs: If True, output JSON (production). If False, human-readable (dev)

    Interview Point - Logging Best Practices:
    1. Structured output: JSON for machines, pretty-print for humans
    2. Context binding: Attach request_id to all logs in a request
    3. Performance: Lazy evaluation, async logging in production
    4. Security: Never log secrets (use processors to redact)

    Example JSON output:
    {
        "event": "arbitrage_detected",
        "timestamp": "2025-01-15T10:30:00.123456Z",
        "level": "info",
        "logger": "src.strategies.price_discrepancy",
        "app_name": "polymarket-arbitrage-detector",
        "market_id": "0x123abc",
        "profit": 0.04
    }

    Example console output (dev):
    2025-01-15 10:30:00 [info     ] arbitrage_detected     market_id=0x123abc profit=0.04
    """

    # Shared processors (used by both JSON and console renderers)
    shared_processors = [
        # Add log level to event dict
        structlog.stdlib.add_log_level,
        # Add logger name to event dict
        structlog.stdlib.add_logger_name,
        # Add timestamp in ISO format
        structlog.processors.TimeStamper(fmt="iso"),
        # If exception in context, format stack trace
        structlog.processors.StackInfoRenderer(),
        # Format exception info if present
        structlog.processors.format_exc_info,
        # Add application context (app_name, version, etc.)
        add_app_context,
    ]

    if json_logs:
        # Production: JSON output for log aggregation
        processors = shared_processors + [
            # Remove color codes (not needed for JSON)
            drop_color_message_key,
            # Render as JSON
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Development: Human-readable colorized output
        processors = shared_processors + [
            # Add colors based on log level
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.plain_traceback,
            )
        ]

    # Configure structlog
    structlog.configure(
        processors=processors,
        # Use stdlib logging as backend (integrates with third-party libs)
        wrapper_class=structlog.stdlib.BoundLogger,
        # Use dict for context (thread-safe)
        context_class=dict,
        # Create stdlib loggers
        logger_factory=structlog.stdlib.LoggerFactory(),
        # Cache loggers (performance optimization)
        cache_logger_on_first_use=True,
    )

    # Configure stdlib logging (used by third-party libraries)
    # Why configure both?
    # - structlog: Our application logs
    # - stdlib logging: httpx, asyncio, etc. logs
    logging.basicConfig(
        format="%(message)s",  # structlog handles formatting
        stream=sys.stdout,
        level=getattr(logging, log_level.upper()),
    )

    # Set log level for noisy third-party libraries
    # Interview Point: Third-party library log management
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> Any:
    """
    Get a structlog logger instance.

    Args:
        name: Logger name (usually __name__ from calling module)

    Returns:
        Bound logger instance

    Usage:
        logger = get_logger(__name__)
        logger.info("market_fetched", market_id="0x123", count=10)

    Interview Point - Why structured logging?
    - Traditional: logger.info(f"Fetched {count} markets for {market_id}")
      Problem: Hard to parse, query, or alert on
    - Structured: logger.info("market_fetched", market_id=market_id, count=count)
      Benefit: Can query 'WHERE event="market_fetched" AND count > 100'
    """
    return structlog.get_logger(name)


def bind_context(**kwargs: Any) -> None:
    """
    Bind context variables to all subsequent logs in this execution context.

    Args:
        **kwargs: Key-value pairs to bind (e.g., request_id, user_id)

    Usage:
        bind_context(request_id="abc-123", market_id="0x456")
        logger.info("processing")  # Includes request_id and market_id
        logger.info("completed")   # Also includes request_id and market_id

    Interview Point - Context Binding for Distributed Tracing:
    - Generate request_id at entry point (e.g., API gateway)
    - Bind to context
    - All logs in that request automatically include request_id
    - Can trace entire request flow through microservices

    Why this matters:
    - User reports bug: "My request failed at 10:30"
    - Search logs: WHERE request_id="abc-123"
    - See entire flow: API → strategy → execution → error
    """
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """
    Clear all bound context variables.

    Usage:
        # At start of new request/cycle
        clear_context()
        bind_context(cycle_id=new_uuid)

    Why clear?
    - Prevents context leaking between requests
    - Especially important in async code (multiple concurrent requests)
    """
    structlog.contextvars.clear_contextvars()


# Example usage for documentation
if __name__ == "__main__":
    # Configure for development (human-readable)
    configure_logging(log_level="DEBUG", json_logs=False)

    logger = get_logger(__name__)

    # Simple log
    logger.info("application_started")

    # Log with context
    logger.info("market_fetched", market_id="0x123abc", price=0.48)

    # Bind context (appears in all subsequent logs)
    bind_context(request_id="req-456", user_id="user-789")

    logger.info("processing_request")  # Includes request_id, user_id
    logger.info("request_completed")  # Also includes request_id, user_id

    # Clear context for next request
    clear_context()

    # Exception logging
    try:
        raise ValueError("Example error")
    except ValueError:
        logger.error("operation_failed", exc_info=True)

    # Warning with additional context
    logger.warning(
        "low_liquidity_detected",
        market_id="0xabc",
        liquidity=500,
        minimum=1000,
        action="skipping_market",
    )
