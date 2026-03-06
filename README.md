# Polymarket Arbitrage Detector

> **Production-grade arbitrage detection system for Polymarket prediction markets**
>
> 

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Type checked: mypy](https://img.shields.io/badge/type%20checked-mypy-blue.svg)](http://mypy-lang.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 🎯 Project Goals

This is a **learning project** focused on demonstrating production-grade software engineering:

- ✅ **Paper trading only** (no real money)
- ✅ **Production patterns** (circuit breaker, retry, rate limiting)
- ✅ **Clean architecture** (separation of concerns, dependency injection)
- ✅ **Comprehensive testing** (unit, integration, property-based)
- ✅ **Full observability** (structured logging, Prometheus metrics)
- ✅ **Interview-ready** (inline comments explaining architectural decisions)

**This is NOT** a production trading system—it's a portfolio piece showcasing engineering excellence.

---

## 📚 Table of Contents

- [System Architecture](#-system-architecture)
- [Key Features](#-key-features)
- [Technology Stack](#-technology-stack)
- [Quick Start](#-quick-start)
- [Project Structure](#-project-structure)
- [Design Decisions](#-design-decisions)
- [Testing](#-testing)
- [Monitoring](#-monitoring)
- [Development](#-development)

---

## 🏗️ System Architecture

```
┌────────────────────────────────────────────────────────┐
│                 Main Orchestrator                       │
│  • Dependency injection (composition root)              │
│  • Lifecycle management (startup → run → shutdown)      │
│  • Detection cycles (fetch → detect → execute)          │
│  • Signal handling (graceful shutdown)                  │
└────────┬───────────────────────────────────────────────┘
         │
    ┌────┴─────────┬─────────────┬──────────────┐
    │              │             │              │
┌───▼──────┐  ┌───▼─────┐  ┌────▼──────┐  ┌───▼────────┐
│ API      │  │Strategy │  │ Execution  │  │ Monitoring │
│ Layer    │  │ Engine  │  │   Layer    │  │   Layer    │
│          │  │         │  │            │  │            │
│•HTTP/2   │  │•Detect  │  │•Paper Trade│  │•Prometheus │
│•Circuit  │  │•Filter  │  │•Track P&L  │  │•Structlog  │
│•Retry    │  │•Score   │  │•Capital    │  │•Health     │
│•Rate Lim │  │         │  │            │  │            │
└──────────┘  └─────────┘  └────────────┘  └────────────┘
```

### Core Arbitrage Logic

**Opportunity**: When YES price + NO price < $0.99

**Example**:
```python
YES token: $0.48 (48% implied probability)
NO token:  $0.48 (48% implied probability)
Total:     $0.96 < $0.99  ← Arbitrage exists!

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

## ✨ Key Features

### Production-Grade Patterns

1. **Circuit Breaker Pattern**
   - Prevents cascading failures when API degrades
   - States: CLOSED → OPEN → HALF_OPEN
   - Auto-recovery testing
   - See: `src/api/resilience.py`

2. **Exponential Backoff with Jitter**
   - Graceful retry strategy
   - Prevents thundering herd problem
   - AWS best practice implementation
   - See: `src/api/resilience.py`

3. **Token Bucket Rate Limiter**
   - Smooth traffic control (no boundary effects)
   - Sustainable rate + burst allowance
   - Industry standard (AWS, Stripe, GitHub use this)
   - See: `src/api/resilience.py`

4. **Multi-Endpoint Fallback**
   - Tries multiple API patterns
   - Graceful degradation
   - Mirrors real-world API integration
   - See: `src/api/endpoints.py`

### Code Quality

- **Type Safety**: Full type hints, mypy validation
- **Immutability**: Frozen Pydantic models (thread-safe)
- **Decimal Math**: No float precision errors for financial calculations
- **SOLID Principles**: Dependency injection, single responsibility
- **DRY**: No code duplication
- **Rich Domain Models**: Business logic in models, not services

### Observability

- **Structured Logging**: JSON logs with context binding (structlog)
- **Prometheus Metrics**: Golden signals + business metrics
- **Health Checks**: Kubernetes-ready liveness/readiness probes
- **Performance Tracking**: P&L, capital utilization, ROI

---

## 🛠️ Technology Stack

### Core
- **Python 3.11+**: Modern async/await, type hints
- **httpx**: Async HTTP client with HTTP/2, connection pooling
- **Pydantic**: Data validation, settings management
- **structlog**: Structured logging

### Monitoring
- **Prometheus**: Metrics collection
- **Grafana**: Dashboards and visualization

### Development
- **pytest**: Testing framework
- **hypothesis**: Property-based testing
- **mypy**: Static type checking
- **black**: Code formatting
- **ruff**: Fast linting

### Infrastructure
- **Docker**: Containerization
- **docker-compose**: Local orchestration

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (optional, for full stack)
- Poetry (for dependency management)

### Installation

```bash
# Clone repository
cd polymarket-arbitrage-detector

# Install dependencies
poetry install

# Copy environment template
cp .env.example .env

# Edit configuration
vim .env  # or use your preferred editor
```

### Running Locally

```bash
# Run with Python
poetry run python -m src.main

# Or activate virtual environment
poetry shell
python -m src.main
```

### Running with Docker

```bash
# Build and start entire stack (app + Prometheus + Grafana)
docker-compose up -d

# View logs
docker-compose logs -f arbitrage-detector

# Access dashboards
# - Grafana: http://localhost:3000 (admin/admin)
# - Prometheus: http://localhost:9091
# - Metrics: http://localhost:9090/metrics

# Stop stack
docker-compose down
```

### Running Tests

```bash
# Run all tests
poetry run pytest

# Run with coverage
poetry run pytest --cov=src --cov-report=html

# Run specific test file
poetry run pytest tests/unit/test_strategies.py

# Run with verbose output
poetry run pytest -v
```

---

## 📁 Project Structure

```
polymarket-arbitrage-detector/
├── src/
│   ├── api/                    # API client layer
│   │   ├── client.py           # Async HTTP client
│   │   ├── resilience.py       # Circuit breaker, retry, rate limiter
│   │   ├── endpoints.py        # Multi-endpoint fallback
│   │   ├── parsers.py          # Flexible response parsing
│   │   └── response_models.py  # Pydantic API models
│   │
│   ├── config/                 # Configuration
│   │   ├── settings.py         # Pydantic BaseSettings
│   │   └── constants.py        # Domain constants
│   │
│   ├── domain/                 # Domain layer
│   │   ├── models.py           # Rich domain models
│   │   ├── exceptions.py       # Custom exceptions
│   │   └── protocols.py        # Interface definitions (PEP 544)
│   │
│   ├── strategies/             # Arbitrage strategies
│   │   ├── base.py             # Base strategy with shared logic
│   │   └── price_discrepancy.py # YES+NO < 0.99 detector
│   │
│   ├── execution/              # Trade execution
│   │   ├── paper_trader.py     # Paper trading executor
│   │   └── position_tracker.py # Position & P&L tracking
│   │
│   ├── monitoring/             # Observability
│   │   ├── logging.py          # Structured logging (structlog)
│   │   └── metrics.py          # Prometheus metrics
│   │
│   └── main.py                 # Main orchestrator
│
├── tests/                      # Test suite
│   ├── conftest.py             # Shared fixtures
│   ├── unit/                   # Unit tests
│   │   ├── test_domain_models.py
│   │   ├── test_parsers.py
│   │   ├── test_strategies.py
│   │   └── test_paper_trader.py
│   ├── integration/            # Integration tests
│   └── property/               # Property-based tests
│
├── config/                     # Configuration files
│   ├── config.yaml             # Default configuration
│   └── config.dev.yaml         # Development overrides
│
├── monitoring/                 # Monitoring configuration
│   └── prometheus.yml          # Prometheus config
│
├── Dockerfile                  # Multi-stage production build
├── docker-compose.yml          # Local development stack
├── pyproject.toml              # Dependencies & tool config
└── README.md                   # This file
```

---

## 🧠 Design Decisions

### Architecture Patterns

#### 1. **Protocols vs Abstract Base Classes**

**Decision**: Use `typing.Protocol` (PEP 544) for interfaces

**Why?**
- Duck typing: No inheritance required
- Easier mocking in tests
- Pythonic approach to SOLID principles
- Gradual typing without refactoring

**When to use ABC?**
- When you have shared implementation to inherit
- Example: `ArbitrageStrategy` base class has common filtering logic

**Code**: See `src/domain/protocols.py`

---

#### 2. **Separate API Models from Domain Models**

**Decision**: `api/response_models.py` vs `domain/models.py`

**Why?**
- **Decoupling**: API changes don't break domain logic
- **Multiple sources**: Can integrate multiple APIs → single domain model
- **Validation layers**:
  - API models: Validate structure (Pydantic)
  - Domain models: Validate business rules

**Example**:
- API returns `tokenId` (camelCase) or `token_id` (snake_case)
- Domain model uses consistent `token_id`

**Code**: Compare `src/api/response_models.py` and `src/domain/models.py`

---

#### 3. **Decimal for Financial Math**

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

**In arbitrage**: 0.001 difference = profit or loss
**Regulatory**: Financial systems require exact decimal arithmetic

**Code**: All domain models use `Decimal`

---

#### 4. **Frozen Pydantic Models**

**Decision**: All domain models have `frozen=True`

**Why?**
- **Thread safety**: Can share across async coroutines safely
- **Immutability**: Prevents accidental mutation bugs
- **Hashable**: Can use as dict keys or in sets
- **Functional programming**: Easier to reason about (no side effects)

**Code**: See `src/domain/models.py`

---

#### 5. **Dependency Injection (Composition Root)**

**Decision**: Build entire dependency graph in `main.py`

**Why?**
- **Testability**: Easy to inject mocks
- **Flexibility**: Swap implementations (paper trader → live trader)
- **No hidden dependencies**: All dependencies explicit
- **SOLID**: Dependency Inversion Principle

**Pattern**: Manual DI (no framework), simple and explicit

**Code**: See `src/main.py` `Application.__init__()`

---

### Resilience Patterns

#### 1. **Circuit Breaker**

**Problem**: API degraded → all requests fail → queue builds up → memory exhaustion

**Solution**: Circuit breaker pattern
- After N failures → OPEN (reject requests immediately)
- After timeout → HALF_OPEN (test recovery)
- On success → CLOSED (resume normal operation)

**Alternative Considered**: Simple retry with backoff
**Rejected**: Doesn't prevent request buildup during prolonged outages

**Code**: `src/api/resilience.py` `CircuitBreaker`

---

#### 2. **Exponential Backoff with Jitter**

**Problem**: 1000 clients hit rate limit → all retry at same time → still rate limited!

**Solution**: Exponential backoff + jitter
- Delay: `base * (2 ^ attempt) * random(0.5, 1.5)`
- Spreads retries out over time
- AWS best practice (full jitter)

**Code**: `src/api/resilience.py` `retry_with_backoff()`

---

#### 3. **Token Bucket Rate Limiting**

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

**Code**: `src/api/resilience.py` `RateLimiter`

---

## 🧪 Testing

### Test Coverage

- **Unit Tests**: Domain models, parsers, strategies, execution
- **Integration Tests**: End-to-end with mocked API (future)
- **Property-Based Tests**: Hypothesis for invariants (future)

### Running Tests

```bash
# All tests
pytest

# Specific module
pytest tests/unit/test_strategies.py

# With coverage
pytest --cov=src --cov-report=html
open htmlcov/index.html

# Verbose
pytest -v

# Stop on first failure
pytest -x
```

### Test Philosophy

**What to Test**:
- ✅ Business logic (arbitrage detection, profit calculation)
- ✅ Edge cases (boundary values, empty lists)
- ✅ Error handling (invalid data, API failures)
- ✅ Immutability (can't modify frozen models)

**What NOT to Test**:
- ❌ Third-party libraries (httpx, Pydantic)
- ❌ Simple getters/setters
- ❌ Configuration loading (too simple)

**Code**: See `tests/` directory

---

## 📊 Monitoring

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

**Format**: JSON (machine-parseable)

**Example Log**:
```json
{
  "event": "arbitrage_detected",
  "timestamp": "2025-01-15T10:30:00.123456Z",
  "level": "info",
  "app_name": "polymarket-arbitrage-detector",
  "market_id": "0x123abc",
  "question": "Will Bitcoin reach $100k?",
  "yes_price": 0.48,
  "no_price": 0.48,
  "expected_profit": 0.04,
  "cycle_id": "uuid-1234"
}
```

**Benefits**:
- Easy to parse (Splunk, Datadog, Elasticsearch)
- Queryable (WHERE event="arbitrage_detected" AND profit > 0.05)
- Context binding (request_id in all logs for tracing)

---

## 🔧 Development

### Setup Development Environment

```bash
# Install dev dependencies
poetry install

# Install pre-commit hooks
poetry run pre-commit install

# Run linting
poetry run ruff check src/
poetry run black --check src/

# Run type checking
poetry run mypy src/
```

### Code Quality Tools

- **black**: Code formatting (line length 100)
- **ruff**: Fast linting (replaces flake8, isort, etc.)
- **mypy**: Static type checking
- **pytest**: Testing framework

### Pre-commit Hooks

Automatically runs before each commit:
- black (formatting)
- ruff (linting)
- mypy (type checking)
- trailing whitespace removal

---

## 🎓 Interview Talking Points

### For AI/ML Roles

1. **Production ML Systems**
   - This demonstrates production patterns applicable to ML deployment
   - Observability, resilience, graceful degradation
   - Real-time decision making (detection → execution)

2. **Distributed Systems**
   - Circuit breaker, retry, rate limiting
   - Multi-endpoint fallback
   - Graceful shutdown, signal handling

3. **Software Engineering Best Practices**
   - Clean architecture, SOLID principles
   - Comprehensive testing
   - Type safety, immutability
   - Structured logging, metrics

4. **Financial Domain Knowledge**
   - Arbitrage detection logic
   - Risk management (position sizing)
   - P&L tracking

### Key Strengths

- ✅ **Production-ready code** (not toy example)
- ✅ **Inline comments** explaining architectural decisions
- ✅ **Comprehensive testing** (not just happy path)
- ✅ **Real-world patterns** (circuit breaker, exponential backoff)
- ✅ **Observable** (metrics, structured logging)
- ✅ **Containerized** (Docker, docker-compose)

---

## 📄 License

MIT License - see LICENSE file for details

---

## 🙏 Acknowledgments

This project demonstrates production-grade patterns learned from:
- Google SRE Book (Golden Signals, error budgets)
- AWS Best Practices (exponential backoff with jitter)
- Domain-Driven Design (rich domain models)
- Clean Architecture (separation of concerns)

Built for learning and portfolio purposes—not actual trading.

---

## 📞 Contact

**Author**: Jacob J. Choi
**LinkedIn**: https://www.linkedin.com/in/jacobjchoi/
**GitHub**: https://github.com/jacob7choi-xyz
**Portfolio**: https://jacobjchoi.xyz/

**Purpose**: For general curiosity and to learn.

---

*This is a paper trading system for educational purposes. No real money is used.*
