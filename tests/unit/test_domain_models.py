"""
Unit tests for domain models.

Testing:
- Token model validation
- Market model business logic
- ArbitrageOpportunity calculations
- Immutability (frozen models)

Interview Point - What to Test in Domain Models:
- Business rules (is_arbitrage_opportunity)
- Calculated properties (total_probability, profit)
- Edge cases (boundary values)
- Immutability (can't modify after creation)
"""

from datetime import datetime
from decimal import Decimal

import pytest

from src.domain.models import ArbitrageOpportunity, Market, Token


class TestToken:
    """Test Token domain model."""

    def test_token_creation(self, sample_yes_token: Token) -> None:
        """Test creating a valid token."""
        assert sample_yes_token.token_id == "0xyes123"
        assert sample_yes_token.outcome == "Yes"
        assert sample_yes_token.price == Decimal("0.48")

    def test_token_implied_probability(self, sample_yes_token: Token) -> None:
        """Test implied probability equals price."""
        assert sample_yes_token.implied_probability == Decimal("0.48")

    def test_token_price_validation_too_high(self) -> None:
        """Test price validation rejects > 1.0."""
        with pytest.raises(ValueError, match="must be between 0 and 1"):
            Token(token_id="0x123", outcome="Yes", price=Decimal("1.5"))

    def test_token_price_validation_negative(self) -> None:
        """Test price validation rejects negative."""
        with pytest.raises(ValueError, match="must be between 0 and 1"):
            Token(token_id="0x123", outcome="Yes", price=Decimal("-0.1"))

    def test_token_immutability(self, sample_yes_token: Token) -> None:
        """Test token is immutable (frozen)."""
        with pytest.raises(Exception):  # Pydantic raises validation error
            sample_yes_token.price = Decimal("0.50")  # type: ignore


class TestMarket:
    """Test Market domain model."""

    def test_market_creation(self, sample_market: Market) -> None:
        """Test creating a valid market."""
        assert sample_market.market_id == "0xmarket123"
        assert sample_market.question == "Will Bitcoin reach $100k in 2025?"
        assert sample_market.yes_token.price == Decimal("0.48")
        assert sample_market.no_token.price == Decimal("0.48")

    def test_total_implied_probability(self, sample_market: Market) -> None:
        """Test total probability calculation."""
        expected = Decimal("0.48") + Decimal("0.48")
        assert sample_market.total_implied_probability == expected

    def test_is_arbitrage_opportunity_true(self, sample_market: Market) -> None:
        """Test arbitrage detection when YES + NO < 0.99."""
        # sample_market has 0.48 + 0.48 = 0.96 < 0.99
        assert sample_market.is_arbitrage_opportunity is True

    def test_is_arbitrage_opportunity_false(
        self, sample_market_no_arbitrage: Market
    ) -> None:
        """Test no arbitrage when YES + NO >= 0.99."""
        # sample_market_no_arbitrage has 0.50 + 0.50 = 1.00 >= 0.99
        assert sample_market_no_arbitrage.is_arbitrage_opportunity is False

    def test_arbitrage_profit_per_dollar(self, sample_market: Market) -> None:
        """Test profit calculation."""
        # 1.0 - (0.48 + 0.48) = 0.04
        expected_profit = Decimal("1.0") - Decimal("0.96")
        assert sample_market.arbitrage_profit_per_dollar == expected_profit

    def test_arbitrage_profit_zero_when_no_arbitrage(
        self, sample_market_no_arbitrage: Market
    ) -> None:
        """Test profit is zero when no arbitrage."""
        assert sample_market_no_arbitrage.arbitrage_profit_per_dollar == Decimal("0")

    def test_is_expired_false_future_date(self, sample_market: Market) -> None:
        """Test market not expired when end_date in future."""
        assert sample_market.is_expired is False

    def test_is_expired_true_past_date(self) -> None:
        """Test market expired when end_date in past."""
        market = Market(
            market_id="0xexpired",
            condition_id="0xcond",
            question="Past market",
            yes_token=Token(token_id="0xyes", outcome="Yes", price=Decimal("0.5")),
            no_token=Token(token_id="0xno", outcome="No", price=Decimal("0.5")),
            volume=Decimal("1000"),
            liquidity=Decimal("500"),
            end_date=datetime(2020, 1, 1),  # Past
            active=True,
        )
        assert market.is_expired is True

    def test_is_tradeable_true(self, sample_market: Market) -> None:
        """Test market is tradeable when active, not expired, has arbitrage."""
        assert sample_market.is_tradeable is True

    def test_is_tradeable_false_inactive(self, sample_market: Market) -> None:
        """Test market not tradeable when inactive."""
        # Create inactive market
        inactive_market = Market(
            market_id="0xinactive",
            condition_id="0xcond",
            question="Inactive market",
            yes_token=sample_market.yes_token,
            no_token=sample_market.no_token,
            volume=sample_market.volume,
            liquidity=sample_market.liquidity,
            end_date=sample_market.end_date,
            active=False,  # Inactive
        )
        assert inactive_market.is_tradeable is False

    def test_market_immutability(self, sample_market: Market) -> None:
        """Test market is immutable."""
        with pytest.raises(Exception):
            sample_market.active = False  # type: ignore


class TestArbitrageOpportunity:
    """Test ArbitrageOpportunity model."""

    def test_opportunity_creation(self, sample_opportunity: ArbitrageOpportunity) -> None:
        """Test creating opportunity."""
        assert sample_opportunity.market.market_id == "0xmarket123"
        assert sample_opportunity.expected_profit_per_dollar > 0
        assert sample_opportunity.recommended_position_size == Decimal("100")

    def test_total_expected_profit(self, sample_opportunity: ArbitrageOpportunity) -> None:
        """Test total profit calculation."""
        # profit_per_dollar * position_size
        expected = (
            sample_opportunity.expected_profit_per_dollar
            * sample_opportunity.recommended_position_size
        )
        assert sample_opportunity.total_expected_profit == expected

    def test_expected_roi_percent(self, sample_opportunity: ArbitrageOpportunity) -> None:
        """Test ROI percentage calculation."""
        # profit_per_dollar * 100
        expected = sample_opportunity.expected_profit_per_dollar * Decimal("100")
        assert sample_opportunity.expected_roi_percent == expected

    def test_opportunity_age_seconds(self, sample_opportunity: ArbitrageOpportunity) -> None:
        """Test age calculation."""
        # Should be very small (just created)
        assert sample_opportunity.age_seconds < 1.0

    def test_is_stale_false_fresh(self, sample_opportunity: ArbitrageOpportunity) -> None:
        """Test fresh opportunity is not stale."""
        assert sample_opportunity.is_stale(max_age_seconds=60.0) is False

    def test_profit_validation_rejects_negative(self, sample_market: Market) -> None:
        """Test opportunity rejects negative profit."""
        with pytest.raises(ValueError, match="must be positive"):
            ArbitrageOpportunity(
                market=sample_market,
                detected_at=datetime.now(),
                expected_profit_per_dollar=Decimal("-0.01"),  # Negative!
                recommended_position_size=Decimal("100"),
            )
