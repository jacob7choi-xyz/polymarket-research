"""
Resilience patterns for API stability: Circuit Breaker, Retry, Rate Limiting.

Why separate from client.py?
- Single Responsibility: Client handles HTTP, resilience handles failures
- Testability: Can test each pattern independently
- Composability: Mix and match patterns as needed
- Reusability: Can apply to any async function, not just HTTP

Interview Points:
- Circuit Breaker: Prevent cascading failures
- Exponential Backoff: Graceful degradation under load
- Token Bucket: Smooth rate limiting with burst allowance
- Jitter: Prevent thundering herd problem
"""

import asyncio
import random
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from typing import Any, Awaitable, Callable, TypeVar

from ..domain.exceptions import CircuitBreakerOpenError, RateLimitError
from ..monitoring.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


# ============================================================================
# Circuit Breaker Pattern
# ============================================================================


class CircuitBreakerState(Enum):
    """
    Circuit breaker states.

    State transitions:
    CLOSED → OPEN (after failure_threshold failures)
    OPEN → HALF_OPEN (after recovery_timeout seconds)
    HALF_OPEN → CLOSED (on first success)
    HALF_OPEN → OPEN (on failure)

    Interview Point - Why these states?
    - CLOSED: Normal operation, all requests pass through
    - OPEN: Too many failures, reject all requests (fail fast)
    - HALF_OPEN: Testing recovery, allow limited requests
    """

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if recovered


class CircuitBreaker:
    """
    Circuit breaker pattern implementation.

    Prevents cascading failures when downstream service (API) is degraded.

    How it works:
    1. Start in CLOSED state (normal)
    2. Count failures
    3. After N failures → OPEN (reject all requests)
    4. After timeout → HALF_OPEN (test recovery)
    5. If test succeeds → CLOSED (resume normal)
    6. If test fails → OPEN (back to rejecting)

    Interview Point - Why Circuit Breaker?
    - Fail fast: Don't waste resources on doomed requests
    - Prevent queue buildup: API down → requests pile up → memory exhaustion
    - Auto-recovery: Automatically tests if API recovered
    - Backpressure: Signals upstream to slow down

    Real-world example:
    - Polymarket API degraded (high latency, errors)
    - Without circuit breaker: All requests timeout (30s each), queue grows
    - With circuit breaker: After 5 failures, reject immediately, retry after 60s

    Alternative Considered: Simple retry with backoff
    Rejected because: Doesn't prevent request buildup during prolonged outages
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type[Exception] = Exception,
        half_open_max_calls: int = 1,
    ):
        """
        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before testing recovery (OPEN → HALF_OPEN)
            expected_exception: Which exceptions count as failures
            half_open_max_calls: Max concurrent calls allowed in HALF_OPEN state

        Interview Point - Tuning Parameters:
        - failure_threshold: Too low → false positives, too high → slow reaction
        - recovery_timeout: Too short → excessive retries, too long → slow recovery
        - Trade-off: Fast failure detection vs avoiding false alarms
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: datetime | None = None
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitBreakerState:
        """Current circuit breaker state."""
        return self._state

    @property
    def failure_count(self) -> int:
        """Current failure count."""
        return self._failure_count

    def _should_attempt_reset(self) -> bool:
        """
        Check if enough time has passed to attempt recovery.

        Returns True if:
        - State is OPEN
        - recovery_timeout seconds have elapsed since last failure
        """
        if self._state != CircuitBreakerState.OPEN:
            return False

        if self._last_failure_time is None:
            return False

        elapsed = datetime.now() - self._last_failure_time
        return elapsed > timedelta(seconds=self.recovery_timeout)

    async def _on_success(self) -> None:
        """Handle successful call."""
        async with self._lock:
            self._failure_count = 0

            if self._state == CircuitBreakerState.HALF_OPEN:
                self._success_count += 1
                # After first success in HALF_OPEN, transition to CLOSED
                self._state = CircuitBreakerState.CLOSED
                self._half_open_calls = 0
                logger.info(
                    "circuit_breaker.closed",
                    success_count=self._success_count,
                    message="Circuit breaker recovered, resuming normal operation",
                )

    async def _on_failure(self) -> None:
        """Handle failed call."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = datetime.now()

            if self._state == CircuitBreakerState.HALF_OPEN:
                # Failure during recovery test → back to OPEN
                self._state = CircuitBreakerState.OPEN
                self._half_open_calls = 0
                logger.warning(
                    "circuit_breaker.opened",
                    reason="recovery_test_failed",
                    failure_count=self._failure_count,
                )

            elif self._failure_count >= self.failure_threshold:
                # Too many failures → OPEN circuit
                self._state = CircuitBreakerState.OPEN
                logger.warning(
                    "circuit_breaker.opened",
                    reason="threshold_exceeded",
                    failure_count=self._failure_count,
                    threshold=self.failure_threshold,
                    recovery_timeout=self.recovery_timeout,
                )

    def __call__(self, func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        """
        Decorator to wrap async functions with circuit breaker.

        Usage:
            circuit_breaker = CircuitBreaker(failure_threshold=5)

            @circuit_breaker
            async def fetch_data():
                return await api_call()

        Interview Point - Decorator Pattern:
        - Separates cross-cutting concerns (resilience) from business logic
        - Composable: Can stack multiple decorators
        - Pythonic: Familiar pattern for Python developers
        """

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            # Check if should attempt recovery
            if self._should_attempt_reset():
                async with self._lock:
                    if self._state == CircuitBreakerState.OPEN:
                        self._state = CircuitBreakerState.HALF_OPEN
                        self._half_open_calls = 0
                        logger.info(
                            "circuit_breaker.half_open",
                            message="Testing recovery",
                            func=func.__name__,
                        )

            # Check circuit state
            if self._state == CircuitBreakerState.OPEN:
                logger.debug(
                    "circuit_breaker.request_rejected",
                    func=func.__name__,
                    failure_count=self._failure_count,
                )
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is OPEN for {func.__name__}",
                    failure_count=self._failure_count,
                    threshold=self.failure_threshold,
                )

            if self._state == CircuitBreakerState.HALF_OPEN:
                # Limit concurrent calls in HALF_OPEN
                async with self._lock:
                    if self._half_open_calls >= self.half_open_max_calls:
                        logger.debug(
                            "circuit_breaker.half_open_limit",
                            func=func.__name__,
                        )
                        raise CircuitBreakerOpenError(
                            f"Circuit breaker HALF_OPEN call limit reached for {func.__name__}"
                        )
                    self._half_open_calls += 1

            # Execute function
            try:
                result = await func(*args, **kwargs)
                await self._on_success()
                return result

            except self.expected_exception as e:
                await self._on_failure()
                raise

            finally:
                # Decrement HALF_OPEN call count
                if self._state == CircuitBreakerState.HALF_OPEN:
                    async with self._lock:
                        self._half_open_calls = max(0, self._half_open_calls - 1)

        return wrapper

    async def reset(self) -> None:
        """
        Manually reset circuit breaker to CLOSED state.

        Use cases:
        - Manual intervention after investigating issue
        - Testing
        - Forced recovery
        """
        async with self._lock:
            self._state = CircuitBreakerState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            logger.info("circuit_breaker.manually_reset")


# ============================================================================
# Exponential Backoff with Jitter
# ============================================================================


async def retry_with_backoff(
    func: Callable[..., Awaitable[T]],
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> T:
    """
    Retry async function with exponential backoff and jitter.

    Algorithm:
    1. Try function
    2. If fails, wait base_delay * (exponential_base ^ attempt)
    3. Add random jitter to delay
    4. Retry up to max_attempts times

    Args:
        func: Async function to retry
        max_attempts: Maximum retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay (cap for exponential growth)
        exponential_base: Base for exponential backoff (usually 2)
        jitter: Add randomness to delay
        exceptions: Which exceptions to retry

    Returns:
        Function result

    Raises:
        Last exception if all retries exhausted

    Interview Point - Why Exponential Backoff?
    - Linear backoff: Retry every 1s → still hammering degraded API
    - Exponential: 1s, 2s, 4s, 8s → gives API time to recover
    - Max delay: Prevents excessive waiting (exponential grows unbounded)

    Interview Point - Why Jitter?
    - Without jitter: All clients retry at same time (thundering herd)
    - With jitter: Retries spread out, reduces API load spikes
    - AWS best practice: Full jitter (multiply by random 0-1)

    Real-world example:
    - 1000 clients hit rate limit at 12:00:00
    - Without jitter: All retry at 12:00:01 (still rate limited!)
    - With jitter: Retries spread across 0.5s-1.5s window

    Alternative Considered: Fixed delay retry
    Rejected because: Doesn't give API time to recover, causes thundering herd
    """
    last_exception: Exception | None = None

    for attempt in range(max_attempts):
        try:
            return await func()

        except exceptions as e:
            last_exception = e

            # Don't retry on last attempt
            if attempt == max_attempts - 1:
                break

            # Calculate delay: base_delay * (exponential_base ^ attempt)
            delay = min(base_delay * (exponential_base**attempt), max_delay)

            # Add jitter: multiply by random value between 0.5 and 1.5
            # Why 0.5-1.5? Keeps delay in reasonable range while spreading out retries
            if jitter:
                delay *= random.uniform(0.5, 1.5)

            logger.warning(
                "retry_attempt",
                attempt=attempt + 1,
                max_attempts=max_attempts,
                delay_seconds=delay,
                error=str(e),
                error_type=type(e).__name__,
            )

            await asyncio.sleep(delay)

    # All retries exhausted, raise last exception
    logger.error(
        "retry_exhausted",
        max_attempts=max_attempts,
        error=str(last_exception),
        error_type=type(last_exception).__name__ if last_exception else None,
    )

    if last_exception:
        raise last_exception
    raise RuntimeError("Retry failed with no exception (should not happen)")


def with_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """
    Decorator version of retry_with_backoff.

    Usage:
        @with_retry(max_attempts=3, base_delay=1.0)
        async def fetch_data():
            return await api_call()
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            async def call_func() -> T:
                return await func(*args, **kwargs)

            return await retry_with_backoff(
                func=call_func,
                max_attempts=max_attempts,
                base_delay=base_delay,
                max_delay=max_delay,
                exponential_base=exponential_base,
                jitter=jitter,
                exceptions=exceptions,
            )

        return wrapper

    return decorator


# ============================================================================
# Token Bucket Rate Limiter
# ============================================================================


class RateLimiter:
    """
    Token bucket rate limiter.

    How it works:
    1. Bucket starts with 'burst' tokens
    2. Tokens refill at 'rate' per second
    3. Each request consumes 1 token
    4. If no tokens available, wait until refilled

    Interview Point - Why Token Bucket over Fixed Window?

    Fixed Window (e.g., 60 req/min):
    - Allows 60 requests at 00:59:59
    - Then 60 more at 01:00:00
    - Total: 120 requests in 1 second! (boundary effect)

    Token Bucket:
    - Smooths traffic over time
    - Allows bursts (up to bucket size)
    - Maintains average rate
    - No boundary effects

    Industry Usage:
    - AWS API Gateway: Token bucket
    - Stripe API: Token bucket
    - GitHub API: Token bucket
    - Google Cloud: Token bucket

    Real-world example:
    - Rate: 10 req/s, Burst: 20
    - Can burst 20 requests immediately
    - Then sustained 10 req/s
    - Good for handling spiky traffic
    """

    def __init__(self, rate: float, burst: int):
        """
        Args:
            rate: Tokens added per second (sustainable rate)
            burst: Maximum bucket size (allows bursts)

        Example:
            RateLimiter(rate=10.0, burst=20)
            - Sustainable: 10 requests/second
            - Burst: Up to 20 requests immediately
            - Refill: 10 tokens/second

        Interview Point - Choosing Parameters:
        - rate: Based on API limits (Polymarket ~10 req/s safe)
        - burst: 2x rate allows handling spikes
        - Trade-off: Higher burst = more responsive, but can hit limits
        """
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)  # Start with full bucket
        self._last_update = datetime.now()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> None:
        """
        Acquire tokens from bucket.

        If not enough tokens available, waits until refilled.

        Args:
            tokens: Number of tokens to consume (usually 1)

        Interview Point - Why Async?
        - Allows other coroutines to run while waiting
        - Non-blocking: Doesn't freeze entire application
        - Efficient: Single thread can handle many concurrent limiters
        """
        async with self._lock:
            now = datetime.now()
            elapsed = (now - self._last_update).total_seconds()

            # Refill bucket based on elapsed time
            # tokens = min(burst, current + elapsed * rate)
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._last_update = now

            if self._tokens >= tokens:
                # Enough tokens available, consume and proceed
                self._tokens -= tokens
                logger.debug(
                    "rate_limiter.acquired",
                    tokens_consumed=tokens,
                    tokens_remaining=self._tokens,
                )
            else:
                # Not enough tokens, calculate wait time
                tokens_needed = tokens - self._tokens
                wait_time = tokens_needed / self.rate

                logger.debug(
                    "rate_limiter.waiting",
                    tokens_needed=tokens_needed,
                    wait_seconds=wait_time,
                )

                # Wait for tokens to refill
                await asyncio.sleep(wait_time)

                # After waiting, we have exactly 'tokens' available
                self._tokens = 0
                self._last_update = datetime.now()

    def __call__(self, func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        """
        Decorator to rate limit async functions.

        Usage:
            rate_limiter = RateLimiter(rate=10.0, burst=20)

            @rate_limiter
            async def api_call():
                return await fetch()
        """

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            await self.acquire()
            return await func(*args, **kwargs)

        return wrapper

    async def reset(self) -> None:
        """Reset rate limiter (fill bucket)."""
        async with self._lock:
            self._tokens = float(self.burst)
            self._last_update = datetime.now()
            logger.info("rate_limiter.reset")


# Example usage for documentation
if __name__ == "__main__":
    import time

    # Example 1: Circuit Breaker
    circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=5.0)

    @circuit_breaker
    async def flaky_api_call(should_fail: bool = False) -> str:
        """Simulates flaky API."""
        if should_fail:
            raise Exception("API error")
        return "Success"

    async def test_circuit_breaker() -> None:
        print("=== Circuit Breaker Test ===")

        # Trigger failures
        for i in range(5):
            try:
                await flaky_api_call(should_fail=True)
            except Exception as e:
                print(f"Attempt {i+1}: {e}")

        # Circuit should be OPEN now
        try:
            await flaky_api_call(should_fail=False)
        except CircuitBreakerOpenError as e:
            print(f"Circuit OPEN: {e}")

        print(f"Circuit state: {circuit_breaker.state}")

    # Example 2: Retry with Backoff
    async def test_retry() -> None:
        print("\n=== Retry with Backoff Test ===")

        call_count = 0

        async def failing_then_success() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception(f"Attempt {call_count} failed")
            return "Success!"

        result = await retry_with_backoff(
            failing_then_success, max_attempts=5, base_delay=0.5, jitter=True
        )
        print(f"Result: {result} (after {call_count} attempts)")

    # Example 3: Rate Limiter
    async def test_rate_limiter() -> None:
        print("\n=== Rate Limiter Test ===")

        rate_limiter = RateLimiter(rate=5.0, burst=10)  # 5 req/s, burst of 10

        start = time.time()

        # Make 15 requests (should take ~1 second due to rate limiting)
        for i in range(15):
            await rate_limiter.acquire()
            elapsed = time.time() - start
            print(f"Request {i+1} at {elapsed:.2f}s")

    # Run tests
    async def run_all_tests() -> None:
        await test_circuit_breaker()
        await test_retry()
        await test_rate_limiter()

    asyncio.run(run_all_tests())
