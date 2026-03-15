"""Tests for PolymarketClient HTTP client."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from polymarket_arbitrage.api.client import PolymarketClient
from polymarket_arbitrage.api.response_models import MarketResponse
from polymarket_arbitrage.domain.exceptions import (
    APIError,
    MarketNotFoundError,
    RateLimitError,
)
from polymarket_arbitrage.domain.exceptions import (
    ConnectionError as DomainConnectionError,
)
from polymarket_arbitrage.domain.exceptions import (
    TimeoutError as DomainTimeoutError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(
    status_code: int = 200,
    json_data: Any = None,
    headers: dict[str, str] | None = None,
    text: str = "",
) -> httpx.Response:
    """Build a minimal httpx.Response for testing."""
    resp_headers = dict(headers or {})
    if json_data is not None:
        content = json.dumps(json_data).encode()
        resp_headers.setdefault("content-type", "application/json")
    else:
        content = text.encode()
    return httpx.Response(
        status_code=status_code,
        headers=resp_headers,
        content=content,
        request=httpx.Request("GET", "https://gamma-api.polymarket.com/test"),
    )


def _mock_async_client() -> AsyncMock:
    """Return an AsyncMock standing in for httpx.AsyncClient."""
    mock = AsyncMock(spec=httpx.AsyncClient)
    mock.aclose = AsyncMock()
    return mock


# ---------------------------------------------------------------------------
# TestPolymarketClientInit
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPolymarketClientInit:
    """Tests for PolymarketClient construction and defaults."""

    def test_default_base_url(self) -> None:
        """Default base_url points to Gamma API."""
        client = PolymarketClient()
        assert client.base_url == "https://gamma-api.polymarket.com"

    def test_default_timeout(self) -> None:
        """Default timeout has 5s connect, 30s read."""
        client = PolymarketClient()
        assert client.timeout.connect == 5.0
        assert client.timeout.read == 30.0

    def test_default_limits(self) -> None:
        """Default connection pool limits are set."""
        client = PolymarketClient()
        assert client.limits.max_connections == 100
        assert client.limits.max_keepalive_connections == 20

    def test_custom_base_url(self) -> None:
        """Custom base_url is stored with trailing slash stripped."""
        client = PolymarketClient(base_url="https://example.com/api/")
        assert client.base_url == "https://example.com/api"

    def test_custom_timeout(self) -> None:
        """Custom timeout is passed through."""
        timeout = httpx.Timeout(connect=1.0, read=2.0, write=3.0, pool=4.0)
        client = PolymarketClient(timeout=timeout)
        assert client.timeout is timeout

    def test_custom_limits(self) -> None:
        """Custom limits are passed through."""
        limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
        client = PolymarketClient(limits=limits)
        assert client.limits is limits

    def test_client_not_initialized(self) -> None:
        """Internal _client is None before entering context manager."""
        client = PolymarketClient()
        assert client._client is None


# ---------------------------------------------------------------------------
# TestPolymarketClientContextManager
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPolymarketClientContextManager:
    """Tests for async context manager lifecycle."""

    @pytest.mark.asyncio
    async def test_aenter_creates_client_and_returns_self(self) -> None:
        """__aenter__ creates httpx client and returns the wrapper."""
        poly_client = PolymarketClient()
        result = await poly_client.__aenter__()
        try:
            assert result is poly_client
            assert poly_client._client is not None
            assert isinstance(poly_client._client, httpx.AsyncClient)
        finally:
            await poly_client.__aexit__(None, None, None)

    @pytest.mark.asyncio
    async def test_aexit_closes_client(self) -> None:
        """__aexit__ closes the underlying httpx client."""
        poly_client = PolymarketClient()
        poly_client._client = _mock_async_client()
        await poly_client.__aexit__(None, None, None)
        poly_client._client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_aexit_noop_when_no_client(self) -> None:
        """__aexit__ is a no-op when _client is None."""
        poly_client = PolymarketClient()
        # Should not raise
        await poly_client.__aexit__(None, None, None)

    def test_client_property_raises_when_not_initialized(self) -> None:
        """Accessing .client before __aenter__ raises RuntimeError."""
        poly_client = PolymarketClient()
        with pytest.raises(RuntimeError, match="Client not initialized"):
            _ = poly_client.client

    @pytest.mark.asyncio
    async def test_client_property_returns_httpx_client(self) -> None:
        """Accessing .client after __aenter__ returns the httpx AsyncClient."""
        poly_client = PolymarketClient()
        mock = _mock_async_client()
        poly_client._client = mock
        assert poly_client.client is mock


# ---------------------------------------------------------------------------
# TestPolymarketClientRequest
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPolymarketClientRequest:
    """Tests for the _request method and its error handling."""

    @pytest.fixture
    def poly_client(self) -> PolymarketClient:
        """PolymarketClient with a mocked httpx.AsyncClient."""
        client = PolymarketClient()
        client._client = _mock_async_client()
        return client

    @pytest.mark.asyncio
    async def test_successful_get_returns_dict(self, poly_client: PolymarketClient) -> None:
        """Successful GET returns parsed JSON dict."""
        expected = {"id": "0x123", "question": "Test?"}
        poly_client._client.request = AsyncMock(  # type: ignore[union-attr, method-assign]
            return_value=_make_response(200, json_data=expected),
        )
        result = await poly_client._request("GET", "/markets/0x123")
        assert result == expected

    @pytest.mark.asyncio
    async def test_successful_get_returns_list(self, poly_client: PolymarketClient) -> None:
        """Successful GET returns parsed JSON list."""
        expected = [{"id": "1"}, {"id": "2"}]
        poly_client._client.request = AsyncMock(  # type: ignore[union-attr, method-assign]
            return_value=_make_response(200, json_data=expected),
        )
        result = await poly_client._request("GET", "/markets")
        assert result == expected

    @pytest.mark.asyncio
    async def test_timeout_raises_domain_timeout_error(self, poly_client: PolymarketClient) -> None:
        """httpx.TimeoutException is translated to domain TimeoutError with chaining."""
        original = httpx.TimeoutException("timed out")
        poly_client._client.request = AsyncMock(side_effect=original)  # type: ignore[union-attr, method-assign]

        with pytest.raises(DomainTimeoutError, match="Request timeout") as exc_info:
            await poly_client._request("GET", "/markets")

        assert exc_info.value.__cause__ is original
        assert exc_info.value.endpoint == "/markets"

    @pytest.mark.asyncio
    async def test_connect_error_raises_domain_connection_error(
        self, poly_client: PolymarketClient
    ) -> None:
        """httpx.ConnectError is translated to domain ConnectionError with chaining."""
        original = httpx.ConnectError("connection refused")
        poly_client._client.request = AsyncMock(side_effect=original)  # type: ignore[union-attr, method-assign]

        with pytest.raises(DomainConnectionError, match="Connection failed") as exc_info:
            await poly_client._request("GET", "/markets")

        assert exc_info.value.__cause__ is original
        assert exc_info.value.endpoint == "/markets"

    @pytest.mark.asyncio
    async def test_http_429_raises_rate_limit_error(self, poly_client: PolymarketClient) -> None:
        """HTTP 429 is translated to RateLimitError with retry_after from header."""
        response = _make_response(429, headers={"Retry-After": "30"}, text="rate limited")
        poly_client._client.request = AsyncMock(  # type: ignore[union-attr, method-assign]
            return_value=response,
        )

        with pytest.raises(RateLimitError, match="Rate limit exceeded") as exc_info:
            await poly_client._request("GET", "/markets")

        assert exc_info.value.retry_after == 30
        assert exc_info.value.status_code == 429
        assert exc_info.value.endpoint == "/markets"
        assert isinstance(exc_info.value.__cause__, httpx.HTTPStatusError)

    @pytest.mark.asyncio
    async def test_http_429_without_retry_after_header(self, poly_client: PolymarketClient) -> None:
        """HTTP 429 without Retry-After header sets retry_after to None."""
        response = _make_response(429, text="rate limited")
        poly_client._client.request = AsyncMock(  # type: ignore[union-attr, method-assign]
            return_value=response,
        )

        with pytest.raises(RateLimitError) as exc_info:
            await poly_client._request("GET", "/markets")

        assert exc_info.value.retry_after is None

    @pytest.mark.asyncio
    async def test_http_404_raises_market_not_found_error(
        self, poly_client: PolymarketClient
    ) -> None:
        """HTTP 404 on /markets/<id> raises MarketNotFoundError with market_id."""
        response = _make_response(404, text="not found")
        poly_client._client.request = AsyncMock(  # type: ignore[union-attr, method-assign]
            return_value=response,
        )

        with pytest.raises(MarketNotFoundError, match="0xabc123") as exc_info:
            await poly_client._request("GET", "/markets/0xabc123")

        assert exc_info.value.market_id == "0xabc123"
        assert isinstance(exc_info.value.__cause__, httpx.HTTPStatusError)

    @pytest.mark.asyncio
    async def test_http_404_non_market_path(self, poly_client: PolymarketClient) -> None:
        """HTTP 404 on non-market path sets market_id to 'unknown'."""
        response = _make_response(404, text="not found")
        poly_client._client.request = AsyncMock(  # type: ignore[union-attr, method-assign]
            return_value=response,
        )

        with pytest.raises(MarketNotFoundError, match="unknown"):
            await poly_client._request("GET", "/other/endpoint")

    @pytest.mark.asyncio
    async def test_http_500_raises_api_error(self, poly_client: PolymarketClient) -> None:
        """HTTP 500 raises APIError with status_code and endpoint."""
        response = _make_response(500, text="internal server error")
        poly_client._client.request = AsyncMock(  # type: ignore[union-attr, method-assign]
            return_value=response,
        )

        with pytest.raises(APIError, match="500") as exc_info:
            await poly_client._request("GET", "/markets")

        assert exc_info.value.status_code == 500
        assert exc_info.value.endpoint == "/markets"

    @pytest.mark.asyncio
    async def test_http_500_with_json_error_body(self, poly_client: PolymarketClient) -> None:
        """HTTP 500 with structured JSON error extracts message via ErrorResponse."""
        error_body = {"error": "Internal failure", "code": "INTERNAL"}
        response = _make_response(500, json_data=error_body)
        poly_client._client.request = AsyncMock(  # type: ignore[union-attr, method-assign]
            return_value=response,
        )

        with pytest.raises(APIError, match="Internal failure") as exc_info:
            await poly_client._request("GET", "/markets")

        assert exc_info.value.response_data == error_body

    @pytest.mark.asyncio
    async def test_absolute_url_path_bypasses_base_url(self, poly_client: PolymarketClient) -> None:
        """Passing a full URL as path uses it directly instead of joining with base_url."""
        expected = {"id": "0x123"}
        poly_client._client.request = AsyncMock(  # type: ignore[union-attr, method-assign]
            return_value=_make_response(200, json_data=expected),
        )
        result = await poly_client._request("GET", "https://other-api.com/markets/0x123")
        assert result == expected
        call_args = poly_client._client.request.call_args  # type: ignore[union-attr]
        assert call_args[1]["url"] == "https://other-api.com/markets/0x123"

    @pytest.mark.asyncio
    async def test_exception_chaining_on_http_status_error(
        self, poly_client: PolymarketClient
    ) -> None:
        """HTTP status errors preserve exception chain."""
        response = _make_response(503, text="service unavailable")
        poly_client._client.request = AsyncMock(  # type: ignore[union-attr, method-assign]
            return_value=response,
        )

        with pytest.raises(APIError) as exc_info:
            await poly_client._request("GET", "/markets")

        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, httpx.HTTPStatusError)


# ---------------------------------------------------------------------------
# TestPolymarketClientGetMarket
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPolymarketClientGetMarket:
    """Tests for the get_market method."""

    @pytest.fixture
    def poly_client(self) -> PolymarketClient:
        """PolymarketClient with a mocked httpx.AsyncClient."""
        client = PolymarketClient()
        client._client = _mock_async_client()
        return client

    @pytest.mark.asyncio
    async def test_valid_response_returns_market_response(
        self,
        poly_client: PolymarketClient,
        mock_api_market_response: dict[str, Any],
    ) -> None:
        """Valid API dict is parsed into MarketResponse."""
        poly_client._client.request = AsyncMock(  # type: ignore[union-attr, method-assign]
            return_value=_make_response(200, json_data=mock_api_market_response),
        )
        result = await poly_client.get_market("0xmarket123")
        assert isinstance(result, MarketResponse)
        assert result.market_id == "0xmarket123"
        assert result.question == "Will Bitcoin reach $100k in 2025?"
        assert len(result.tokens) == 2

    @pytest.mark.asyncio
    async def test_non_dict_response_raises_value_error(
        self, poly_client: PolymarketClient
    ) -> None:
        """Non-dict response (e.g. list) raises ValueError."""
        poly_client._client.request = AsyncMock(  # type: ignore[union-attr, method-assign]
            return_value=_make_response(200, json_data=[{"id": "0x1"}]),
        )

        with pytest.raises(ValueError, match="Expected dict response"):
            await poly_client.get_market("0x1")

    @pytest.mark.asyncio
    async def test_invalid_data_raises_value_error(self, poly_client: PolymarketClient) -> None:
        """Dict missing required fields raises ValueError (Pydantic validation)."""
        poly_client._client.request = AsyncMock(  # type: ignore[union-attr, method-assign]
            return_value=_make_response(200, json_data={"id": "0x1"}),
        )

        with pytest.raises(ValueError):
            await poly_client.get_market("0x1")


# ---------------------------------------------------------------------------
# TestPolymarketClientHealthCheck
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPolymarketClientHealthCheck:
    """Tests for the health_check method."""

    @pytest.fixture
    def poly_client(self) -> PolymarketClient:
        """PolymarketClient with a mocked httpx.AsyncClient."""
        client = PolymarketClient()
        client._client = _mock_async_client()
        return client

    @pytest.mark.asyncio
    async def test_successful_request_returns_true(self, poly_client: PolymarketClient) -> None:
        """Health check returns True when API responds successfully."""
        poly_client._client.request = AsyncMock(  # type: ignore[union-attr, method-assign]
            return_value=_make_response(200, json_data=[]),
        )
        result = await poly_client.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_timeout_returns_false(self, poly_client: PolymarketClient) -> None:
        """Health check returns False on timeout, never raises."""
        poly_client._client.request = AsyncMock(  # type: ignore[union-attr, method-assign]
            side_effect=httpx.TimeoutException("timed out"),
        )
        result = await poly_client.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_connection_error_returns_false(self, poly_client: PolymarketClient) -> None:
        """Health check returns False on connection error, never raises."""
        poly_client._client.request = AsyncMock(  # type: ignore[union-attr, method-assign]
            side_effect=httpx.ConnectError("refused"),
        )
        result = await poly_client.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_http_error_returns_false(self, poly_client: PolymarketClient) -> None:
        """Health check returns False on HTTP error, never raises."""
        poly_client._client.request = AsyncMock(  # type: ignore[union-attr, method-assign]
            return_value=_make_response(500, text="down"),
        )
        result = await poly_client.health_check()
        assert result is False
