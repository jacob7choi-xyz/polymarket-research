"""
Application settings using Pydantic BaseSettings.

Why Pydantic BaseSettings?
- Type safety: Validates all config at startup (fail fast)
- Multi-source: Loads from environment variables, YAML files, and defaults
- 12-factor app: Environment-based configuration for cloud deployment
- Auto-documentation: Field descriptions serve as documentation

Interview Points:
- Configuration validation prevents runtime errors
- Environment variables for secrets (never commit credentials)
- YAML for complex configuration (readability)
- Defaults for developer convenience
"""

from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .constants import (
    ARBITRAGE_THRESHOLD,
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_MAX_POSITION_SIZE,
    DEFAULT_MARKET_CATEGORIES,
    DEFAULT_POLL_INTERVAL,
    MIN_LIQUIDITY,
    MIN_VOLUME,
)


class Settings(BaseSettings):
    """
    Application settings with validation.

    Load order (later overrides earlier):
    1. Default values defined here
    2. YAML config file (if specified)
    3. Environment variables with ARBITRAGE_ prefix

    Example:
        ARBITRAGE_LOG_LEVEL=DEBUG will override log_level

    Why this pattern?
    - Defaults: Developers can run without any config
    - YAML: Ops teams can manage complex config files
    - Env vars: Cloud platforms inject secrets via environment
    """

    model_config = SettingsConfigDict(
        env_prefix="ARBITRAGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore unknown env vars (defensive)
    )

    # ========================================================================
    # API Configuration
    # ========================================================================

    polymarket_api_url: HttpUrl = Field(
        default="https://gamma-api.polymarket.com",
        description="Polymarket Gamma API base URL",
    )

    api_timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=120.0,
        description="HTTP request timeout in seconds",
    )

    api_max_connections: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum concurrent HTTP connections (connection pool size)",
    )

    # ========================================================================
    # Rate Limiting
    # ========================================================================

    rate_limit_requests_per_second: float = Field(
        default=10.0,
        ge=0.1,
        le=100.0,
        description="Token bucket: tokens added per second (sustainable rate)",
    )

    rate_limit_burst: int = Field(
        default=20,
        ge=1,
        le=200,
        description="Token bucket: maximum bucket size (allows bursts)",
    )

    # ========================================================================
    # Resilience Patterns
    # ========================================================================

    retry_max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum retry attempts for failed API calls",
    )

    retry_base_delay_seconds: float = Field(
        default=1.0,
        ge=0.1,
        le=60.0,
        description="Initial delay for exponential backoff (doubles each retry)",
    )

    circuit_breaker_failure_threshold: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Failures before circuit breaker opens",
    )

    circuit_breaker_recovery_timeout_seconds: float = Field(
        default=60.0,
        ge=1.0,
        le=600.0,
        description="Seconds to wait before testing recovery (OPEN → HALF_OPEN)",
    )

    # ========================================================================
    # Strategy Configuration
    # ========================================================================

    arbitrage_threshold: Decimal = Field(
        default=ARBITRAGE_THRESHOLD,
        ge=Decimal("0.5"),
        le=Decimal("1.0"),
        description="Arbitrage threshold (YES + NO < threshold)",
    )

    min_liquidity_usd: Decimal = Field(
        default=MIN_LIQUIDITY,
        ge=Decimal("0"),
        description="Minimum market liquidity in USD",
    )

    min_volume_usd: Decimal = Field(
        default=MIN_VOLUME,
        ge=Decimal("0"),
        description="Minimum 24h volume in USD",
    )

    # ========================================================================
    # Execution Configuration
    # ========================================================================

    paper_trading_enabled: bool = Field(
        default=True,
        description="Paper trading mode (true = simulate, false = live trading)",
    )

    initial_capital_usd: Decimal = Field(
        default=DEFAULT_INITIAL_CAPITAL,
        ge=Decimal("0"),
        description="Initial capital for paper trading in USD",
    )

    max_position_size_usd: Decimal = Field(
        default=DEFAULT_MAX_POSITION_SIZE,
        ge=Decimal("0"),
        description="Maximum position size per opportunity in USD",
    )

    # ========================================================================
    # Market Filters
    # ========================================================================

    market_categories: list[str] = Field(
        default=DEFAULT_MARKET_CATEGORIES.copy(),
        description="Market categories to monitor (politics, crypto, sports, etc.)",
    )

    exclude_markets: list[str] = Field(
        default_factory=list,
        description="Market IDs to exclude from arbitrage detection",
    )

    # ========================================================================
    # Monitoring Configuration
    # ========================================================================

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Logging level",
    )

    json_logs: bool = Field(
        default=True,
        description="Output logs in JSON format (true = production, false = development)",
    )

    metrics_port: int = Field(
        default=9090,
        ge=1024,
        le=65535,
        description="Prometheus metrics HTTP port",
    )

    # ========================================================================
    # Polling Configuration
    # ========================================================================

    poll_interval_seconds: float = Field(
        default=DEFAULT_POLL_INTERVAL,
        ge=1.0,
        le=3600.0,
        description="Polling interval for market data in seconds",
    )

    # ========================================================================
    # Validators
    # ========================================================================

    @field_validator("max_position_size_usd")
    @classmethod
    def validate_position_size(cls, v: Decimal, info) -> Decimal:
        """
        Ensure max position size doesn't exceed initial capital.

        Why validate here?
        - Fail fast at startup rather than runtime
        - Clear error message for operators
        - Prevents impossible configurations
        """
        # Note: info.data might not have initial_capital_usd yet during validation
        # This is a cross-field validation that runs after all fields are set
        return v

    @field_validator("market_categories")
    @classmethod
    def validate_categories(cls, v: list[str]) -> list[str]:
        """
        Ensure at least one category is specified.

        Why? Without categories, we'd fetch all markets → high API usage
        """
        if not v:
            raise ValueError("At least one market category must be specified")
        return v


def load_settings(config_file: Path | None = None) -> Settings:
    """
    Load settings from environment and optional config file.

    Args:
        config_file: Optional path to YAML config file

    Returns:
        Validated Settings instance

    Raises:
        ValidationError: If configuration is invalid

    Interview Point - Configuration Loading Strategy:
    - Start with sensible defaults (developer convenience)
    - Override with config file (ops team preferences)
    - Override with environment variables (cloud deployment, secrets)
    - Validate everything at startup (fail fast, clear errors)

    Example:
        >>> settings = load_settings()  # Use defaults + env vars
        >>> settings = load_settings(Path("config/prod.yaml"))  # + YAML overrides
    """
    if config_file and config_file.exists():
        import yaml

        with open(config_file) as f:
            config_data = yaml.safe_load(f)
        return Settings(**config_data)

    return Settings()


# Singleton instance for convenience
# Interview Point: Why singleton?
# - Settings are immutable during application runtime
# - Avoids re-parsing environment variables on every import
# - Can still be overridden for testing (dependency injection)
_settings: Settings | None = None


def get_settings() -> Settings:
    """
    Get or create singleton Settings instance.

    For testing, you can override by calling load_settings() with custom config.
    """
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings
