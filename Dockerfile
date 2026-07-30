# Multi-stage Dockerfile for production deployment
#
# Why multi-stage?
# - Smaller final image (no build tools)
# - Security: fewer attack vectors
# - Build cache: faster rebuilds

# Stage 1: Builder
FROM python:3.11-slim AS builder

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first (cache layer)
COPY pyproject.toml uv.lock ./

# Install production dependencies only
RUN uv sync --no-dev --frozen --no-install-project

# Copy source and install the project itself.
# README.md is required, not decorative: pyproject.toml declares `readme = "README.md"`,
# so the build backend opens it while building the project wheel. Omitting it fails the
# second `uv sync` with "failed to open file /app/README.md".
COPY src/ ./src/
COPY README.md ./
RUN uv sync --no-dev --frozen

# Stage 2: Runtime
FROM python:3.11-slim

# Create non-root user (never run containers as root)
RUN useradd -m -u 1000 arbitrage && \
    mkdir -p /app /app/logs && \
    chown -R arbitrage:arbitrage /app

WORKDIR /app
USER arbitrage

# Copy the virtual environment from builder
COPY --from=builder --chown=arbitrage:arbitrage /app/.venv /app/.venv

# Copy application code and config
COPY --chown=arbitrage:arbitrage src/ ./src/
COPY --chown=arbitrage:arbitrage config/ ./config/

# Environment variables
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ARBITRAGE_JSON_LOGS=true

# Expose metrics port
EXPOSE 9090

# Health check for container orchestration (Kubernetes liveness/readiness)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import polymarket_arbitrage; import sys; sys.exit(0)"

# Run application
CMD ["python", "-m", "polymarket_arbitrage.main"]
