# Build stage: compile dependencies and assemble virtual environment using uv
FROM python:3.12-alpine AS builder

WORKDIR /build

# Copy uv binary from official distribution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Install binutils for stripping native shared libraries
RUN apk add --no-cache binutils

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# Create isolated virtualenv and install dependencies
COPY requirements.txt ./
RUN uv venv /app/.venv && \
    uv pip install --no-cache --python /app/.venv -r requirements.txt

# Prune virtual environment: remove tests, type stubs, documentation, and strip native .so binaries
RUN find /app/.venv -type d \( -name "tests" -o -name "test" -o -name "docs" \) -exec rm -rf {} + 2>/dev/null || true && \
    find /app/.venv -type f \( -name "*.pyi" -o -name "*.typed" \) -delete 2>/dev/null || true && \
    find /app/.venv -type f -name "*.so" -exec strip --strip-unneeded {} + 2>/dev/null || true

# Runtime stage: minimal Alpine footprint (<25MB compressed)
FROM python:3.12-alpine

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Copy virtual environment and application source
COPY --from=builder /app/.venv /app/.venv
COPY app.py healthcheck.py cloudflare.py models.py ./
COPY static ./static

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://127.0.0.1:8090/health || exit 1

CMD ["python", "app.py"]
