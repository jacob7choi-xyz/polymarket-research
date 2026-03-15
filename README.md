# Polymarket Research

> **Arbitrage detection and probability calibration research for Polymarket prediction markets**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Linting: ruff](https://img.shields.io/badge/linting-ruff-261230.svg)](https://github.com/astral-sh/ruff)
[![Type checked: mypy](https://img.shields.io/badge/type%20checked-mypy-blue.svg)](http://mypy-lang.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![codecov](https://codecov.io/gh/jacob7choi-xyz/polymarket-research/branch/main/graph/badge.svg)](https://codecov.io/gh/jacob7choi-xyz/polymarket-research)

---

## Project Goals

This is a **learning and portfolio project** with two components:

1. **Arbitrage Detection Engine** -- a production-grade paper trading system that detects when YES + NO prices sum to less than $0.99 on Polymarket binary markets, simulating trades via a paper trading engine.
2. **Research Pipeline** -- data collection and calibration analysis studying how well Polymarket prices predict actual outcomes, with 9,900+ resolved markets analyzed.

- **Paper trading only** (no real money)
- **Production patterns** (circuit breaker, retry, rate limiting)
- **Clean architecture** (separation of concerns, dependency injection)
- **Comprehensive testing** (unit, integration, property-based)
- **Full observability** (structured logging, Prometheus metrics)
- **Calibration research** (probability accuracy, category-level bias analysis)

**This is NOT a production trading system.**

---

## Table of Contents

- [System Architecture](#system-architecture)
- [Research Pipeline](#research-pipeline)
- [Key Features](#key-features)
- [Technology Stack](#technology-stack)
- [Quick Start](#quick-start)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Design Decisions](#design-decisions)
- [Testing](#testing)
- [Monitoring](#monitoring)
- [Development](#development)
- [Contributing](#contributing)

---

## System Architecture

```
┌────────────────────────────────────────────────────────┐
│                 Main Orchestrator                       │
│  - Dependency injection (composition root)              │
│  - Lifecycle management (startup -> run -> shutdown)    │
│  - Detection cycles (fetch -> detect -> execute)        │
│  - Signal handling (graceful shutdown)                  │
└────────┬───────────────────────────────────────────────┘
         │
    ┌────┴─────────┬─────────────┬──────────────┐
    │              │             │              │
┌───▼──────┐  ┌───▼─────┐  ┌────▼──────┐  ┌───▼────────┐
│ API      │  │Strategy │  │ Execution  │  │ Monitoring │
│ Layer    │  │ Engine  │  │   Layer    │  │   Layer    │
│          │  │         │  │            │  │            │
│ HTTP/2   │  │ Detect  │  │ Paper Trade│  │ Prometheus │
│ Circuit  │  │ Filter  │  │ Track P&L  │  │ Structlog  │
│ Retry    │  │ Score   │  │ Capital    │  │ Health     │
│ Rate Lim │  │         │  │            │  │            │
└──────────┘  └─────────┘  └────────────┘  └────────────┘
```

### Core Arbitrage Logic

**Opportunity**: When YES price + NO price < $0.99

**Example**:
```
YES token: $0.48 (48% implied probability)
NO token:  $0.48 (48% implied probability)
Total:     $0.96 < $0.99  <- Arbitrage exists!

Buy both outcomes:
- Cost: $0.96
- Guaranteed payout: $1.00 (one outcome will win)
- Profit: $0.04 (4% ROI)
```

**Why < $0.99 not < $1.00?**
- Transaction fees (~2%)
- Slippage (prices move during execution)
- Safety buffer

---

## Research Pipeline

The research pipeline collects resolved market data and analyzes how well Polymarket prices predict actual outcomes.

### Data Flow

```
Gamma API -> fetch_markets.py -> SQLite -> fetch_prices.py -> SQLite -> calibration.py -> plots
```

1. **Data Collection**: Fetches resolved binary markets from the Gamma API with resumable checkpointing
2. **Price Histories**: Pulls CLOB price snapshots at multiple time horizons (24h, 6h, 1h before resolution)
3. **Calibration Analysis**: Compares predicted probabilities against actual resolution rates

### Key Findings

- **9,900+ resolved markets** analyzed
- **Overall calibration**: Markets are well-calibrated, especially 1h before resolution
- **Crypto markets**: Systematic overconfidence -- bulls consistently price YES too high
- **Sports markets**: Well-calibrated across the full probability range
- **Dataset skew**: ~95% of markets resolve near certainty; only ~50 genuinely uncertain markets

See `research/ROADMAP.md` for detailed findings and next steps.

---

## Key Features

### Production-Grade Patterns

1. **Circuit Breaker Pattern**
   - Prevents cascading failures when API degrades
   - States: CLOSED -> OPEN -> HALF_OPEN
   - Auto-recovery testing
   - See: `src/polymarket_arbitrage/api/resilience.py`

2. **Exponential Backoff with Jitter**
   - Graceful retry strategy
   - Prevents thundering herd problem
   - AWS best practice implementation
   - See: `src/polymarket_arbitrage/api/resilience.py`

3. **Token Bucket Rate Limiter**
   - Smooth traffic control (no boundary effects)
   - Sustainable rate + burst allowance
   - Industry standard (AWS, Stripe, GitHub use this)
   - See: `src/polymarket_arbitrage/api/resilience.py`

4. **Multi-Endpoint Fallback**
   - Tries multiple API patterns
   - Graceful degradation
   - Mirrors real-world API integration
   - See: `src/polymarket_arbitrage/api/endpoints.py`

### Code Quality

- **Type Safety**: Full type hints, strict mypy validation
- **Immutability**: Frozen Pydantic models (thread-safe)
- **Decimal Math**: No float precision errors for financial calculations
- **SOLID Principles**: Dependency injection, single responsibility
- **Rich Domain Models**: Business logic in models, not services

### Observability

- **Structured Logging**: JSON logs with context binding (structlog)
- **Prometheus Metrics**: Golden signals + business metrics
- **Health Checks**: Kubernetes-ready liveness/readiness probes
- **Performance Tracking**: P&L, capital utilization, ROI

---

## Technology Stack

### Core
- **Python 3.11+**: Modern async/await, type hints
- **httpx**: Async HTTP client with HTTP/2, connection pooling
- **Pydantic v2**: Data validation, settings management
- **structlog**: Structured logging

### Monitoring
- **Prometheus**: Metrics collection
- **Grafana**: Dashboards and visualization

### Development
- **uv**: Package management and builds
- **pytest**: Testing framework with async support
- **hypothesis**: Property-based testing
- **mypy**: Strict static type checking
- **ruff**: Linting and formatting

### Infrastructure
- **Docker**: Multi-stage production build
- **docker-compose**: Local orchestration (app + Prometheus + Grafana)

---

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (package manager)
- Docker & Docker Compose (optional, for full stack)

### Installation

```bash
# Clone repository
git clone https://github.com/jacob7choi-xyz/polymarket-research.git
cd polymarket-research

# Install all dependencies (including dev)
uv sync --group dev

# Copy environment template
cp .env.example .env
```

### Running Locally

```bash
# Run the detector
uv run python -m polymarket_arbitrage.main

# Or activate the virtual environment first
source .venv/bin/activate
python -m polymarket_arbitrage.main
```

### Running with Docker

```bash
# Build and start entire stack (app + Prometheus + Grafana)
docker compose up -d

# View logs
docker compose logs -f arbitrage-detector

# Access dashboards
# - Grafana: http://localhost:3000 (admin/admin)
# - Prometheus: http://localhost:9091
# - Metrics: http://localhost:9090/metrics

# Stop stack
docker compose down
```

### Running Tests

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/unit/test_strategies.py

# Run with verbose output
uv run pytest -v

# Stop on first failure
uv run pytest -x
```

---

## Project Structure

```
polymarket-research/
├── src/
│   └── polymarket_arbitrage/       # Arbitrage detection engine
│       ├── __init__.py
│       ├── main.py                 # Orchestrator & composition root
│       ├── api/                    # API client layer
│       │   ├── client.py           # Async HTTP client (httpx)
│       │   ├── resilience.py       # Circuit breaker, retry, rate limiter
│       │   ├── endpoints.py        # Multi-endpoint fallback
│       │   ├── parsers.py          # Flexible response parsing
│       │   └── response_models.py  # Pydantic API response models
│       ├── config/                 # Configuration
│       │   ├── settings.py         # Pydantic BaseSettings
│       │   └── constants.py        # Domain constants
│       ├── domain/                 # Domain layer (no external deps)
│       │   ├── models.py           # Rich domain models (frozen)
│       │   ├── exceptions.py       # Custom exception hierarchy
│       │   └── protocols.py        # Interface definitions (PEP 544)
│       ├── strategies/             # Arbitrage detection strategies
│       │   ├── base.py             # Base strategy with shared logic
│       │   └── price_discrepancy.py # YES+NO < 0.99 detector
│       ├── execution/              # Trade execution
│       │   ├── paper_trader.py     # Paper trading executor
│       │   └── position_tracker.py # Position & P&L tracking
│       └── monitoring/             # Observability
│           ├── logging.py          # Structured logging (structlog)
│           └── metrics.py          # Prometheus metrics
│
├── research/                       # Research pipeline (separate system)
│   ├── pipeline/                   # Data collection
│   │   ├── fetch_markets.py        # Fetch resolved markets from Gamma API
│   │   ├── fetch_prices.py         # Fetch CLOB price histories
│   │   ├── checkpoint.py           # Resumable checkpoint system
│   │   └── storage.py              # SQLite schema and helpers
│   ├── analysis/                   # Data analysis
│   │   ├── calibration.py          # Calibration curve analysis
│   │   ├── infer_categories.py     # Category inference
│   │   └── extract_preresolution_prices.py
│   └── ROADMAP.md                  # Research findings and next steps
│
├── tests/                          # Test suite
│   ├── conftest.py                 # Shared fixtures
│   ├── unit/                       # Unit tests
│   │   ├── test_domain_models.py
│   │   ├── test_parsers.py
│   │   ├── test_strategies.py
│   │   └── test_paper_trader.py
│   ├── integration/                # Integration tests (future)
│   └── property/                   # Property-based tests (future)
│
├── config/                         # Runtime configuration files
│   ├── config.yaml                 # Default configuration
│   └── config.dev.yaml             # Development overrides
│
├── monitoring/                     # Monitoring configuration
│   └── prometheus.yml              # Prometheus scrape config
│
├── .env.example                    # Environment variable template
├── .pre-commit-config.yaml         # Pre-commit hook config
├── Dockerfile                      # Multi-stage production build
├── docker-compose.yml              # Local development stack
├── pyproject.toml                  # Dependencies, build, & tool config
└── uv.lock                        # Locked dependency versions
```

---

## Configuration

The system uses a layered configuration approach:

1. **Defaults** in `config/constants.py` and Pydantic field defaults
2. **YAML files** in `config/` for structured settings
3. **Environment variables** (highest priority) for deployment overrides

### Environment Variables

All environment variables are prefixed with `ARBITRAGE_`. See `.env.example` for the complete list.

| Variable | Default | Description |
|---|---|---|
| `ARBITRAGE_POLYMARKET_API_URL` | `https://gamma-api.polymarket.com` | API base URL |
| `ARBITRAGE_ARBITRAGE_THRESHOLD` | `0.99` | Max YES+NO sum to trigger |
| `ARBITRAGE_MIN_LIQUIDITY_USD` | `1000` | Minimum market liquidity |
| `ARBITRAGE_INITIAL_CAPITAL_USD` | `10000` | Starting paper capital |
| `ARBITRAGE_MAX_POSITION_SIZE_USD` | `100` | Max single position size |
| `ARBITRAGE_LOG_LEVEL` | `INFO` | Log verbosity |
| `ARBITRAGE_JSON_LOGS` | `true` | JSON output (prod) vs console (dev) |
| `ARBITRAGE_POLL_INTERVAL_SECONDS` | `60` | Market data polling interval |

---

## Design Decisions

### Architecture Patterns

#### 1. Protocols vs Abstract Base Classes

**Decision**: Use `typing.Protocol` (PEP 544) for interfaces

**Why?**
- Duck typing: No inheritance required
- Easier mocking in tests
- Pythonic approach to SOLID principles
- Gradual typing without refactoring

**When to use ABC?**
- When you have shared implementation to inherit
- Example: `ArbitrageStrategy` base class has common filtering logic

**Code**: See `src/polymarket_arbitrage/domain/protocols.py`

#### 2. Separate API Models from Domain Models

**Decision**: `api/response_models.py` vs `domain/models.py`

**Why?**
- **Decoupling**: API changes don't break domain logic
- **Multiple sources**: Can integrate multiple APIs into a single domain model
- **Validation layers**:
  - API models: Validate structure (Pydantic)
  - Domain models: Validate business rules

**Example**:
- API returns `tokenId` (camelCase) or `token_id` (snake_case)
- Domain model uses consistent `token_id`

#### 3. Decimal for Financial Math

**Decision**: Use `Decimal` for all prices and money

**Why?**
```python
# Float has precision errors
>>> float(0.1) + float(0.2)
0.30000000000000004  # NOT 0.3!

# Decimal is exact
>>> Decimal("0.1") + Decimal("0.2")
Decimal("0.3")  # Correct!
```

In arbitrage, 0.001 difference = profit or loss. Financial systems require exact decimal arithmetic.

#### 4. Frozen Pydantic Models

**Decision**: All domain models have `frozen=True`

**Why?**
- **Thread safety**: Can share across async coroutines safely
- **Immutability**: Prevents accidental mutation bugs
- **Hashable**: Can use as dict keys or in sets
- **Functional programming**: Easier to reason about (no side effects)

#### 5. Dependency Injection (Composition Root)

**Decision**: Build entire dependency graph in `main.py`

**Why?**
- **Testability**: Easy to inject mocks
- **Flexibility**: Swap implementations (paper trader -> live trader)
- **No hidden dependencies**: All dependencies explicit
- **SOLID**: Dependency Inversion Principle

Pattern: Manual DI (no framework), simple and explicit.

---

### Resilience Patterns

#### Circuit Breaker

**Problem**: API degraded -> all requests fail -> queue builds up -> memory exhaustion

**Solution**: Circuit breaker pattern
- After N failures -> OPEN (reject requests immediately)
- After timeout -> HALF_OPEN (test recovery)
- On success -> CLOSED (resume normal operation)

**Alternative Considered**: Simple retry with backoff
**Rejected**: Doesn't prevent request buildup during prolonged outages

**Code**: `src/polymarket_arbitrage/api/resilience.py`

#### Exponential Backoff with Jitter

**Problem**: 1000 clients hit rate limit -> all retry at same time -> still rate limited

**Solution**: Exponential backoff + jitter
- Delay: `base * (2 ^ attempt) * random(0.5, 1.5)`
- Spreads retries out over time
- AWS best practice (full jitter)

#### Token Bucket Rate Limiting

**Problem**: Fixed window rate limiting has boundary effects
```
Fixed window (60 req/min):
- 59 requests at 12:00:59
- 60 requests at 12:01:00
= 119 requests in 1 second!
```

**Solution**: Token bucket algorithm
- Bucket refills at constant rate
- Allows bursts up to bucket size
- No boundary effects
- Industry standard (AWS, Stripe, GitHub)

---

## Testing

### Test Coverage

- **Unit Tests**: Domain models, parsers, strategies, execution
- **Integration Tests**: End-to-end with mocked API (future)
- **Property-Based Tests**: Hypothesis for invariants (future)

### Running Tests

```bash
# All tests with coverage
uv run pytest

# Specific module
uv run pytest tests/unit/test_strategies.py

# Verbose output
uv run pytest -v

# Stop on first failure
uv run pytest -x

# Open coverage report
open htmlcov/index.html
```

Coverage is configured in `pyproject.toml` and runs automatically with every `pytest` invocation, reporting to terminal, HTML, and XML.

### Test Philosophy

**What to Test**:
- Business logic (arbitrage detection, profit calculation)
- Edge cases (boundary values, empty lists)
- Error handling (invalid data, API failures)
- Immutability (can't modify frozen models)

**What NOT to Test**:
- Third-party libraries (httpx, Pydantic)
- Simple getters/setters
- Configuration loading (too simple)

---

## Monitoring

### Prometheus Metrics

#### Golden Signals (Google SRE)

1. **Latency**: `polymarket_api_latency_seconds`
2. **Traffic**: `polymarket_api_requests_total`
3. **Errors**: `polymarket_api_requests_total{status_code=5xx}`
4. **Saturation**: `available_capital_usd`, `open_positions`

#### Business Metrics

- `arbitrage_opportunities_detected_total`
- `trades_executed_total{status=success|failure}`
- `arbitrage_profit_per_dollar` (histogram)

#### Example Queries (PromQL)

```promql
# Request rate (per second)
rate(polymarket_api_requests_total[5m])

# 95th percentile latency
histogram_quantile(0.95, rate(polymarket_api_latency_seconds_bucket[5m]))

# Arbitrage opportunity rate
rate(arbitrage_opportunities_detected_total[1h])

# Capital utilization %
(capital_deployed_usd / (capital_deployed_usd + available_capital_usd)) * 100
```

### Structured Logging

**Format**: JSON (machine-parseable in production)

```json
{
  "event": "arbitrage_detected",
  "timestamp": "2025-01-15T10:30:00.123456Z",
  "level": "info",
  "app_name": "polymarket-research",
  "market_id": "0x123abc",
  "question": "Will Bitcoin reach $100k?",
  "yes_price": 0.48,
  "no_price": 0.48,
  "expected_profit": 0.04,
  "cycle_id": "uuid-1234"
}
```

Set `ARBITRAGE_JSON_LOGS=false` for human-readable console output during development.

---

## Development

### Setup

```bash
# Install all dependencies
uv sync --group dev

# Install pre-commit hooks
uv run pre-commit install
```

### Code Quality

```bash
# Lint
uv run ruff check src/ tests/

# Format
uv run ruff format src/ tests/

# Type check
uv run mypy src/ tests/

# Run everything (lint + type check + tests)
uv run ruff check src/ tests/ && uv run mypy src/ tests/ && uv run pytest
```

### Pre-commit Hooks

Automatically run before each commit:
- Trailing whitespace removal
- End-of-file fixer
- YAML validation
- Ruff (lint + format)
- mypy (type checking)

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow, code standards, and pull request guidelines.

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Acknowledgments

This project demonstrates production-grade patterns learned from:
- Google SRE Book (Golden Signals, error budgets)
- AWS Best Practices (exponential backoff with jitter)
- Domain-Driven Design (rich domain models)
- Clean Architecture (separation of concerns)

Built for learning and portfolio purposes -- not actual trading.

---

## Contact

**Author**: Jacob J. Choi
**LinkedIn**: https://www.linkedin.com/in/jacobjchoi/
**GitHub**: https://github.com/jacob7choi-xyz
**Portfolio**: https://jacobjchoi.xyz/

*This is a paper trading system for educational purposes. No real money is used.*
