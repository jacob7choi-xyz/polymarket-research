"""
Domain constants for arbitrage detection.

Why separate from settings.py?
- Settings: Operational config that varies between environments (dev/prod)
- Constants: Business logic values that remain consistent across all environments

Interview Point: Separation of Concerns - configuration vs domain knowledge
"""

from decimal import Decimal

# ============================================================================
# Arbitrage Detection Thresholds
# ============================================================================

# Core arbitrage condition: YES + NO < ARBITRAGE_THRESHOLD
# Why 0.99 instead of 1.0?
# - Polymarket charges ~2% fees on winning outcomes
# - Slippage during execution (prices move)
# - Safety buffer ensures profit after all costs
ARBITRAGE_THRESHOLD = Decimal("0.99")

# Minimum profit required to consider opportunity worth executing
# $0.01 per $1 invested = 1% ROI minimum
MIN_PROFIT_THRESHOLD = Decimal("0.01")

# ============================================================================
# Risk Management
# ============================================================================

# Minimum market liquidity to avoid execution risk
# If liquidity < $1000, orders may move prices significantly
MIN_LIQUIDITY = Decimal("1000")

# Minimum 24h volume indicates market is active and prices are reliable
# Low volume markets may have stale prices
MIN_VOLUME = Decimal("10000")

# Maximum position size as percentage of market liquidity
# Taking >1% of liquidity creates price impact (slippage)
# Interview Point: Market microstructure - why liquidity matters
MAX_POSITION_PCT_OF_LIQUIDITY = Decimal("0.01")

# ============================================================================
# API Endpoint Patterns
# ============================================================================

# Multiple endpoint patterns for fetching market data
# Mirrors reference code's multi-endpoint fallback strategy
# Different API versions use different URL patterns
MARKET_ENDPOINT_PATTERNS = [
    "/markets/{id}",  # Primary endpoint
    "/markets/condition/{id}",  # Fallback for condition-based lookup
    "/markets",  # Query param based (needs ?condition_id={id})
]

# ============================================================================
# Market Categories
# ============================================================================

# Focus on high-volume, liquid markets
# Politics and crypto tend to have:
# - High trading volume (easier execution)
# - More market participants (more arbitrage opportunities)
# - Binary YES/NO outcomes (required for arbitrage strategy)
DEFAULT_MARKET_CATEGORIES = ["politics", "crypto"]

# ============================================================================
# System Defaults
# ============================================================================

# Default polling interval (seconds)
# Why 60s? Balance between:
# - Opportunity detection speed (faster = more opportunities)
# - API rate limits (slower = fewer requests)
# - System resource usage
DEFAULT_POLL_INTERVAL = 60.0

# Default paper trading capital
# $10k is enough to test strategy without over-committing
DEFAULT_INITIAL_CAPITAL = Decimal("10000")

# Default max position size per opportunity
# $100 = 1% of default capital (Kelly criterion-inspired sizing)
DEFAULT_MAX_POSITION_SIZE = Decimal("100")
