"""
Unit tests for API response parsers.

Testing:
- Multi-format response parsing (dict, list, wrapped)
- Token extraction from various formats
- snake_case and camelCase handling
- Error cases (missing tokens, invalid format)

Interview Point - Why Test Parsers?
- Real-world APIs are inconsistent
- Defensive parsing critical for reliability
- Edge cases (missing fields, wrong types)
- Regression protection (API changes)
"""

import pytest

from src.api.parsers import ResponseParser


class TestResponseParser:
    """Test ResponseParser class."""

    def test_extract_tokens_from_dict_format(self) -> None:
        """Test parsing dict with tokens key."""
        response = {
            "id": "0xmarket",
            "tokens": [
                {"tokenId": "0xyes", "outcome": "YES", "price": "0.48"},
                {"tokenId": "0xno", "outcome": "NO", "price": "0.52"},
            ],
        }

        result = ResponseParser.extract_tokens_from_response(response, "test_id")

        assert result is not None
        yes_id, no_id = result
        assert yes_id == "0xyes"
        assert no_id == "0xno"

    def test_extract_tokens_from_wrapped_markets(self) -> None:
        """Test parsing dict with markets list."""
        response = {
            "markets": [
                {
                    "id": "0xmarket",
                    "tokens": [
                        {"tokenId": "0xyes", "outcome": "YES"},
                        {"tokenId": "0xno", "outcome": "NO"},
                    ],
                }
            ]
        }

        result = ResponseParser.extract_tokens_from_response(response, "test_id")

        assert result is not None
        yes_id, no_id = result
        assert yes_id == "0xyes"
        assert no_id == "0xno"

    def test_extract_tokens_from_list_format(self) -> None:
        """Test parsing direct list of markets."""
        response = [
            {
                "id": "0xmarket",
                "tokens": [
                    {"token_id": "0xyes", "outcome": "yes"},  # snake_case
                    {"token_id": "0xno", "outcome": "no"},
                ],
            }
        ]

        result = ResponseParser.extract_tokens_from_response(response, "test_id")

        assert result is not None
        yes_id, no_id = result
        assert yes_id == "0xyes"
        assert no_id == "0xno"

    def test_extract_tokens_handles_outcome_variations(self) -> None:
        """Test normalizing different outcome casings."""
        test_cases = [
            ("YES", "NO"),
            ("yes", "no"),
            ("Yes", "No"),
            ("Y", "N"),
        ]

        for yes_outcome, no_outcome in test_cases:
            response = {
                "tokens": [
                    {"tokenId": "0xyes", "outcome": yes_outcome},
                    {"tokenId": "0xno", "outcome": no_outcome},
                ]
            }

            result = ResponseParser.extract_tokens_from_response(response, "test")
            assert result is not None, f"Failed for {yes_outcome}/{no_outcome}"

    def test_extract_tokens_handles_id_field_variations(self) -> None:
        """Test different token ID field names."""
        test_cases = ["tokenId", "token_id", "id"]

        for field_name in test_cases:
            response = {
                "tokens": [
                    {field_name: "0xyes", "outcome": "YES"},
                    {field_name: "0xno", "outcome": "NO"},
                ]
            }

            result = ResponseParser.extract_tokens_from_response(response, "test")
            assert result is not None, f"Failed for field {field_name}"

    def test_extract_tokens_missing_tokens(self) -> None:
        """Test handling response with no tokens."""
        response = {"id": "0xmarket", "tokens": []}

        result = ResponseParser.extract_tokens_from_response(response, "test_id")

        assert result is None

    def test_extract_tokens_incomplete_tokens(self) -> None:
        """Test handling response with only YES or only NO."""
        # Only YES token
        response = {
            "tokens": [
                {"tokenId": "0xyes", "outcome": "YES"},
            ]
        }

        result = ResponseParser.extract_tokens_from_response(response, "test_id")
        assert result is None

    def test_extract_tokens_unknown_format(self) -> None:
        """Test handling unknown response format."""
        response = {"error": "Not found"}

        result = ResponseParser.extract_tokens_from_response(response, "test_id")

        assert result is None

    def test_parse_to_market_response_success(
        self, mock_api_market_response: dict
    ) -> None:
        """Test successful parsing to MarketResponse."""
        result = ResponseParser.parse_to_market_response(
            mock_api_market_response, "test_id"
        )

        assert result is not None
        assert result.market_id == "0xmarket123"
        assert result.question == "Will Bitcoin reach $100k in 2025?"
        assert len(result.tokens) == 2

    def test_parse_to_market_response_wrapped(
        self, mock_api_markets_list_response: dict
    ) -> None:
        """Test parsing wrapped markets response."""
        result = ResponseParser.parse_to_market_response(
            mock_api_markets_list_response, "test_id"
        )

        assert result is not None
        assert result.market_id == "0xmarket123"

    def test_parse_to_market_response_validation_failure(self) -> None:
        """Test handling validation errors."""
        # Missing required fields
        invalid_response = {"id": "0xmarket"}

        result = ResponseParser.parse_to_market_response(invalid_response, "test_id")

        assert result is None
