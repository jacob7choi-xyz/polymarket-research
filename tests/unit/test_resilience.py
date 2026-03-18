"""Tests for API resilience patterns: CircuitBreaker, retry_with_backoff, RateLimiter."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from polymarket_arbitrage.api.resilience import (
    CircuitBreaker,
    CircuitBreakerState,
    RateLimiter,
    retry_with_backoff,
    with_retry,
)
from polymarket_arbitrage.domain.exceptions import CircuitBreakerOpenError


@pytest.mark.unit
class TestCircuitBreaker:
    """Tests for CircuitBreaker resilience pattern."""

    @pytest.fixture
    def cb(self) -> CircuitBreaker:
        """Circuit breaker with low thresholds for testing."""
        return CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=10.0,
            expected_exception=ValueError,
            half_open_max_calls=1,
        )

    @pytest.mark.asyncio
    async def test_initial_state_is_closed(self, cb: CircuitBreaker) -> None:
        """Circuit breaker starts in CLOSED state."""
        assert cb.state == CircuitBreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_single_failure_does_not_open(self, cb: CircuitBreaker) -> None:
        """One failure should not open the circuit (threshold is 3)."""

        @cb
        async def failing() -> str:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await failing()

        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 1

    @pytest.mark.asyncio
    async def test_opens_after_failure_threshold(self, cb: CircuitBreaker) -> None:
        """Circuit opens after failure_threshold consecutive failures."""

        @cb
        async def failing() -> str:
            raise ValueError("boom")

        for _ in range(3):
            with pytest.raises(ValueError):
                await failing()

        assert cb.state == CircuitBreakerState.OPEN
        assert cb.failure_count == 3

    @pytest.mark.asyncio
    async def test_rejects_calls_when_open(self, cb: CircuitBreaker) -> None:
        """OPEN circuit raises CircuitBreakerOpenError immediately."""

        @cb
        async def failing() -> str:
            raise ValueError("boom")

        for _ in range(3):
            with pytest.raises(ValueError):
                await failing()

        with pytest.raises(CircuitBreakerOpenError):
            await failing()

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self, cb: CircuitBreaker) -> None:
        """A success resets the failure counter to zero."""
        call_count = 0

        @cb
        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ValueError("temporary")
            return "ok"

        for _ in range(2):
            with pytest.raises(ValueError):
                await flaky()

        assert cb.failure_count == 2

        result = await flaky()
        assert result == "ok"
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_recovery_timeout(
        self, cb: CircuitBreaker
    ) -> None:
        """After recovery_timeout elapses, OPEN transitions to HALF_OPEN."""

        @cb
        async def failing() -> str:
            raise ValueError("boom")

        for _ in range(3):
            with pytest.raises(ValueError):
                await failing()

        assert cb.state == CircuitBreakerState.OPEN

        # Simulate time passing beyond recovery_timeout
        cb._last_failure_time = datetime.now() - timedelta(seconds=cb.recovery_timeout + 1)

        @cb
        async def succeeding() -> str:
            return "recovered"

        result = await succeeding()
        assert result == "recovered"
        assert cb.state == CircuitBreakerState.CLOSED  # type: ignore[comparison-overlap]

    @pytest.mark.asyncio
    async def test_half_open_to_closed_on_success(self, cb: CircuitBreaker) -> None:
        """HALF_OPEN transitions to CLOSED on a successful call."""
        cb._state = CircuitBreakerState.HALF_OPEN
        cb._half_open_calls = 0

        @cb
        async def succeeding() -> str:
            return "ok"

        await succeeding()
        assert cb.state == CircuitBreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_to_open_on_failure(self, cb: CircuitBreaker) -> None:
        """HALF_OPEN transitions back to OPEN on a failure."""
        cb._state = CircuitBreakerState.HALF_OPEN
        cb._half_open_calls = 0

        @cb
        async def failing() -> str:
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await failing()

        assert cb.state == CircuitBreakerState.OPEN

    @pytest.mark.asyncio
    async def test_half_open_call_limit_enforced(self, cb: CircuitBreaker) -> None:
        """HALF_OPEN rejects calls beyond half_open_max_calls."""
        cb._state = CircuitBreakerState.HALF_OPEN
        cb._half_open_calls = cb.half_open_max_calls

        @cb
        async def succeeding() -> str:
            return "ok"

        with pytest.raises(CircuitBreakerOpenError):
            await succeeding()

    @pytest.mark.asyncio
    async def test_exception_filtering_only_expected_triggers_circuit(
        self, cb: CircuitBreaker
    ) -> None:
        """Only expected_exception (ValueError) triggers the circuit; others pass through."""

        @cb
        async def raise_type_error() -> str:
            raise TypeError("not a value error")

        for _ in range(5):
            with pytest.raises(TypeError):
                await raise_type_error()

        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_reset_returns_to_closed_from_open(self, cb: CircuitBreaker) -> None:
        """reset() transitions from OPEN back to CLOSED."""

        @cb
        async def failing() -> str:
            raise ValueError("boom")

        for _ in range(3):
            with pytest.raises(ValueError):
                await failing()

        assert cb.state.value == CircuitBreakerState.OPEN.value

        await cb.reset()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_reset_returns_to_closed_from_half_open(self, cb: CircuitBreaker) -> None:
        """reset() transitions from HALF_OPEN back to CLOSED."""
        cb._state = CircuitBreakerState.HALF_OPEN

        await cb.reset()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_reset_clears_last_failure_time(self, cb: CircuitBreaker) -> None:
        """reset() clears _last_failure_time so stale times don't cause premature transitions."""

        @cb
        async def failing() -> str:
            raise ValueError("boom")

        for _ in range(3):
            with pytest.raises(ValueError):
                await failing()

        assert cb.state == CircuitBreakerState.OPEN
        assert cb._last_failure_time is not None

        await cb.reset()
        assert cb._last_failure_time is None

    @pytest.mark.asyncio
    async def test_decorator_preserves_return_value(self, cb: CircuitBreaker) -> None:
        """Decorator returns the wrapped function's result unchanged."""

        @cb
        async def get_value() -> str:
            return "hello"

        result = await get_value()
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_decorator_preserves_args_and_kwargs(self, cb: CircuitBreaker) -> None:
        """Decorator passes through positional and keyword arguments."""

        @cb
        async def add(a: int, b: int, extra: int = 0) -> int:
            return a + b + extra

        result = await add(2, 3, extra=10)
        assert result == 15

    @pytest.mark.asyncio
    async def test_open_error_includes_failure_count_and_threshold(
        self, cb: CircuitBreaker
    ) -> None:
        """CircuitBreakerOpenError contains failure_count and threshold."""

        @cb
        async def failing() -> str:
            raise ValueError("boom")

        for _ in range(3):
            with pytest.raises(ValueError):
                await failing()

        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            await failing()

        assert exc_info.value.failure_count == 3
        assert exc_info.value.threshold == 3


@pytest.mark.unit
class TestRetryWithBackoff:
    """Tests for retry_with_backoff and with_retry decorator."""

    @pytest.mark.asyncio
    async def test_succeeds_first_attempt(self) -> None:
        """No retry needed when function succeeds immediately."""
        func = AsyncMock(return_value="ok")

        with patch("polymarket_arbitrage.api.resilience.asyncio.sleep", new_callable=AsyncMock):
            result = await retry_with_backoff(func, max_attempts=3, jitter=False)

        assert result == "ok"
        assert func.await_count == 1

    @pytest.mark.asyncio
    async def test_succeeds_second_attempt(self) -> None:
        """Retries once and succeeds on the second attempt."""
        func = AsyncMock(side_effect=[ValueError("fail"), "ok"])

        with patch("polymarket_arbitrage.api.resilience.asyncio.sleep", new_callable=AsyncMock):
            result = await retry_with_backoff(
                func, max_attempts=3, jitter=False, exceptions=(ValueError,)
            )

        assert result == "ok"
        assert func.await_count == 2

    @pytest.mark.asyncio
    async def test_succeeds_on_last_attempt(self) -> None:
        """Succeeds on the final attempt after all prior attempts fail."""
        func = AsyncMock(side_effect=[ValueError("1"), ValueError("2"), "ok"])

        with patch("polymarket_arbitrage.api.resilience.asyncio.sleep", new_callable=AsyncMock):
            result = await retry_with_backoff(
                func, max_attempts=3, jitter=False, exceptions=(ValueError,)
            )

        assert result == "ok"
        assert func.await_count == 3

    @pytest.mark.asyncio
    async def test_raises_last_exception_after_max_attempts(self) -> None:
        """Raises the last exception when all attempts are exhausted."""
        func = AsyncMock(
            side_effect=[ValueError("first"), ValueError("second"), ValueError("third")]
        )

        with patch("polymarket_arbitrage.api.resilience.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="third"):
                await retry_with_backoff(
                    func, max_attempts=3, jitter=False, exceptions=(ValueError,)
                )

        assert func.await_count == 3

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(self) -> None:
        """Delay follows base_delay * (exponential_base ^ attempt)."""
        func = AsyncMock(side_effect=[ValueError("0"), ValueError("1"), ValueError("2"), "ok"])

        with patch(
            "polymarket_arbitrage.api.resilience.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            await retry_with_backoff(
                func,
                max_attempts=4,
                base_delay=1.0,
                exponential_base=2.0,
                jitter=False,
                exceptions=(ValueError,),
            )

        # attempt 0: 1.0 * 2^0 = 1.0
        # attempt 1: 1.0 * 2^1 = 2.0
        # attempt 2: 1.0 * 2^2 = 4.0
        delays = [call.args[0] for call in mock_sleep.await_args_list]
        assert delays == [1.0, 2.0, 4.0]

    @pytest.mark.asyncio
    async def test_max_delay_caps_backoff(self) -> None:
        """Delay is capped at max_delay even when exponential growth exceeds it."""
        func = AsyncMock(side_effect=[ValueError("0"), ValueError("1"), ValueError("2"), "ok"])

        with patch(
            "polymarket_arbitrage.api.resilience.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            await retry_with_backoff(
                func,
                max_attempts=4,
                base_delay=5.0,
                max_delay=10.0,
                exponential_base=2.0,
                jitter=False,
                exceptions=(ValueError,),
            )

        # attempt 0: min(5.0 * 2^0, 10.0) = 5.0
        # attempt 1: min(5.0 * 2^1, 10.0) = 10.0
        # attempt 2: min(5.0 * 2^2, 10.0) = 10.0 (capped)
        delays = [call.args[0] for call in mock_sleep.await_args_list]
        assert delays == [5.0, 10.0, 10.0]

    @pytest.mark.asyncio
    async def test_jitter_applies_random_multiplier(self) -> None:
        """With jitter=True, delay is multiplied by random.uniform(0.5, 1.5)."""
        func = AsyncMock(side_effect=[ValueError("0"), "ok"])

        with (
            patch(
                "polymarket_arbitrage.api.resilience.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep,
            patch("polymarket_arbitrage.api.resilience.random.uniform", return_value=1.25),
        ):
            await retry_with_backoff(
                func,
                max_attempts=2,
                base_delay=2.0,
                jitter=True,
                exceptions=(ValueError,),
            )

        # delay = 2.0 * 2^0 * 1.25 = 2.5
        mock_sleep.assert_awaited_once_with(2.5)

    @pytest.mark.asyncio
    async def test_jitter_disabled_deterministic(self) -> None:
        """With jitter=False, delays are deterministic across runs."""
        func = AsyncMock(side_effect=[ValueError("0"), ValueError("1"), "ok"])

        with patch(
            "polymarket_arbitrage.api.resilience.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            await retry_with_backoff(
                func,
                max_attempts=3,
                base_delay=1.0,
                jitter=False,
                exceptions=(ValueError,),
            )
            delays_run1 = [call.args[0] for call in mock_sleep.await_args_list]

        func.reset_mock()
        func.side_effect = [ValueError("0"), ValueError("1"), "ok"]

        with patch(
            "polymarket_arbitrage.api.resilience.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            await retry_with_backoff(
                func,
                max_attempts=3,
                base_delay=1.0,
                jitter=False,
                exceptions=(ValueError,),
            )
            delays_run2 = [call.args[0] for call in mock_sleep.await_args_list]

        assert delays_run1 == delays_run2

    @pytest.mark.asyncio
    async def test_non_matching_exception_propagates_immediately(self) -> None:
        """Exceptions not in the exceptions tuple propagate without retry."""
        func = AsyncMock(side_effect=TypeError("not retryable"))

        with patch(
            "polymarket_arbitrage.api.resilience.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            with pytest.raises(TypeError, match="not retryable"):
                await retry_with_backoff(
                    func, max_attempts=3, jitter=False, exceptions=(ValueError,)
                )

        assert func.await_count == 1
        mock_sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_with_retry_passes_args_and_kwargs(self) -> None:
        """with_retry decorator forwards positional and keyword arguments."""

        @with_retry(max_attempts=1, jitter=False)
        async def add(a: int, b: int, offset: int = 0) -> int:
            return a + b + offset

        result = await add(2, 3, offset=10)
        assert result == 15

    @pytest.mark.asyncio
    async def test_retry_with_max_attempts_one(self) -> None:
        """With max_attempts=1, a failing function raises immediately without sleeping."""
        func = AsyncMock(side_effect=ValueError("instant fail"))

        with patch(
            "polymarket_arbitrage.api.resilience.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            with pytest.raises(ValueError, match="instant fail"):
                await retry_with_backoff(
                    func, max_attempts=1, jitter=False, exceptions=(ValueError,)
                )

        assert func.await_count == 1
        mock_sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_with_retry_retries_on_failure(self) -> None:
        """with_retry decorator retries on failure and returns on eventual success."""
        call_count = 0

        @with_retry(max_attempts=3, base_delay=0.1, jitter=False, exceptions=(ValueError,))
        async def flaky_func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "success"

        with patch("polymarket_arbitrage.api.resilience.asyncio.sleep", new_callable=AsyncMock):
            result = await flaky_func()

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_with_retry_preserves_return_value(self) -> None:
        """with_retry decorator returns the wrapped function's return value."""
        expected = {"key": "value", "count": 42}

        @with_retry(max_attempts=2, jitter=False, exceptions=(ValueError,))
        async def get_data() -> dict:
            return expected

        result = await get_data()
        assert result == expected


@pytest.mark.unit
class TestRateLimiter:
    """Tests for RateLimiter token bucket implementation."""

    @pytest.fixture
    def limiter(self) -> RateLimiter:
        """Create a rate limiter with 10 tokens/sec and burst of 5."""
        return RateLimiter(rate=10.0, burst=5)

    @pytest.mark.asyncio
    async def test_acquire_immediate_when_tokens_available(self, limiter: RateLimiter) -> None:
        """Tokens available in full bucket -- acquire does not sleep."""
        with patch("polymarket_arbitrage.api.resilience.asyncio.sleep") as mock_sleep:
            await limiter.acquire()
            mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_acquire_burst_capacity(self, limiter: RateLimiter) -> None:
        """Can acquire up to burst tokens immediately without waiting."""
        with patch("polymarket_arbitrage.api.resilience.asyncio.sleep") as mock_sleep:
            for _ in range(5):
                await limiter.acquire()
            mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_acquire_waits_when_tokens_depleted(self) -> None:
        """When bucket is empty, acquire sleeps for tokens_needed / rate."""
        limiter = RateLimiter(rate=10.0, burst=5)
        t0 = datetime(2025, 1, 1, 12, 0, 0)

        with patch("polymarket_arbitrage.api.resilience.datetime") as mock_dt:
            mock_dt.now.return_value = t0
            limiter._last_update = t0
            limiter._tokens = 0.0

            with patch("polymarket_arbitrage.api.resilience.asyncio.sleep") as mock_sleep:
                await limiter.acquire()
                mock_sleep.assert_called_once()
                wait_time = mock_sleep.call_args[0][0]
                # 1 token needed / 10.0 rate = 0.1 seconds
                assert abs(wait_time - 0.1) < 1e-9

    @pytest.mark.asyncio
    async def test_token_refill_over_elapsed_time(self) -> None:
        """Tokens refill based on elapsed time at the configured rate."""
        limiter = RateLimiter(rate=10.0, burst=5)
        t0 = datetime(2025, 1, 1, 12, 0, 0)

        with patch("polymarket_arbitrage.api.resilience.datetime") as mock_dt:
            limiter._last_update = t0
            limiter._tokens = 0.0

            # Advance 0.3 seconds -- refill 3.0 tokens (10 * 0.3)
            t1 = datetime(2025, 1, 1, 12, 0, 0, 300000)
            mock_dt.now.return_value = t1

            with patch("polymarket_arbitrage.api.resilience.asyncio.sleep"):
                await limiter.acquire()
                # Had 0, refilled 3.0, consumed 1 -> 2.0 remaining
                assert abs(limiter._tokens - 2.0) < 1e-9

    @pytest.mark.asyncio
    async def test_bucket_never_exceeds_burst_capacity(self) -> None:
        """Token count is capped at burst even after long elapsed time."""
        limiter = RateLimiter(rate=10.0, burst=5)
        t0 = datetime(2025, 1, 1, 12, 0, 0)

        with patch("polymarket_arbitrage.api.resilience.datetime") as mock_dt:
            limiter._last_update = t0
            limiter._tokens = 3.0

            # Advance 10 seconds -- would refill 100 but capped at burst (5)
            t1 = datetime(2025, 1, 1, 12, 0, 10)
            mock_dt.now.return_value = t1

            with patch("polymarket_arbitrage.api.resilience.asyncio.sleep"):
                await limiter.acquire()
                # Capped at 5, consumed 1 -> 4.0 remaining
                assert abs(limiter._tokens - 4.0) < 1e-9

    @pytest.mark.asyncio
    async def test_reset_refills_bucket(self, limiter: RateLimiter) -> None:
        """reset() restores tokens to full burst capacity."""
        for _ in range(5):
            await limiter.acquire()

        await limiter.reset()
        assert limiter._tokens == float(limiter.burst)

    @pytest.mark.asyncio
    async def test_decorator_preserves_return_value_and_args(self) -> None:
        """Decorator passes through arguments and return value unchanged."""
        limiter = RateLimiter(rate=10.0, burst=5)

        @limiter
        async def add(a: int, b: int, extra: int = 0) -> int:
            return a + b + extra

        result = await add(3, 4, extra=10)
        assert result == 17

    @pytest.mark.asyncio
    async def test_wait_time_calculation(self) -> None:
        """Wait time should be tokens_needed / rate."""
        limiter = RateLimiter(rate=5.0, burst=2)
        t0 = datetime(2025, 1, 1, 12, 0, 0)

        with patch("polymarket_arbitrage.api.resilience.datetime") as mock_dt:
            mock_dt.now.return_value = t0
            limiter._last_update = t0
            limiter._tokens = 0.0

            with patch("polymarket_arbitrage.api.resilience.asyncio.sleep") as mock_sleep:
                await limiter.acquire(tokens=3)
                mock_sleep.assert_called_once()
                wait_time = mock_sleep.call_args[0][0]
                # 3 tokens needed / 5.0 rate = 0.6 seconds
                assert abs(wait_time - 0.6) < 1e-9

    @pytest.mark.asyncio
    async def test_tokens_set_to_zero_after_waiting(self) -> None:
        """After waiting for token refill, tokens should be set to 0."""
        limiter = RateLimiter(rate=10.0, burst=5)
        t0 = datetime(2025, 1, 1, 12, 0, 0)

        with patch("polymarket_arbitrage.api.resilience.datetime") as mock_dt:
            mock_dt.now.return_value = t0
            limiter._last_update = t0
            limiter._tokens = 0.0

            with patch("polymarket_arbitrage.api.resilience.asyncio.sleep"):
                await limiter.acquire()
                assert limiter._tokens == 0.0
