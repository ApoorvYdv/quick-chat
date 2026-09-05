# syntax=docker/dockerfile:1

FROM python:3.14-slim AS builder

ARG PROJECT_HOME=/quick_chat_api
WORKDIR ${PROJECT_HOME}

# Dependencies required to build Python packages
RUN apt-get update && apt-get install --no-install-recommends -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.8.4 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Copy dependency metadata first for better layer caching
COPY pyproject.toml uv.lock README.md ./

# Install dependencies without installing the project
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-editable

# Copy application source
COPY src ./src

# Install project
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable


# --------------------------------------------------
# Runtime
# --------------------------------------------------

FROM python:3.14-slim AS api

ARG PROJECT_HOME=/quick_chat_api
WORKDIR ${PROJECT_HOME}

# Runtime PostgreSQL dependency
RUN apt-get update && apt-get install --no-install-recommends -y \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy uv
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv

# Copy virtual environment
COPY --from=builder ${PROJECT_HOME}/.venv ./.venv

# Copy application source
COPY --from=builder ${PROJECT_HOME}/src ./src

EXPOSE 8000

CMD ["uv", "run", "--", "uvicorn", "quick_chat_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]