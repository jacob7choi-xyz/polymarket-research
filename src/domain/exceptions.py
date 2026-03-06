"""
Custom exception hierarchy for the arbitrage detection system.

Why custom exceptions?
- Precise error handling: Catch specific errors, not generic Exception
- Context preservation: Include relevant data (market_id, status_code, etc.)
- Clean error handling: Callers can distinguish API errors from business logic errors

Interview Point - Exception Design:
- Inherit from a base exception for easy catching
- Include context in exception (which endpoint? what data?)
- Distinguish recoverable vs non-recoverable errors
- Use for control flow only when appropriate (not for validation)
"""


class PolymarketError(Exception):
    """
    Base exception for all Polymarket arbitrage detector errors.

    Why base exception?
    - Can catch all application errors with: except PolymarketError
    - Distinguishes our errors from third-party library errors
    - Enables error tracking/monitoring (e.g., Sentry)

    Interview Point: Exception hierarchy design pattern
    """

    pass


# ============================================================================
# API Layer Exceptions
# ============================================================================


class APIError(PolymarketError):
    """
    Base class for API-related errors.

    Hierarchy:
        PolymarketError → APIError → RateLimitError, CircuitBreakerOpenError, etc.

    Why separate API errors?
    - Different handling: API errors → retry, business logic errors → don't retry
    - Monitoring: Track API error rates separately
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        endpoint: str | None = None,
        response_data: dict | None = None,
    ):
        """
        Args:
            message: Human-readable error description
            status_code: HTTP status code (if applicable)
            endpoint: API endpoint that failed
            response_data: Raw response data for debugging
        """
        super().__init__(message)
        self.status_code = status_code
        self.endpoint = endpoint
        self.response_data = response_data

    def __str__(self) -> str:
        """
        Include context in error message.

        Example: "API request failed (500): /markets/0x123 - Internal server error"
        """
        parts = [self.args[0]]
        if self.status_code:
            parts[0] = f"{parts[0]} ({self.status_code})"
        if self.endpoint:
            parts.append(f"endpoint={self.endpoint}")
        return " - ".join(parts)


class RateLimitError(APIError):
    """
    Raised when API rate limit is exceeded.

    Why separate exception?
    - Specific handling: Backoff longer than other errors
    - Monitoring: Track rate limit hits (may need to adjust limits)
    - Alerting: High rate limit errors → may need API key upgrade

    Interview Point: Recoverable vs Non-recoverable
    - Rate limit: Recoverable (wait and retry)
    - Authentication: Non-recoverable (fix credentials)
    """

    def __init__(
        self,
        message: str = "API rate limit exceeded",
        retry_after: int | None = None,
        **kwargs,
    ):
        """
        Args:
            message: Error description
            retry_after: Seconds until rate limit resets (from Retry-After header)
            **kwargs: Passed to APIError (status_code, endpoint, etc.)
        """
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class TimeoutError(APIError):
    """
    Raised when API request times out.

    Why separate from generic APIError?
    - Indicates network issues or API slowness
    - May need different retry strategy (longer timeout)
    - Monitoring: Track timeout rates (correlate with API degradation)
    """

    def __init__(self, message: str = "API request timed out", **kwargs):
        super().__init__(message, **kwargs)


class ConnectionError(APIError):
    """
    Raised when cannot connect to API.

    Indicates:
    - API is down
    - Network connectivity issues
    - DNS resolution failures

    Interview Point: Network failure handling
    - Transient: Retry with backoff
    - Persistent: Circuit breaker opens, alert ops team
    """

    def __init__(self, message: str = "Failed to connect to API", **kwargs):
        super().__init__(message, **kwargs)


class CircuitBreakerOpenError(PolymarketError):
    """
    Raised when circuit breaker is open (rejecting requests).

    Why separate from APIError?
    - Not actually an API call (rejected before calling API)
    - Different handling: Don't retry immediately, wait for recovery
    - Indicates cascading failure prevention in action

    Interview Point: Circuit Breaker Pattern
    - CLOSED: Normal operation, requests go through
    - OPEN: Too many failures, reject all requests (fail fast)
    - HALF_OPEN: Testing recovery, allow limited requests
    """

    def __init__(
        self,
        message: str = "Circuit breaker is open, rejecting requests",
        failure_count: int = 0,
        threshold: int = 0,
    ):
        super().__init__(message)
        self.failure_count = failure_count
        self.threshold = threshold


# ============================================================================
# Data/Validation Exceptions
# ============================================================================


class DataValidationError(PolymarketError):
    """
    Base class for data validation errors.

    Used when:
    - API returns unexpected response format
    - Pydantic validation fails
    - Data integrity checks fail
    """

    pass


class MarketNotFoundError(DataValidationError):
    """
    Raised when market ID not found in API.

    Why specific exception?
    - Common case: User provides invalid market_id
    - Clear error message for user
    - Don't retry (market doesn't exist)
    """

    def __init__(self, market_id: str):
        super().__init__(f"Market not found: {market_id}")
        self.market_id = market_id


class InvalidMarketDataError(DataValidationError):
    """
    Raised when market data fails validation.

    Examples:
    - Missing required fields (yes_token, no_token)
    - Invalid price (< 0 or > 1)
    - Inconsistent data (end_date in past but market still active)

    Interview Point: Fail fast principle
    - Validate data at boundaries (API response → domain model)
    - Better to fail loudly than silently use bad data
    - Invalid data → log and skip, don't crash entire system
    """

    def __init__(
        self, message: str, market_id: str | None = None, validation_errors: list | None = None
    ):
        super().__init__(message)
        self.market_id = market_id
        self.validation_errors = validation_errors or []


class InvalidTokenDataError(DataValidationError):
    """
    Raised when token data (YES/NO) is invalid or missing.

    Common causes:
    - API returns market without tokens
    - Token price is null or invalid
    - Missing YES or NO token
    """

    def __init__(self, message: str, market_id: str | None = None):
        super().__init__(message)
        self.market_id = market_id


# ============================================================================
# Business Logic Exceptions
# ============================================================================


class StrategyError(PolymarketError):
    """
    Base class for strategy execution errors.

    Used when:
    - Strategy configuration is invalid
    - Strategy detects impossible condition
    - Strategy encounters unexpected market state
    """

    pass


class InsufficientLiquidityError(StrategyError):
    """
    Raised when market liquidity is too low for safe execution.

    Why separate exception?
    - Common filter condition
    - Not an error per se, just market not suitable
    - Monitoring: Track how often we skip due to liquidity
    """

    def __init__(self, market_id: str, liquidity: float, minimum: float):
        super().__init__(
            f"Insufficient liquidity: {liquidity} < {minimum} for market {market_id}"
        )
        self.market_id = market_id
        self.liquidity = liquidity
        self.minimum = minimum


# ============================================================================
# Execution Exceptions
# ============================================================================


class ExecutionError(PolymarketError):
    """
    Base class for trade execution errors.

    Used when:
    - Order placement fails
    - Slippage exceeds limits
    - Position tracking fails
    """

    pass


class InsufficientCapitalError(ExecutionError):
    """
    Raised when insufficient capital for trade.

    Why specific exception?
    - Common case in paper trading (ran out of capital)
    - Should pause trading, not crash
    - Monitoring: Alert when approaching capital limits
    """

    def __init__(self, required: float, available: float):
        super().__init__(f"Insufficient capital: required {required}, available {available}")
        self.required = required
        self.available = available


class OrderExecutionError(ExecutionError):
    """
    Raised when order execution fails.

    Examples:
    - Order rejected by exchange
    - Slippage too high
    - Partial fill when full fill required
    """

    def __init__(
        self,
        message: str,
        market_id: str | None = None,
        order_details: dict | None = None,
    ):
        super().__init__(message)
        self.market_id = market_id
        self.order_details = order_details


# ============================================================================
# Configuration Exceptions
# ============================================================================


class ConfigurationError(PolymarketError):
    """
    Raised when configuration is invalid.

    Examples:
    - Required environment variable missing
    - Invalid config value (negative timeout)
    - Conflicting settings (max_position > initial_capital)

    Interview Point: Fail fast at startup
    - Validate all configuration before starting
    - Better to crash immediately than fail during trading
    - Clear error messages help operators fix issues quickly
    """

    pass


# Example usage for documentation
if __name__ == "__main__":
    # Example 1: API error with context
    try:
        raise APIError(
            "Failed to fetch market",
            status_code=500,
            endpoint="/markets/0x123",
            response_data={"error": "Internal server error"},
        )
    except APIError as e:
        print(f"API Error: {e}")
        print(f"Status code: {e.status_code}")
        print(f"Endpoint: {e.endpoint}")

    # Example 2: Rate limit with retry_after
    try:
        raise RateLimitError(retry_after=60)
    except RateLimitError as e:
        print(f"Rate limited. Retry after {e.retry_after} seconds")

    # Example 3: Catching all application errors
    try:
        raise MarketNotFoundError("0xabc123")
    except PolymarketError as e:
        print(f"Application error: {e}")

    # Example 4: Circuit breaker
    try:
        raise CircuitBreakerOpenError(failure_count=5, threshold=5)
    except CircuitBreakerOpenError as e:
        print(f"Circuit breaker open: {e.failure_count}/{e.threshold} failures")
