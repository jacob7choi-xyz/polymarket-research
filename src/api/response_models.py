"""
Pydantic models for Polymarket API responses.

Why separate from domain models?
- API models: Match exact API structure (snake_case, camelCase mixing, optional fields)
- Domain models: Clean business logic representation (consistent naming, required fields)
- Decoupling: API changes don't require domain model changes

Interview Point - Data Validation Strategy:
1. API boundary: Validate structure with Pydantic (fail fast on bad data)
2. Transformation layer: Convert API models → domain models
3. Domain layer: Business logic with validated, clean data

This follows the Ports and Adapters (Hexagonal Architecture) pattern.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class TokenResponse(BaseModel):
    """
    Raw token data from Polymarket API.

    Polymarket API inconsistencies handled:
    - Field names: tokenId vs token_id (use aliases)
    - Outcome casing: YES vs yes vs Yes (normalize in validator)
    - Price formats: string vs number (Pydantic coerces)

    Interview Point - API Integration Best Practices:
    - Be liberal in what you accept (Postel's Law)
    - Normalize data at boundaries
    - Log unknown formats for monitoring
    """

    # Token ID (hex string like "0x123abc...")
    # Why Field(alias=...)? API uses camelCase, we prefer snake_case
    token_id: str = Field(alias="tokenId")

    # Outcome: YES or NO
    # API returns various casings, we normalize to title case
    outcome: str

    # Current price (0.0 to 1.0)
    # Why Decimal? Financial calculations require exact arithmetic
    # Interview Point: float(0.1) + float(0.2) != 0.3 (binary floating point issue)
    price: Decimal

    # Trading volume (optional, not always provided)
    volume: Decimal | None = None

    class Config:
        # Allow both snake_case and camelCase field names
        # Enables: TokenResponse(tokenId="123") OR TokenResponse(token_id="123")
        populate_by_name = True

    @field_validator("outcome")
    @classmethod
    def normalize_outcome(cls, v: str) -> Literal["Yes", "No"]:
        """
        Normalize outcome to title case.

        API returns: "YES", "yes", "Yes", "NO", "no", "No"
        We normalize to: "Yes" or "No"

        Why? Consistent data makes business logic simpler.
        """
        normalized = v.capitalize()
        if normalized not in ["Yes", "No"]:
            raise ValueError(f"Invalid outcome: {v}. Must be Yes or No")
        return normalized  # type: ignore

    @field_validator("price", mode="before")
    @classmethod
    def validate_price_range(cls, v: Any) -> Decimal:
        """
        Validate price is in valid range [0, 1].

        Why [0, 1]?
        - Prices in prediction markets = implied probability
        - Probability must be between 0 and 1
        - Price of 0.48 = 48% chance of YES

        Interview Point: Validate at boundaries, fail fast on bad data
        """
        price = Decimal(str(v))
        if not (Decimal("0") <= price <= Decimal("1")):
            raise ValueError(f"Price must be between 0 and 1, got {price}")
        return price


class MarketResponse(BaseModel):
    """
    Market data response from Polymarket API.

    Represents a binary prediction market (YES/NO question).
    Example: "Will Bitcoin reach $100k in 2025?"
    """

    # Unique market identifier (hex string)
    market_id: str = Field(alias="id")

    # Condition ID (used for grouping related markets)
    condition_id: str = Field(alias="conditionId")

    # Question being predicted
    # Example: "Will Bitcoin reach $100k by end of 2025?"
    question: str

    # Market description (optional, longer form)
    description: str | None = None

    # YES and NO outcome tokens
    # Why list? Some markets have >2 outcomes (we filter to binary only)
    tokens: list[TokenResponse]

    # 24-hour trading volume in USD
    volume: Decimal = Decimal("0")

    # Current liquidity in USD
    # Why important? High liquidity = less slippage = better execution
    liquidity: Decimal = Field(default=Decimal("0"), alias="liquidity")

    # Market end date (when question resolves)
    end_date: datetime = Field(alias="endDate")

    # Is market currently active for trading?
    active: bool = True

    # Market category (politics, crypto, sports, etc.)
    category: str | None = None

    class Config:
        populate_by_name = True

    @field_validator("tokens")
    @classmethod
    def validate_binary_market(cls, v: list[TokenResponse]) -> list[TokenResponse]:
        """
        Ensure market has exactly 2 tokens (YES and NO).

        Why?
        - Our arbitrage strategy requires binary markets
        - Multi-outcome markets have different probability math
        - Fail fast: Better to skip than process incorrectly

        Interview Point: Business rule validation at data layer
        """
        if len(v) != 2:
            raise ValueError(f"Binary market must have exactly 2 tokens, got {len(v)}")

        outcomes = {token.outcome for token in v}
        if outcomes != {"Yes", "No"}:
            raise ValueError(f"Market must have Yes and No outcomes, got {outcomes}")

        return v

    @field_validator("end_date", mode="before")
    @classmethod
    def parse_end_date(cls, v: Any) -> datetime:
        """
        Parse end date from various formats.

        API might return:
        - ISO timestamp: "2025-12-31T23:59:59Z"
        - Unix timestamp: 1735689599
        - Date string: "2025-12-31"

        Interview Point: Defensive parsing for real-world APIs
        """
        if isinstance(v, datetime):
            return v
        if isinstance(v, int):
            # Unix timestamp
            return datetime.fromtimestamp(v)
        if isinstance(v, str):
            # ISO timestamp
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        raise ValueError(f"Invalid end_date format: {v}")


class MarketsListResponse(BaseModel):
    """
    Response when fetching multiple markets.

    Polymarket API returns:
    - Sometimes: {"markets": [...]}
    - Sometimes: [...]

    This model handles the wrapped format.
    """

    markets: list[MarketResponse]


class ConditionMarketsResponse(BaseModel):
    """
    Response when fetching markets by condition_id.

    Different endpoint pattern:
    - /markets/condition/{id} returns: {"markets": [...], "condition": {...}}
    - /markets?condition_id={id} returns: [...]

    Why separate model?
    - Different response structure
    - Contains additional condition metadata
    - Easier to maintain separate models than complex unions
    """

    markets: list[MarketResponse]
    # Condition metadata (optional, not always needed)
    condition: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """
    Standard error response from Polymarket API.

    Example:
    {
        "error": "Market not found",
        "code": "NOT_FOUND",
        "details": {"market_id": "0x123"}
    }

    Why model errors?
    - Structured error handling
    - Extract error codes for specific handling
    - Include details in logging
    """

    error: str
    code: str | None = None
    details: dict[str, Any] | None = None
    message: str | None = None

    @property
    def full_message(self) -> str:
        """
        Combine error and message for logging.

        Returns: "Market not found: Invalid market ID"
        """
        if self.message:
            return f"{self.error}: {self.message}"
        return self.error


# Example usage for documentation
if __name__ == "__main__":
    # Example 1: Parse token response with camelCase
    token_data = {"tokenId": "0x123", "outcome": "YES", "price": "0.48"}
    token = TokenResponse(**token_data)
    print(f"Token: {token.outcome} at {token.price}")

    # Example 2: Parse token response with snake_case
    token_data_snake = {"token_id": "0x456", "outcome": "no", "price": 0.52}
    token2 = TokenResponse(**token_data_snake)
    print(f"Token: {token2.outcome} at {token2.price}")

    # Example 3: Parse market response
    market_data = {
        "id": "0xmarket123",
        "conditionId": "0xcond456",
        "question": "Will Bitcoin reach $100k?",
        "tokens": [
            {"tokenId": "0xyes", "outcome": "YES", "price": "0.48"},
            {"tokenId": "0xno", "outcome": "NO", "price": "0.48"},
        ],
        "volume": "50000",
        "liquidity": "10000",
        "endDate": "2025-12-31T23:59:59Z",
        "active": True,
    }
    market = MarketResponse(**market_data)
    print(f"Market: {market.question}")
    print(f"Tokens: {len(market.tokens)}")

    # Example 4: Price validation
    try:
        invalid_token = TokenResponse(tokenId="0x999", outcome="Yes", price="1.5")
    except ValueError as e:
        print(f"Validation error: {e}")
