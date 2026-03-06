"""
Flexible response parsers for Polymarket API.

Mirrors reference code's extract_yes_no_token_ids_from_gamma() approach:
- Handle dict, list, nested structures
- Support snake_case and camelCase
- Extract YES/NO tokens from various formats
- Log unknown formats for monitoring

Why separate from client.py?
- Single Responsibility: Parsing logic isolated
- Testability: Easy to test with mock data
- Reusability: Can parse data from different sources
- Maintainability: API format changes isolated here

Interview Point - Postel's Law:
"Be conservative in what you send, be liberal in what you accept"
- Accept various response formats
- Normalize to consistent domain models
- Log unknowns (helps discover new API patterns)
- Don't fail on minor format differences
"""

from typing import Any

from ..domain.exceptions import InvalidTokenDataError
from ..monitoring.logging import get_logger
from .response_models import MarketResponse, TokenResponse

logger = get_logger(__name__)


class ResponseParser:
    """
    Parse YES/NO token IDs from various Polymarket API response formats.

    Based on reference code's flexible parsing approach.

    Handles:
    1. Dict with 'tokens' key: {"tokens": [...]}
    2. Dict with 'markets' list: {"markets": [{...}]}
    3. Direct list: [{...}, {...}]
    4. Various key naming: tokenId vs token_id, YES vs yes
    5. Nested structures

    Interview Point - Real-World API Integration:
    - APIs are inconsistent (different versions, different endpoints)
    - Defensive programming: Handle all observed formats
    - Fail gracefully: Log and skip bad data, don't crash
    - Monitor unknowns: New formats appear over time
    """

    @staticmethod
    def extract_tokens_from_response(
        response_data: Any,
        identifier: str,
    ) -> tuple[str, str] | None:
        """
        Extract YES and NO token IDs from API response.

        Args:
            response_data: Raw API response (dict or list)
            identifier: Market/condition ID (for logging)

        Returns:
            (yes_token_id, no_token_id) or None if not found

        Example responses handled:
        1. {"id": "0x123", "tokens": [{"tokenId": "0xyes", "outcome": "YES"}, ...]}
        2. {"markets": [{"tokens": [...]}]}
        3. [{"tokens": [...]}]

        Interview Point - Error Handling Philosophy:
        - Don't crash on unknown format
        - Log warning (helps discover new patterns)
        - Return None (caller decides how to handle)
        - Include context (identifier, format) in logs
        """
        try:
            # Case 1: Direct dict with tokens
            if isinstance(response_data, dict) and "tokens" in response_data:
                logger.debug(
                    "parser.direct_dict_format",
                    identifier=identifier,
                )
                return ResponseParser._extract_from_market_dict(response_data, identifier)

            # Case 2: Dict with markets list
            if isinstance(response_data, dict) and "markets" in response_data:
                markets = response_data["markets"]
                if markets and len(markets) > 0:
                    logger.debug(
                        "parser.wrapped_markets_format",
                        identifier=identifier,
                        market_count=len(markets),
                    )
                    return ResponseParser._extract_from_market_dict(markets[0], identifier)

            # Case 3: Direct list of markets
            if isinstance(response_data, list) and len(response_data) > 0:
                logger.debug(
                    "parser.list_format",
                    identifier=identifier,
                    item_count=len(response_data),
                )
                return ResponseParser._extract_from_market_dict(response_data[0], identifier)

            # Unknown format
            logger.warning(
                "parser.unknown_format",
                identifier=identifier,
                response_type=type(response_data).__name__,
                has_tokens="tokens" in response_data if isinstance(response_data, dict) else False,
                has_markets="markets" in response_data if isinstance(response_data, dict) else False,
                is_list=isinstance(response_data, list),
                list_length=len(response_data) if isinstance(response_data, list) else 0,
            )
            return None

        except Exception as e:
            logger.error(
                "parser.extraction_failed",
                identifier=identifier,
                error=str(e),
                error_type=type(e).__name__,
            )
            return None

    @staticmethod
    def _extract_from_market_dict(
        market_data: dict[str, Any],
        identifier: str,
    ) -> tuple[str, str] | None:
        """
        Extract YES/NO token IDs from single market dict.

        Handles:
        - Various key names: tokenId, token_id, id
        - Various outcome names: YES, yes, Yes, Y, NO, no, No, N
        - Missing tokens
        - Invalid token data

        Args:
            market_data: Market dict from API
            identifier: Market/condition ID (for logging)

        Returns:
            (yes_token_id, no_token_id) or None

        Interview Point - Defensive Parsing:
        - Try multiple key names (camelCase, snake_case)
        - Normalize outcome names
        - Validate we have both YES and NO
        - Log if incomplete data found
        """
        tokens = market_data.get("tokens", [])

        if not tokens:
            logger.warning(
                "parser.no_tokens",
                identifier=identifier,
            )
            return None

        yes_token_id: str | None = None
        no_token_id: str | None = None

        # Iterate through tokens to find YES and NO
        for token in tokens:
            # Extract token ID (handle various key names)
            # Try: tokenId, token_id, id
            token_id = (
                token.get("tokenId")
                or token.get("token_id")
                or token.get("id")
            )

            if not token_id:
                logger.debug(
                    "parser.token_missing_id",
                    identifier=identifier,
                    token_data=token,
                )
                continue

            # Extract outcome (handle various formats)
            outcome = token.get("outcome", "")
            outcome_upper = outcome.upper()

            # Match YES variations: YES, yes, Yes, Y
            if outcome_upper in ["YES", "Y"]:
                yes_token_id = str(token_id)

            # Match NO variations: NO, no, No, N
            elif outcome_upper in ["NO", "N"]:
                no_token_id = str(token_id)

            else:
                logger.debug(
                    "parser.unknown_outcome",
                    identifier=identifier,
                    outcome=outcome,
                )

        # Validate we found both tokens
        if yes_token_id and no_token_id:
            logger.debug(
                "parser.tokens_extracted",
                identifier=identifier,
                yes_token=yes_token_id,
                no_token=no_token_id,
            )
            return (yes_token_id, no_token_id)

        # Incomplete token data
        logger.warning(
            "parser.incomplete_tokens",
            identifier=identifier,
            yes_found=yes_token_id is not None,
            no_found=no_token_id is not None,
            token_count=len(tokens),
        )
        return None

    @staticmethod
    def parse_to_market_response(
        response_data: Any,
        identifier: str,
    ) -> MarketResponse | None:
        """
        Parse API response to MarketResponse Pydantic model.

        Args:
            response_data: Raw API response
            identifier: Market/condition ID (for logging)

        Returns:
            Validated MarketResponse or None if parsing fails

        This is a higher-level parser that:
        1. Extracts market data from various formats
        2. Validates with Pydantic
        3. Returns typed domain object

        Interview Point - Layered Parsing:
        - Layer 1: Extract raw data (handle format variations)
        - Layer 2: Validate with Pydantic (ensure data quality)
        - Layer 3: Convert to domain models (business logic)
        - Separation of concerns: Each layer has single responsibility
        """
        try:
            # Extract market data (handle various formats)
            market_dict: dict[str, Any] | None = None

            if isinstance(response_data, dict) and "tokens" in response_data:
                market_dict = response_data

            elif isinstance(response_data, dict) and "markets" in response_data:
                markets = response_data["markets"]
                if markets and len(markets) > 0:
                    market_dict = markets[0]

            elif isinstance(response_data, list) and len(response_data) > 0:
                market_dict = response_data[0]

            if not market_dict:
                logger.warning(
                    "parser.no_market_data",
                    identifier=identifier,
                )
                return None

            # Validate with Pydantic
            market_response = MarketResponse(**market_dict)

            logger.debug(
                "parser.market_parsed",
                identifier=identifier,
                market_id=market_response.market_id,
            )

            return market_response

        except ValueError as e:
            # Pydantic validation error
            logger.warning(
                "parser.validation_failed",
                identifier=identifier,
                error=str(e),
            )
            return None

        except Exception as e:
            # Unexpected error
            logger.error(
                "parser.parse_failed",
                identifier=identifier,
                error=str(e),
                error_type=type(e).__name__,
            )
            return None


# Example usage for documentation
if __name__ == "__main__":
    # Example 1: Parse dict with tokens
    print("=== Example 1: Dict with tokens ===")
    response1 = {
        "id": "0xmarket123",
        "tokens": [
            {"tokenId": "0xyes", "outcome": "YES", "price": "0.48"},
            {"tokenId": "0xno", "outcome": "NO", "price": "0.52"},
        ],
    }

    result1 = ResponseParser.extract_tokens_from_response(response1, "market123")
    if result1:
        yes_id, no_id = result1
        print(f"YES: {yes_id}, NO: {no_id}")

    # Example 2: Parse dict with markets list
    print("\n=== Example 2: Wrapped markets ===")
    response2 = {
        "markets": [
            {
                "id": "0xmarket456",
                "tokens": [
                    {"token_id": "0xyes2", "outcome": "yes", "price": 0.45},
                    {"token_id": "0xno2", "outcome": "no", "price": 0.50},
                ],
            }
        ]
    }

    result2 = ResponseParser.extract_tokens_from_response(response2, "condition456")
    if result2:
        yes_id, no_id = result2
        print(f"YES: {yes_id}, NO: {no_id}")

    # Example 3: Parse list of markets
    print("\n=== Example 3: List format ===")
    response3 = [
        {
            "id": "0xmarket789",
            "tokens": [
                {"id": "0xyes3", "outcome": "Yes", "price": "0.60"},
                {"id": "0xno3", "outcome": "No", "price": "0.35"},
            ],
        }
    ]

    result3 = ResponseParser.extract_tokens_from_response(response3, "query_result")
    if result3:
        yes_id, no_id = result3
        print(f"YES: {yes_id}, NO: {no_id}")

    # Example 4: Unknown format (logs warning)
    print("\n=== Example 4: Unknown format ===")
    response4 = {"error": "Not found"}

    result4 = ResponseParser.extract_tokens_from_response(response4, "unknown")
    print(f"Result: {result4}")

    # Example 5: Parse to MarketResponse
    print("\n=== Example 5: Full market parsing ===")
    from datetime import datetime

    response5 = {
        "id": "0xfullmarket",
        "conditionId": "0xcondition",
        "question": "Will BTC reach $100k?",
        "tokens": [
            {"tokenId": "0xyes", "outcome": "YES", "price": "0.48"},
            {"tokenId": "0xno", "outcome": "NO", "price": "0.48"},
        ],
        "volume": "50000",
        "liquidity": "10000",
        "endDate": "2025-12-31T23:59:59Z",
        "active": True,
    }

    market = ResponseParser.parse_to_market_response(response5, "full_test")
    if market:
        print(f"Market: {market.question}")
        print(f"Tokens: {len(market.tokens)}")
        print(f"Volume: ${market.volume}")
