"""
Core domain models for arbitrage detection system.

Why separate from API models (response_models.py)?
- Domain models: Business logic, clean naming, required fields
- API models: Match API structure, handle inconsistencies
- Separation: API changes don't break business logic

Interview Points:
- Frozen Pydantic models: Immutable for thread safety in async code
- Decimal for prices: Financial arithmetic requires exact precision
- Rich domain objects: Business logic lives in models (not services)
- Computed fields: Derive values from state (total_probability, is_arbitrage)
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_validator


class Token(BaseModel):
    """
    Represents a YES or NO outcome token in a prediction market.

    Why Decimal for price?
    - Financial correctness: float has rounding errors
    - Example: float(0.1) + float(0.2) = 0.30000000000000004
    - Arbitrage depends on exact price calculations
    - Interview Point: Always use Decimal for money/prices

    Why frozen?
    - Thread safety: Can share across async coroutines
    - Immutability: Prevents accidental mutations
    - Hashable: Can use as dict keys
    - Functional programming: Easier to reason about
    """

    token_id: str = Field(description="Unique token identifier (hex string)")
    outcome: Literal["Yes", "No"] = Field(description="YES or NO outcome")
    price: Decimal = Field(description="Current price (0.0 to 1.0)")

    class Config:
        frozen = True  # Immutable
        str_strip_whitespace = True

    @field_validator("price")
    @classmethod
    def validate_price_range(cls, v: Decimal) -> Decimal:
        """Ensure price is valid probability [0, 1]."""
        if not (Decimal("0") <= v <= Decimal("1")):
            raise ValueError(f"Price must be between 0 and 1, got {v}")
        return v

    @computed_field  # type: ignore
    @property
    def implied_probability(self) -> Decimal:
        """
        Convert price to implied probability.

        In prediction markets: price = implied probability
        - Price of 0.48 = 48% chance of YES
        - Price of 0.85 = 85% chance of NO

        Why computed field?
        - Derived from price (don't store redundantly)
        - Always up-to-date
        - Clear intent in domain model
        """
        return self.price


class Market(BaseModel):
    """
    Binary prediction market (YES/NO question).

    Rich domain model with embedded business logic.

    Example: "Will Bitcoin reach $100k in 2025?"
    - YES token: $0.48 (48% implied probability)
    - NO token: $0.48 (48% implied probability)
    - Total: 0.96 < 0.99 → Arbitrage opportunity!

    Interview Point - Rich Domain Models vs Anemic Models:
    - Anemic: Just data, logic in services
    - Rich: Data + behavior, self-contained
    - Rich models: Better encapsulation, clearer code
    """

    market_id: str = Field(description="Unique market identifier")
    condition_id: str = Field(description="Condition this market belongs to")
    question: str = Field(description="Question being predicted")
    yes_token: Token = Field(description="YES outcome token")
    no_token: Token = Field(description="NO outcome token")
    volume: Decimal = Field(description="24h trading volume (USD)")
    liquidity: Decimal = Field(description="Current liquidity (USD)")
    end_date: datetime = Field(description="Market resolution date")
    active: bool = Field(description="Is market active for trading")
    category: str | None = Field(default=None, description="Market category")

    class Config:
        frozen = True

    @computed_field  # type: ignore
    @property
    def total_implied_probability(self) -> Decimal:
        """
        Sum of YES and NO probabilities.

        In efficient market: Should equal 1.0
        - YES: 0.50 + NO: 0.50 = 1.00 (efficient, no arbitrage)
        - YES: 0.48 + NO: 0.48 = 0.96 (inefficient, arbitrage exists!)

        Why not 1.0 in real markets?
        - Transaction fees
        - Bid-ask spread
        - Market inefficiency
        - Risk premium

        Interview Point: Market efficiency and arbitrage
        """
        return self.yes_token.price + self.no_token.price

    @computed_field  # type: ignore
    @property
    def is_arbitrage_opportunity(self) -> bool:
        """
        Core arbitrage detection logic.

        Arbitrage exists when: YES + NO < 0.99

        Why 0.99 instead of 1.0?
        - Polymarket fees: ~2% on winning outcomes
        - Slippage: Prices move during execution
        - Safety buffer: Ensures profit after costs

        Strategy:
        1. Buy YES token for $0.48
        2. Buy NO token for $0.48
        3. Total cost: $0.96
        4. Guaranteed payout: $1.00 (one outcome will win)
        5. Profit: $1.00 - $0.96 = $0.04 (4% ROI)

        Interview Point: Why this is risk-free arbitrage
        - Guaranteed outcome: One of YES/NO must win
        - No market risk: Don't care which outcome wins
        - Execution risk: Only risk is failure to execute
        """
        # Threshold from configuration (default 0.99)
        from ..config.constants import ARBITRAGE_THRESHOLD

        return self.total_implied_probability < ARBITRAGE_THRESHOLD

    @computed_field  # type: ignore
    @property
    def arbitrage_profit_per_dollar(self) -> Decimal:
        """
        Expected profit per $1 invested.

        Example:
        - YES: $0.48, NO: $0.48
        - Total: $0.96
        - Profit: $1.00 - $0.96 = $0.04 per $1 invested (4% ROI)

        Returns:
            Decimal: Profit per dollar (0.04 = 4 cents profit per $1)

        Interview Point: Position sizing
        - Higher profit → larger position size
        - Kelly Criterion: Optimal position sizing formula
        - Risk management: Don't bet everything on one opportunity
        """
        if self.is_arbitrage_opportunity:
            return Decimal("1.0") - self.total_implied_probability
        return Decimal("0")

    @computed_field  # type: ignore
    @property
    def is_expired(self) -> bool:
        """Check if market has ended."""
        return self.end_date < datetime.now()

    @computed_field  # type: ignore
    @property
    def is_tradeable(self) -> bool:
        """
        Check if market can be traded.

        Requirements:
        - Active status
        - Not expired
        - Has arbitrage opportunity

        Why check all three?
        - Active: Market might be paused by exchange
        - Not expired: Can't trade after resolution
        - Has opportunity: Only trade profitable opportunities
        """
        return self.active and not self.is_expired and self.is_arbitrage_opportunity


class ArbitrageOpportunity(BaseModel):
    """
    Represents a detected arbitrage opportunity.

    Why separate from Market?
    - Market: Data model (what is)
    - Opportunity: Action model (what to do)
    - Separation of concerns: Market can exist without being an opportunity

    Contains:
    - Market data
    - Detection timestamp
    - Expected profit
    - Recommended position size
    """

    market: Market = Field(description="Market with arbitrage opportunity")
    detected_at: datetime = Field(
        default_factory=datetime.now,
        description="When opportunity was detected",
    )
    expected_profit_per_dollar: Decimal = Field(
        description="Expected profit per $1 invested"
    )
    recommended_position_size: Decimal = Field(
        description="Recommended position size (USD)"
    )

    class Config:
        frozen = True

    @field_validator("expected_profit_per_dollar")
    @classmethod
    def validate_positive_profit(cls, v: Decimal) -> Decimal:
        """Ensure profit is positive (sanity check)."""
        if v <= 0:
            raise ValueError(f"Arbitrage profit must be positive, got {v}")
        return v

    @computed_field  # type: ignore
    @property
    def total_expected_profit(self) -> Decimal:
        """
        Total expected profit for this opportunity.

        Example:
        - Profit per dollar: $0.04
        - Position size: $100
        - Total profit: $0.04 × $100 = $4.00
        """
        return self.expected_profit_per_dollar * self.recommended_position_size

    @computed_field  # type: ignore
    @property
    def expected_roi_percent(self) -> Decimal:
        """
        Expected return on investment as percentage.

        Example:
        - Profit per dollar: $0.04
        - ROI: 4.0%
        """
        return self.expected_profit_per_dollar * Decimal("100")

    @computed_field  # type: ignore
    @property
    def age_seconds(self) -> float:
        """
        How long ago was this opportunity detected?

        Why track age?
        - Stale opportunities: Prices may have changed
        - Monitoring: Alert if opportunities sit too long
        - Priority: Process newer opportunities first
        """
        return (datetime.now() - self.detected_at).total_seconds()

    def is_stale(self, max_age_seconds: float = 60.0) -> bool:
        """
        Check if opportunity is stale.

        Args:
            max_age_seconds: Maximum age before considering stale

        Returns:
            True if opportunity is older than max_age_seconds

        Interview Point: Market data freshness
        - Prices change rapidly in active markets
        - Old opportunities may no longer be profitable
        - Always re-check prices before execution
        """
        return self.age_seconds > max_age_seconds


# Example usage for documentation
if __name__ == "__main__":
    # Example 1: Create tokens
    yes_token = Token(token_id="0xyes", outcome="Yes", price=Decimal("0.48"))
    no_token = Token(token_id="0xno", outcome="No", price=Decimal("0.48"))

    print(f"YES: {yes_token.price} (probability: {yes_token.implied_probability})")
    print(f"NO: {no_token.price} (probability: {no_token.implied_probability})")

    # Example 2: Create market
    market = Market(
        market_id="0xmarket123",
        condition_id="0xcondition456",
        question="Will Bitcoin reach $100k in 2025?",
        yes_token=yes_token,
        no_token=no_token,
        volume=Decimal("50000"),
        liquidity=Decimal("10000"),
        end_date=datetime(2025, 12, 31, 23, 59, 59),
        active=True,
        category="crypto",
    )

    print(f"\nMarket: {market.question}")
    print(f"Total probability: {market.total_implied_probability}")
    print(f"Is arbitrage? {market.is_arbitrage_opportunity}")
    print(f"Profit per $: {market.arbitrage_profit_per_dollar}")

    # Example 3: Create opportunity
    if market.is_arbitrage_opportunity:
        opportunity = ArbitrageOpportunity(
            market=market,
            expected_profit_per_dollar=market.arbitrage_profit_per_dollar,
            recommended_position_size=Decimal("100"),
        )

        print(f"\nOpportunity detected!")
        print(f"Position size: ${opportunity.recommended_position_size}")
        print(f"Expected profit: ${opportunity.total_expected_profit}")
        print(f"Expected ROI: {opportunity.expected_roi_percent}%")

    # Example 4: Immutability test
    try:
        market.active = False  # type: ignore
    except Exception as e:
        print(f"\nImmutability test: {type(e).__name__} (models are frozen)")
