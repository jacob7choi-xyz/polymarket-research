"""
Unit tests for the application composition root.

Testing:
- Component wiring in startup()
- Injected API client is preserved (not replaced)
- Fail-fast when the client was never injected
- Market fetching and pagination behaviour

Interview Point - Why Test the Composition Root:
- Wiring bugs do not surface in component-level tests
- Every component can be individually correct while the graph is wrong
"""

from typing import Any

import pytest

from polymarket_arbitrage.api.client import PolymarketClient
from polymarket_arbitrage.api.resilience import CircuitBreaker, RateLimiter
from polymarket_arbitrage.config.constants import MAX_MARKET_PAGES
from polymarket_arbitrage.config.settings import Settings
from polymarket_arbitrage.domain.exceptions import APIError
from polymarket_arbitrage.main import Application


def build_raw_market(market_id: str, yes_price: str = "0.48", no_price: str = "0.48") -> dict:
    """Build a raw Gamma API market payload.

    Mirrors the live shape: outcomes, outcomePrices and clobTokenIds arrive as
    JSON-encoded strings, and endDate carries a 'Z' suffix.
    """
    return {
        "id": market_id,
        "conditionId": f"0xcond{market_id}",
        "question": f"Will market {market_id} resolve YES?",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": f'["{yes_price}", "{no_price}"]',
        "clobTokenIds": f'["0xyes{market_id}", "0xno{market_id}"]',
        "acceptingOrders": True,
        "volume24hr": 50000,
        "liquidity": 10000,
        "endDate": "2099-01-01T00:00:00Z",
        "active": True,
    }


class StubClient:
    """API client stub returning queued pages, then raising."""

    def __init__(self, pages: list[list[dict]], error: Exception | None = None):
        self.pages = pages
        self.error = error
        self.calls = 0

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if self.calls < len(self.pages):
            page = self.pages[self.calls]
            self.calls += 1
            return page
        if self.error is not None:
            raise self.error
        return []


class TestApplicationStartup:
    """Test Application startup wiring."""

    @pytest.fixture
    def settings(self) -> Settings:
        """Settings with defaults."""
        return Settings()

    @pytest.fixture
    def app(self, settings: Settings) -> Application:
        """Application instance with no components built yet."""
        return Application(settings)

    @pytest.mark.asyncio
    async def test_startup_preserves_injected_client(
        self, app: Application, settings: Settings
    ) -> None:
        """Test startup does not replace the client it was given.

        Regression: startup() constructed a fresh PolymarketClient, discarding
        the one entered by the caller's async context manager. The replacement
        had no underlying httpx session, so every request raised RuntimeError
        and the detection cycle silently fetched zero markets.
        """
        async with PolymarketClient(base_url=str(settings.polymarket_api_url)) as client:
            app.api_client = client

            await app.startup()

            assert app.api_client is client

    @pytest.mark.asyncio
    async def test_startup_without_client_raises(self, app: Application) -> None:
        """Test startup fails fast when no client was injected."""
        with pytest.raises(RuntimeError, match="api_client"):
            await app.startup()

    @pytest.mark.asyncio
    async def test_startup_builds_all_components(
        self, app: Application, settings: Settings
    ) -> None:
        """Test startup wires every component in the dependency graph."""
        async with PolymarketClient(base_url=str(settings.polymarket_api_url)) as client:
            app.api_client = client

            await app.startup()

            assert app.position_tracker is not None
            assert app.paper_trader is not None
            assert app.strategy is not None
            # Trader shares the tracker instance rather than building its own
            assert app.paper_trader.position_tracker is app.position_tracker

    @pytest.mark.asyncio
    async def test_startup_adopts_the_clients_resilience(
        self, app: Application, settings: Settings
    ) -> None:
        """Test the app reports the same breaker that actually gates requests.

        Regression: startup() used to construct its own RateLimiter and CircuitBreaker
        while the client applied neither, so the breaker published to metrics could never
        leave CLOSED no matter how the API behaved.
        """
        limiter = RateLimiter(rate=5.0, burst=10)
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)
        async with PolymarketClient(
            base_url=str(settings.polymarket_api_url),
            rate_limiter=limiter,
            circuit_breaker=breaker,
        ) as client:
            app.api_client = client

            await app.startup()

            assert app.rate_limiter is limiter
            assert app.circuit_breaker is breaker

    @pytest.mark.asyncio
    async def test_startup_without_resilience_reports_none(
        self, app: Application, settings: Settings
    ) -> None:
        """Test an unprotected client is reported as unprotected, not faked."""
        async with PolymarketClient(base_url=str(settings.polymarket_api_url)) as client:
            app.api_client = client

            await app.startup()

            assert app.rate_limiter is None
            assert app.circuit_breaker is None

    @pytest.mark.asyncio
    async def test_startup_applies_configured_threshold(
        self, app: Application, settings: Settings
    ) -> None:
        """Test the strategy receives thresholds from settings."""
        async with PolymarketClient(base_url=str(settings.polymarket_api_url)) as client:
            app.api_client = client

            await app.startup()

            assert app.strategy is not None
            assert app.strategy.arbitrage_threshold == settings.arbitrage_threshold
            assert app.strategy.min_liquidity == settings.min_liquidity_usd
            assert app.strategy.min_volume == settings.min_volume_usd


class TestFetchMarkets:
    """Test market fetching and pagination."""

    @pytest.fixture
    def app(self) -> Application:
        """Application instance."""
        return Application(Settings())

    @pytest.mark.asyncio
    async def test_fetch_markets_parses_pages(self, app: Application) -> None:
        """Test a full page followed by a short page is fully parsed."""
        full_page = [build_raw_market(str(i)) for i in range(100)]
        short_page = [build_raw_market("100")]
        app.api_client = StubClient([full_page, short_page])  # type: ignore[assignment]

        markets = await app._fetch_markets()

        assert len(markets) == 101

    @pytest.mark.asyncio
    async def test_fetch_markets_keeps_results_when_pagination_fails(
        self, app: Application
    ) -> None:
        """Test markets already fetched survive a mid-pagination API failure.

        Regression: Gamma caps offset at ~2100 and returns HTTP 422 beyond it.
        The error escaped to a handler that skipped parsing entirely, so a cycle
        that had successfully fetched 2100 markets returned none of them.
        """
        full_page = [build_raw_market(str(i)) for i in range(100)]
        app.api_client = StubClient(  # type: ignore[assignment]
            [full_page],
            error=APIError("offset too large", status_code=422, endpoint="/markets"),
        )

        markets = await app._fetch_markets()

        assert len(markets) == 100

    @pytest.mark.asyncio
    async def test_fetch_markets_stops_at_page_limit(self, app: Application) -> None:
        """Test pagination is bounded so a always-full response cannot loop forever."""
        endless = [[build_raw_market(str(i)) for i in range(100)] for _ in range(500)]
        stub = StubClient(endless)
        app.api_client = stub  # type: ignore[assignment]

        await app._fetch_markets()

        assert stub.calls <= MAX_MARKET_PAGES

    @pytest.mark.asyncio
    async def test_fetch_markets_without_client_returns_empty(self, app: Application) -> None:
        """Test fetching with no client returns empty rather than raising."""
        assert await app._fetch_markets() == []
