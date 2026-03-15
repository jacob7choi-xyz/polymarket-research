# Contributing

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (package manager)

## Setup

```bash
# Clone and install
git clone https://github.com/jacob7choi-xyz/polymarket-research.git
cd polymarket-research
uv sync --group dev

# Install pre-commit hooks
uv run pre-commit install

# Verify everything works
uv run ruff check src/ tests/
uv run mypy src/ tests/
uv run pytest
```

## Development Workflow

1. Create a feature branch from `main`
2. Make changes
3. Run the full quality check before committing:

```bash
uv run ruff check src/ tests/    # lint
uv run ruff format src/ tests/   # format
uv run mypy src/ tests/          # type check
uv run pytest                    # test
```

4. Commit (pre-commit hooks run automatically)
5. Open a pull request against `main`

## Code Standards

### Type Safety

All code must pass `mypy --strict`-level checks (configured in `pyproject.toml`). Every function needs type annotations.

```python
# Good
def calculate_profit(price: Decimal, quantity: Decimal) -> Decimal:
    return price * quantity

# Bad - missing annotations
def calculate_profit(price, quantity):
    return price * quantity
```

### Financial Math

Always use `Decimal` for prices, amounts, and percentages. Never use `float` for money.

```python
from decimal import Decimal

# Good
price = Decimal("0.48")

# Bad - float precision errors
price = 0.48
```

### Domain Models

Domain models in `src/polymarket_arbitrage/domain/models.py` must be:
- **Frozen** (`frozen=True`) for thread safety and immutability
- **Validated** with Pydantic field validators for business rules
- **Self-contained** with computed properties for derived values

### Imports

- Use absolute imports (`from polymarket_arbitrage.domain.models import Market`) in tests and top-level scripts
- Use relative imports (`from ..domain.models import Market`) within the `polymarket_arbitrage` package
- Import sorting is enforced by ruff (isort-compatible)

### Error Handling

- Use the custom exception hierarchy in `domain/exceptions.py`
- Distinguish recoverable errors (retry) from non-recoverable (fail fast)
- Never catch bare `Exception` unless re-raising

## Project Layout

This project uses the **src layout** with `uv_build`:

```
src/
  polymarket_arbitrage/    # The installable package
    __init__.py
    main.py
    api/
    config/
    domain/
    execution/
    monitoring/
    strategies/
```

The package is installed in editable mode during development (`uv sync`), so `import polymarket_arbitrage` works from anywhere.

## Adding Dependencies

```bash
# Runtime dependency
uv pip install httpx

# Dev-only dependency (to a dependency group)
uv pip install pytest-timeout
```

After installing, add the dependency to `pyproject.toml` manually with a minimum version pin. Consider setting upper bounds for critical dependencies (e.g., `pydantic`, `httpx`) to avoid surprise breaking changes.

## Testing

### Conventions

- Test files: `test_<module>.py`
- Test classes: `Test<ClassName>`
- Test functions: `test_<behavior>`
- Use fixtures from `tests/conftest.py` for shared test data

### Markers

```bash
uv run pytest -m unit          # Unit tests only
uv run pytest -m integration   # Integration tests only
uv run pytest -m property      # Property-based tests only
```

### Coverage

Coverage runs automatically on every `pytest` invocation (configured in `pyproject.toml`). Reports are generated in:
- Terminal (missing lines)
- `htmlcov/` (browseable HTML)
- `coverage.xml` (CI integration)

## Pull Request Checklist

- [ ] All tests pass (`uv run pytest`)
- [ ] No linting errors (`uv run ruff check src/ tests/`)
- [ ] No type errors (`uv run mypy src/ tests/`)
- [ ] New code has test coverage
- [ ] No `float` used for financial values
- [ ] No bare `Exception` catches
- [ ] Commit messages are descriptive
