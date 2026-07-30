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

1. **Arbitrage Detection Engine** -- a paper trading system that looks for Polymarket binary
   markets where YES + NO sums to less than $0.99, and simulates the trade.
2. **Research Pipeline** -- data collection and calibration analysis studying how well
   Polymarket prices predict outcomes, across 9,922 resolved markets.

- **Paper trading only** (no real money, no wallet, no order submission)
- **Boundary-applied resilience** (rate limiting, retry, circuit breaking on every request)
- **Clean architecture** (separation of concerns, dependency injection)
- **326 tests | 69% coverage | ruff and mypy clean**
- **Observability** (structured logging, Prometheus metrics, provisioned Grafana dashboard)
- **Falsification record** -- every research claim this project made was tested and retracted;
  see [docs/CASE_STUDY.md](docs/CASE_STUDY.md)

**This is NOT a production trading system.** Both headline results are negative, deliberately
so: the arbitrage strategy found no qualifying signal in the observed feed, and no positive
research claim survived review. The write-up is the deliverable.

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
4. **Hypothesis Validation**: Bootstrap CI testing, volume weighting, time-period splits, cross-category comparison
5. **Backtesting**: Strategy simulation with fee modeling, position sizing, and bootstrap confidence intervals

### Key Findings

**No positive research claim from this dataset currently meets the evidentiary standard applied
in the final review.** The findings below are stated as they resolved, not as they were first
reported. Full mechanisms and measurements: [docs/CASE_STUDY.md](docs/CASE_STUDY.md).

- **9,922 resolved markets** across 6 categories. Note the resolution window is narrow --
  `closed_at` spans roughly four weeks -- which constrains every analysis below.
- **Crypto overconfidence: rejected.** A +1% bias signal did not survive bootstrap CI (95% CI
  includes zero), volume weighting, or monthly splits. A small-sample artifact.
- **Weather mispricing: rejected as a calibration claim.** An apparent +17pp bias was traced to
  the analysis itself. Temperature markets are rungs of mutually exclusive ladders, and the
  `[0.05, 0.95]` price filter discarded the *winning* rung in 65.2% of reconstructed ladders.
  Removing the filter collapses the effect to +3.9pp, which incomplete ladder representation
  then accounts for numerically.
- **Politics underconfidence: not supported.** Originally reported as confirmed, with a
  contrarian YES strategy returning +20.5%. It fails on three grounds: 69% of the cohort is one
  narrow speech-event subtype rather than political forecasting questions; the price band was
  chosen after a wider band missed significance; and contracts share underlying events, so 323
  rows are not 323 independent observations. The +20.5% figure was also never a backtest -- its
  entry price was never demonstrated to be executable.
- **Retracted:** a previously reported 1h pre-resolution cohort of n=2,523 reproduces as n=18,
  and the original derivation cannot be reconstructed.

The exploratory dataset is frozen, content-hashed and write-protected rather than corrected in
place, so the analysis that produced the original claims remains inspectable. See
[research/archive/v1/](research/archive/v1/).

`research/ROADMAP.md` records the original methodology and conclusions as written at the time;
it has **not** been rewritten, and its claims should be read against the case study.

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

4. **Multi-Endpoint Fallback** -- *built, tested, and not wired in*
   - `api/endpoints.py` implements ordered fallback across API URL patterns
   - Nothing imports it outside its own tests: `main.py` hardcodes `/markets`
   - Listed here as an honest inventory item, not a runtime capability. It is left
     unreachable rather than wired up to justify the description

### Code Quality

- **Type Safety**: Full type hints, strict mypy validation
- **Immutability**: Frozen Pydantic models (thread-safe)
- **Decimal Math**: No float precision errors for financial calculations
- **SOLID Principles**: Dependency injection, single responsibility
- **Rich Domain Models**: Business logic in models, not services

### Observability

- **Structured Logging**: JSON logs with context binding (structlog), correlation ID per cycle
- **Prometheus Metrics**: business and latency metrics, served at `/metrics` and scraped
- **Grafana**: provisioned datasource and an 11-panel dashboard, checked into `monitoring/`
- **Performance Tracking**: capital, realized and unrealized P&L, cycle latency, breaker state

Scoped honestly: the Docker health check is an import smoke test rather than a liveness probe
of a running detection loop, and the monitoring stack is loopback-bound local development --
not a production observability setup with alerting or SLOs.

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

### Research
- **numpy**: Vectorized bootstrap CI, calibration analysis
- **matplotlib**: Calibration curve visualization
- **SQLite**: Research data storage (9,900+ markets)

### Development
- **uv**: Package management and builds
- **pytest**: Testing framework with async support
- **hypothesis**: Property-based testing
- **mypy**: Strict static type checking (near-strict, warn_unreachable)
- **ruff**: Linting and formatting
- **GitHub Actions**: CI pipeline (lint + test, Python 3.11/3.12/3.13 matrix)

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
# One-time: Grafana credentials are required. Compose refuses to start without them
# rather than falling back to admin/admin.
cp .env.example .env        # then edit GRAFANA_ADMIN_PASSWORD

# Build and start the stack (app + Prometheus + Grafana)
docker compose up -d --build

# View logs
docker compose logs -f arbitrage-detector

# Dashboards -- bound to loopback only, not reachable from the network
# - Grafana:    http://localhost:3000   (credentials from .env; dashboard under "Polymarket")
# - Prometheus: http://localhost:9091
# - Metrics:    http://localhost:9090/metrics

# Stop, keeping Grafana state and metrics history
docker compose down

# To rotate the Grafana password later, use its CLI -- editing .env alone has no effect
# once the volume exists, and `down -v` would delete your metrics history with it:
#   docker compose exec grafana \
#     grafana cli --homepath /usr/share/grafana admin reset-admin-password '<new>'
```

The Grafana datasource and an 11-panel dashboard are provisioned from `monitoring/grafana/`,
so they appear on first boot with no manual setup. Expect the opportunity and trade panels to
read zero -- see [Key Findings](#key-findings) for why.

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
│   │   ├── validate_crypto_signal.py # 5-test crypto bias validation suite
│   │   ├── backtest_politics.py    # Politics contrarian strategy backtest
│   │   ├── infer_categories.py     # Category inference
│   │   └── extract_preresolution_prices.py
│   └── ROADMAP.md                  # Research findings and next steps
│
├── tests/                          # Test suite (326 tests, 69% coverage)
│   ├── conftest.py                 # Shared fixtures
│   ├── unit/                       # Unit tests
│   │   ├── test_domain_models.py   # Token, Market, ArbitrageOpportunity (52 tests)
│   │   ├── test_parsers.py         # Multi-format response parsing (17 tests)
│   │   ├── test_strategies.py      # Opportunity detection, filtering (12 tests)
│   │   ├── test_paper_trader.py    # Trade execution, capital, positions (13 tests)
│   │   ├── test_resilience.py      # Circuit breaker, retry, rate limiter (38 tests)
│   │   ├── test_endpoints.py       # URL building, fallback strategies (34 tests)
│   │   ├── test_metrics.py         # Prometheus metrics recording (22 tests)
│   │   ├── test_settings.py        # Config loading, validation, priority (35 tests)
│   │   └── test_client.py          # HTTP client, error translation (31 tests)
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

### Test Coverage (326 tests, 69%)

- **Unit Tests**: domain models, parsers, strategies, execution and settlement, API client and
  its resilience boundary, composition-root wiring, metrics, settings, frozen-dataset guards
- **Integration Tests**: directory exists, no tests written
- **Property-Based Tests**: directory exists, no tests written (hypothesis is installed)

**Module coverage**: settings 100%, constants 100%, exceptions 93%, client 88%, models 83%,
paper_trader 77%, resilience 77%, position_tracker 72%, metrics 72%, response_models 72%,
endpoints 62%, parsers 59%, base 57%, main 56%, price_discrepancy 55%, logging 31%,
protocols 0%.

A caveat worth stating on a page that quotes a test count: at 254 passing tests this suite did
not catch four defects that left the engine unable to fetch a single market. Roughly 33 of the
326 exercise modules the running application never reaches. Tests here establish that code
satisfies the contracts it encodes -- not that the right contracts were encoded. See
[docs/CASE_STUDY.md](docs/CASE_STUDY.md).

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

## Open Assumptions

Assumptions the code depends on that have **not** been independently established.
Recorded here rather than left implicit, because this project's recurring failure mode
was a plausible-looking field name standing in for a fact nobody had verified.

**Gamma `umaResolutionStatus == "resolved"` is treated as settlement-eligible.**
Settlement releases capital and realizes P&L on that signal. It excludes the intermediate
`"proposed"` state, which is directionally safer than settling earlier in the oracle
lifecycle -- but the mapping from `"resolved"` to settlement eligibility has not been
independently demonstrated, so the mapping as a whole should not be called conservative.
Edge cases around disputed, void, or negative-risk market structures are uncharacterized.
If it is wrong in the early direction, the ledger would release capital before positions
were redeemable, inflating capacity for later trades. That is the same phantom-liquidity
class already eliminated from the market end date, now at a better-isolated boundary.

The assumption lives in exactly one place, `Application._fetch_resolution_status`.
Everything downstream consumes a typed `ResolutionStatus` and would be unaffected by
replacing it with a better-evidenced adapter. Validating it means one premise study
against known-resolved markets, not an accounting rewrite.

**Related scoping notes:**

| Claim | Status |
|---|---|
| Settlement logic does not infer resolution | True downstream of the adapter; the adapter contains one documented mapping assumption |
| Request throttling | Boundary-enforced token bucket. The limiter holds its lock across the wait, so callers sharing an instance serialize. Adequate for this workload; not a high-concurrency implementation |
| Rate-limit handling | 429 is retried with local exponential backoff. `Retry-After` is carried on the exception but not honoured |
| Gamma outcome prices | Measured to sum to exactly 1.0000 across 343 live markets. Not established to be mid-prices, and not executable ask prices |
| Paper-trade lifecycle | Implemented, tested, and wired into the detection cycle. Never exercised against live data, because no position opens on a feed whose prices sum to 1 |
| Position sizing units | The ledger uses explicit `bundle_quantity`, but `_calculate_position_size` still caps a bundle count with a dollar amount (`min(max_position_size, liquidity * 0.01)`). Numerically indistinguishable while a bundle costs ~$1; a correct fix sizes in capital and divides by bundle unit cost |
| `arbitrage_profit_per_dollar` naming | Same root cause. The metric and the `Market` property observe `1 - (yes + no)`, which is profit **per bundle**, not return on capital: at a 0.96 bundle cost that is 0.0400 per bundle versus a 4.17% return on cost. The Prometheus help text and the Grafana panel say so; the identifier is unchanged because renaming it touches 20 call sites across the domain model, strategy and executor, and that belongs in the sizing redesign rather than a monitoring commit |
| Monitoring posture | Loopback-bound, digest-pinned images, credentials from an uncommitted `.env`. That is a defensible **local development** posture, not secret management and not a production monitoring stack -- there is no alerting or SLO story |

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
