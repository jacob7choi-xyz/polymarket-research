"""
Production-grade async HTTP client for Polymarket API.

Why httpx over requests/aiohttp?
- httpx: Modern async/await, HTTP/2 support, excellent ergonomics
- requests: Synchronous only, no connection pooling for async
- aiohttp: Good but httpx has better API and type hints

Interview Points:
- Connection pooling: Reuse TCP connections (saves ~50ms per request)
- HTTP/2: Multiplexing multiple requests over single connection
- Timeout strategy: Aggressive connect (5s), generous read (30s)
- Context manager: Ensures proper cleanup of connections
"""

from types import TracebackType
from typing import Any
from urllib.parse import urljoin

import httpx

from ..domain.exceptions import (
    APIError,
    ConnectionError,
    MarketNotFoundError,
    RateLimitError,
    TimeoutError,
)
from ..monitoring.logging import get_logger
from .response_models import ErrorResponse, MarketResponse

logger = get_logger(__name__)


class PolymarketClient:
    """
    Async HTTP client for Polymarket Gamma API.

    Features:
    - Connection pooling: Reuse TCP connections
    - HTTP/2 support: Multiplex requests
    - Configurable timeouts: Separate connect and read timeouts
    - Context manager: Proper resource cleanup
    - Error handling: Translate HTTP errors to domain exceptions

    Usage:
        async with PolymarketClient(base_url="https://gamma-api.polymarket.com") as client:
            market = await client.get_market("0x123abc")

    Interview Point - Why Async?
    - I/O bound: Waiting for network responses
    - Concurrency: Handle multiple requests simultaneously
    - Resource efficiency: Single thread can handle 1000s of concurrent requests
    - Better than threading: No GIL issues, lower memory overhead
    """

    def __init__(
        self,
        base_url: str = "https://gamma-api.polymarket.com",
        timeout: httpx.Timeout | None = None,
        limits: httpx.Limits | None = None,
    ):
        """
        Initialize Polymarket API client.

        Args:
            base_url: API base URL
            timeout: Request timeouts (connect, read, write, pool)
            limits: Connection pool limits

        Interview Point - Timeout Strategy:
        - Connect timeout (5s): Fast failure on network issues
        - Read timeout (30s): Allow large responses (market lists)
        - Why different? Connect fails fast, read allows API processing time
        """
        self.base_url = base_url.rstrip("/")

        # Default timeout: 5s connect, 30s read
        # Why? Connect failures should fail fast, reads need time for API processing
        self.timeout = timeout or httpx.Timeout(
            connect=5.0,  # TCP connection establishment
            read=30.0,  # Reading response
            write=5.0,  # Sending request
            pool=5.0,  # Getting connection from pool
        )

        # Default connection limits
        # Why these numbers?
        # - max_connections=100: Total concurrent connections
        # - max_keepalive=20: Reuse 20 connections (most markets fetch in parallel)
        # Interview Point: Tuning connection pools
        # - Too low: Requests queue up, high latency
        # - Too high: Resource exhaustion, connection thrashing
        self.limits = limits or httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20,
            keepalive_expiry=30.0,  # Keep connections alive for 30s
        )

        # Create client (done in __aenter__ for async context manager)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "PolymarketClient":
        """
        Async context manager entry.

        Creates httpx.AsyncClient with connection pooling.

        Why context manager?
        - Ensures proper cleanup (closes connections)
        - Python best practice for resource management
        - Prevents connection leaks
        """
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            limits=self.limits,
            http2=True,  # Enable HTTP/2 for multiplexing
            follow_redirects=True,
        )
        logger.info(
            "api_client_initialized",
            base_url=self.base_url,
            timeout=str(self.timeout),
            http2=True,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """
        Async context manager exit.

        Closes all connections and cleans up resources.
        """
        if self._client:
            await self._client.aclose()
            logger.info("api_client_closed")

    @property
    def client(self) -> httpx.AsyncClient:
        """
        Get httpx client, ensuring it's initialized.

        Raises:
            RuntimeError: If client not initialized (use context manager)

        Interview Point: Fail fast on misuse
        """
        if self._client is None:
            raise RuntimeError(
                "Client not initialized. Use 'async with PolymarketClient() as client:'"
            )
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any] | list[Any]:
        """
        Low-level HTTP request with error handling.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path (e.g., "/markets/0x123")
            params: Query parameters
            **kwargs: Additional httpx request kwargs

        Returns:
            Parsed JSON response

        Raises:
            APIError: HTTP errors (4xx, 5xx)
            TimeoutError: Request timeout
            ConnectionError: Network connectivity issues
            RateLimitError: Rate limit exceeded (429)

        Interview Point - Error Handling Strategy:
        1. Catch httpx exceptions
        2. Translate to domain exceptions
        3. Include context (endpoint, status code)
        4. Log errors for monitoring
        """
        url = path if path.startswith("http") else urljoin(self.base_url, path)

        try:
            logger.debug("api_request", method=method, url=url, params=params)

            response = await self.client.request(
                method=method,
                url=url,
                params=params,
                **kwargs,
            )

            # Raise for 4xx/5xx status codes
            response.raise_for_status()

            # Parse JSON response
            data = response.json()

            logger.debug(
                "api_response_success",
                method=method,
                url=url,
                status_code=response.status_code,
                response_size=len(response.content),
            )

            return dict(data) if isinstance(data, dict) else list(data)

        except httpx.TimeoutException as e:
            logger.warning("api_request_timeout", method=method, url=url, error=str(e))
            raise TimeoutError(
                f"Request timeout: {method} {url}",
                endpoint=path,
            ) from e

        except httpx.ConnectError as e:
            logger.error("api_connection_failed", method=method, url=url, error=str(e))
            raise ConnectionError(
                f"Connection failed: {method} {url}",
                endpoint=path,
            ) from e

        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code

            # Rate limiting (429 Too Many Requests)
            if status_code == 429:
                retry_after = e.response.headers.get("Retry-After")
                logger.warning(
                    "api_rate_limited",
                    method=method,
                    url=url,
                    retry_after=retry_after,
                )
                raise RateLimitError(
                    f"Rate limit exceeded: {method} {url}",
                    status_code=status_code,
                    retry_after=int(retry_after) if retry_after else None,
                    endpoint=path,
                ) from e

            # Not Found (404)
            if status_code == 404:
                logger.warning("api_not_found", method=method, url=url)
                # Try to extract market ID from URL for better error message
                market_id = path.split("/")[-1] if "/markets/" in path else "unknown"
                raise MarketNotFoundError(market_id) from e

            # Other HTTP errors
            error_data = None
            try:
                error_data = e.response.json()
                error_response = ErrorResponse(**error_data)
                message = error_response.full_message
            except Exception:
                message = e.response.text or str(e)

            logger.error(
                "api_http_error",
                method=method,
                url=url,
                status_code=status_code,
                error=message,
            )

            raise APIError(
                f"HTTP {status_code}: {message}",
                status_code=status_code,
                endpoint=path,
                response_data=error_data,
            ) from e

    async def get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        """
        Convenience method for GET requests returning JSON.

        Args:
            path: API path
            params: Query parameters

        Returns:
            Parsed JSON response
        """
        return await self._request("GET", path, params=params)

    async def get_market(self, market_id: str) -> MarketResponse:
        """
        Fetch single market by ID.

        Args:
            market_id: Market ID (hex string like "0x123abc")

        Returns:
            Validated MarketResponse

        Raises:
            MarketNotFoundError: Market doesn't exist
            APIError: API request failed
            InvalidMarketDataError: Response validation failed

        Example:
            market = await client.get_market("0x123abc")
            print(f"Question: {market.question}")
            print(f"YES price: {market.tokens[0].price}")
        """
        path = f"/markets/{market_id}"
        data = await self.get_json(path)

        # Validate response with Pydantic
        # Why validate? API might return unexpected format, fail fast
        try:
            if not isinstance(data, dict):
                raise ValueError(f"Expected dict response, got {type(data).__name__}")
            return MarketResponse(**data)
        except ValueError as e:
            logger.error(
                "market_validation_failed",
                market_id=market_id,
                error=str(e),
            )
            raise

    async def health_check(self) -> bool:
        """
        Check if API is reachable.

        Returns:
            True if API is healthy, False otherwise

        Used by:
        - Startup health checks
        - Circuit breaker recovery testing
        - Monitoring readiness probes

        Interview Point: Health check design
        - Lightweight: Don't fetch large data
        - Fast timeout: Fail fast if API is down
        - Non-critical: Don't raise exceptions, return bool
        """
        try:
            # Try to fetch a simple endpoint
            # /markets with limit=1 is lightweight
            await self.get_json("/markets", params={"limit": 1})
            logger.debug("health_check_success")
            return True
        except Exception as e:
            logger.warning("health_check_failed", error=str(e))
            return False


# Example usage for documentation
async def main() -> None:
    """Example usage of PolymarketClient."""
    # Initialize client with context manager
    async with PolymarketClient() as client:
        # Health check
        is_healthy = await client.health_check()
        print(f"API healthy: {is_healthy}")

        # Fetch market
        try:
            market = await client.get_market("example_market_id")
            print(f"Market: {market.question}")
            for token in market.tokens:
                print(f"  {token.outcome}: {token.price}")
        except MarketNotFoundError:
            print("Market not found")
        except APIError as e:
            print(f"API error: {e}")


if __name__ == "__main__":
    import asyncio

    # Run example
    asyncio.run(main())
