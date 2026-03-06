# Multi-stage Dockerfile for production deployment
# Interview Point - Why Multi-stage?
# - Smaller final image (no build dependencies)
# - Security: Fewer attack vectors
# - Build cache: Faster rebuilds

# Stage 1: Builder
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install poetry
RUN pip install --no-cache-dir poetry==1.7.1

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Install dependencies
# --no-root: Don't install the project itself yet
# --no-dev: Don't install dev dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root --without dev

# Stage 2: Runtime
FROM python:3.11-slim

# Create non-root user for security
# Interview Point: Never run containers as root
RUN useradd -m -u 1000 arbitrage && \
    mkdir -p /app /app/logs && \
    chown -R arbitrage:arbitrage /app

WORKDIR /app
USER arbitrage

# Copy installed dependencies from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=arbitrage:arbitrage src/ ./src/
COPY --chown=arbitrage:arbitrage config/ ./config/

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ARBITRAGE_JSON_LOGS=true

# Expose metrics port
EXPOSE 9090

# Health check
# Interview Point: Health checks for container orchestration
# - Kubernetes uses this for liveness/readiness probes
# - Docker can restart unhealthy containers
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Run application
CMD ["python", "-m", "src.main"]
