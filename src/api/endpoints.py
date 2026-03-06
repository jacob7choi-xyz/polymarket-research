"""
Multi-endpoint fallback strategy for Polymarket API.

Mirrors reference code's resolve_outcome_token_ids() pattern:
- Try multiple URL patterns
- Fallback if one fails
- Handle different response formats

Why separate file?
- API versioning: Easy to add new endpoint patterns
- Testing: Can test URL generation independently
- Documentation: Single source of truth for API patterns
- Maintainability: API changes isolated to this file

Interview Point:
- Defensive programming: Don't assume single endpoint works
- Graceful degradation: Try alternatives before failing
- Real-world APIs: Often have multiple ways to fetch same data
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class EndpointStrategy:
    """
    Immutable endpoint configuration.

    Why frozen dataclass?
    - Immutable: Thread-safe, can't be accidentally modified
    - Hashable: Can use as dict keys
    - Type-safe: Better than dict or tuple
    - Clear: Self-documenting structure

    Attributes:
        pattern: URL pattern (e.g., "/markets/{id}")
        param_location: Where to put the identifier (path vs query)
        param_name: Name of the parameter
    """

    pattern: str
    param_location: Literal["path", "query"]
    param_name: str

    def build_url(self, identifier: str) -> tuple[str, dict[str, str] | None]:
        """
        Build URL and query params for this strategy.

        Args:
            identifier: Market ID or condition ID

        Returns:
            Tuple of (url_path, query_params)

        Example:
            >>> strategy = EndpointStrategy("/markets/{id}", "path", "id")
            >>> strategy.build_url("0x123")
            ("/markets/0x123", None)

            >>> strategy = EndpointStrategy("/markets", "query", "condition_id")
            >>> strategy.build_url("0x123")
            ("/markets", {"condition_id": "0x123"})
        """
        if self.param_location == "path":
            # Path parameter: Replace {id} in pattern
            url = self.pattern.replace("{id}", identifier)
            return (url, None)
        else:
            # Query parameter: Return pattern + query dict
            return (self.pattern, {self.param_name: identifier})


class PolymarketEndpoints:
    """
    Encapsulates all known Polymarket API endpoint patterns.

    Based on reference code's multi-endpoint fallback strategy.

    Interview Point - API Integration Patterns:
    - APIs change: New versions, deprecated endpoints
    - Multiple ways to fetch data: market_id vs condition_id
    - Fallback strategy: Try primary, then fallbacks
    - Future-proof: Easy to add new patterns
    """

    # Primary market fetch strategies (in order of preference)
    # Why this order?
    # 1. Direct market ID lookup (fastest, most reliable)
    # 2. Condition-based path lookup (newer API pattern)
    # 3. Query parameter lookup (older API pattern, broader results)
    MARKET_BY_ID_STRATEGIES = [
        EndpointStrategy(
            pattern="/markets/{id}",
            param_location="path",
            param_name="id",
        ),
        EndpointStrategy(
            pattern="/markets/condition/{id}",
            param_location="path",
            param_name="id",
        ),
        EndpointStrategy(
            pattern="/markets",
            param_location="query",
            param_name="condition_id",
        ),
    ]

    # Alternative: By-condition endpoint patterns
    # Some Polymarket API versions use different paths
    CONDITION_STRATEGIES = [
        EndpointStrategy(
            pattern="/markets/by-condition/{id}",
            param_location="path",
            param_name="id",
        ),
        EndpointStrategy(
            pattern="/markets/condition/{id}",
            param_location="path",
            param_name="id",
        ),
    ]

    @classmethod
    def get_market_urls(cls, identifier: str, include_query: bool = True) -> list[tuple[str, dict[str, str] | None]]:
        """
        Generate all possible URLs for fetching market/condition.

        Args:
            identifier: Market ID or condition ID (hex string)
            include_query: Whether to include query parameter strategies

        Returns:
            List of (url, params) tuples to try in order

        Example:
            >>> PolymarketEndpoints.get_market_urls("0x123abc")
            [
                ("/markets/0x123abc", None),
                ("/markets/condition/0x123abc", None),
                ("/markets", {"condition_id": "0x123abc"})
            ]

        Interview Point - Fallback Strategy:
        - Try fastest/most reliable first
        - Fallback to alternatives if 404
        - Stop on first success
        - Log which endpoint succeeded (monitoring)
        """
        urls = []

        # Add primary strategies
        for strategy in cls.MARKET_BY_ID_STRATEGIES:
            # Skip query strategies if not included
            if not include_query and strategy.param_location == "query":
                continue
            urls.append(strategy.build_url(identifier))

        return urls

    @classmethod
    def get_condition_urls(cls, condition_id: str) -> list[tuple[str, dict[str, str] | None]]:
        """
        Generate URLs specifically for condition lookups.

        Args:
            condition_id: Condition ID (hex string)

        Returns:
            List of (url, params) tuples
        """
        urls = []
        for strategy in cls.CONDITION_STRATEGIES:
            urls.append(strategy.build_url(condition_id))
        return urls

    @classmethod
    def get_markets_list_url(
        cls,
        limit: int | None = None,
        offset: int | None = None,
        category: str | None = None,
    ) -> tuple[str, dict[str, str]]:
        """
        Get URL for fetching list of markets.

        Args:
            limit: Maximum number of markets to return
            offset: Pagination offset
            category: Filter by category (e.g., "politics", "crypto")

        Returns:
            Tuple of (url, query_params)

        Example:
            >>> PolymarketEndpoints.get_markets_list_url(limit=10, category="politics")
            ("/markets", {"limit": "10", "category": "politics"})
        """
        params: dict[str, str] = {}

        if limit is not None:
            params["limit"] = str(limit)
        if offset is not None:
            params["offset"] = str(offset)
        if category is not None:
            params["category"] = category

        return ("/markets", params)


# Example usage for documentation
if __name__ == "__main__":
    print("=== Market URL Generation ===")

    # Example 1: Generate URLs for market/condition ID
    market_id = "0x123abc456def"
    urls = PolymarketEndpoints.get_market_urls(market_id)

    print(f"URLs for market {market_id}:")
    for i, (url, params) in enumerate(urls, 1):
        if params:
            print(f"  {i}. {url} with params: {params}")
        else:
            print(f"  {i}. {url}")

    # Example 2: Condition-specific URLs
    print("\n=== Condition URL Generation ===")
    condition_id = "0xabc123"
    condition_urls = PolymarketEndpoints.get_condition_urls(condition_id)

    print(f"URLs for condition {condition_id}:")
    for i, (url, params) in enumerate(condition_urls, 1):
        print(f"  {i}. {url}")

    # Example 3: Markets list with filters
    print("\n=== Markets List URL ===")
    list_url, list_params = PolymarketEndpoints.get_markets_list_url(
        limit=10,
        category="crypto",
    )
    print(f"URL: {list_url}")
    print(f"Params: {list_params}")

    # Example 4: Using EndpointStrategy directly
    print("\n=== EndpointStrategy Usage ===")
    strategy = EndpointStrategy(
        pattern="/markets/{id}",
        param_location="path",
        param_name="id",
    )
    url, params = strategy.build_url("0x789")
    print(f"Strategy: {strategy.pattern}")
    print(f"Generated URL: {url}")
    print(f"Query params: {params}")
