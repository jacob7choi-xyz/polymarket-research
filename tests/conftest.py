"""
Pytest configuration and shared fixtures.

Why conftest.py?
- Shared fixtures available to all test files
- Pytest discovers this automatically
- DRY: Define common test data once

Interview Point - Test Fixtures:
- Reusable test data
- Consistent test setup
- Reduces boilerplate in tests
"""

from datetime import datetime
from decimal import Decimal

import pytest

from src.domain.models import ArbitrageOpportunity, Market, Token


@pytest.fixture
def sample_yes_token() -> Token:
    """Sample YES token for testing."""
    return Token(
        token_id="0xyes123",
        outcome="Yes",
        price=Decimal("0.48"),
    )


@pytest.fixture
def sample_no_token() -> Token:
    """Sample NO token for testing."""
    return Token(
        token_id="0xno123",
        outcome="No",
        price=Decimal("0.48"),
    )


@pytest.fixture
def sample_market(sample_yes_token: Token, sample_no_token: Token) -> Market:
    """
    Sample market with arbitrage opportunity.

    YES: 0.48 + NO: 0.48 = 0.96 < 0.99 → arbitrage!
    """
    return Market(
        market_id="0xmarket123",
        condition_id="0xcond456",
        question="Will Bitcoin reach $100k in 2025?",
        yes_token=sample_yes_token,
        no_token=sample_no_token,
        volume=Decimal("50000"),
        liquidity=Decimal("10000"),
        end_date=datetime(2025, 12, 31, 23, 59, 59),
        active=True,
        category="crypto",
    )


@pytest.fixture
def sample_market_no_arbitrage() -> Market:
    """Sample market without arbitrage (YES + NO = 1.0)."""
    return Market(
        market_id="0xmarket456",
        condition_id="0xcond789",
        question="Will ETH flip BTC?",
        yes_token=Token(
            token_id="0xyes456",
            outcome="Yes",
            price=Decimal("0.50"),
        ),
        no_token=Token(
            token_id="0xno456",
            outcome="No",
            price=Decimal("0.50"),
        ),
        volume=Decimal("30000"),
        liquidity=Decimal("8000"),
        end_date=datetime(2025, 12, 31),
        active=True,
        category="crypto",
    )


@pytest.fixture
def sample_market_low_liquidity() -> Market:
    """Sample market with low liquidity (should be filtered)."""
    return Market(
        market_id="0xmarket_low",
        condition_id="0xcond_low",
        question="Obscure prediction",
        yes_token=Token(
            token_id="0xyes_low",
            outcome="Yes",
            price=Decimal("0.45"),
        ),
        no_token=Token(
            token_id="0xno_low",
            outcome="No",
            price=Decimal("0.45"),
        ),
        volume=Decimal("100"),  # Low volume
        liquidity=Decimal("50"),  # Low liquidity
        end_date=datetime(2025, 12, 31),
        active=True,
    )


@pytest.fixture
def sample_opportunity(sample_market: Market) -> ArbitrageOpportunity:
    """Sample arbitrage opportunity for testing."""
    return ArbitrageOpportunity(
        market=sample_market,
        detected_at=datetime.now(),
        expected_profit_per_dollar=sample_market.arbitrage_profit_per_dollar,
        recommended_position_size=Decimal("100"),
    )


@pytest.fixture
def mock_api_market_response() -> dict:
    """Mock API response for a market."""
    return {
        "id": "0xmarket123",
        "conditionId": "0xcond456",
        "question": "Will Bitcoin reach $100k in 2025?",
        "tokens": [
            {"tokenId": "0xyes123", "outcome": "YES", "price": "0.48"},
            {"tokenId": "0xno123", "outcome": "NO", "price": "0.48"},
        ],
        "volume": "50000",
        "liquidity": "10000",
        "endDate": "2025-12-31T23:59:59Z",
        "active": True,
        "category": "crypto",
    }


@pytest.fixture
def mock_api_markets_list_response(mock_api_market_response: dict) -> dict:
    """Mock API response for markets list."""
    return {"markets": [mock_api_market_response]}
