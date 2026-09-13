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
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=120 \
    UV_CONCURRENT_DOWNLOADS=4

# Prefer IPv4 for DNS resolution: some networks have a broken/throttled IPv6
# route to package CDNs (e.g. download.pytorch.org), which silently stalls
# large wheel downloads for minutes instead of failing fast.
RUN echo 'precedence ::ffff:0:0/96 100' >> /etc/gai.conf

# Copy dependency metadata first for better layer caching
COPY pyproject.toml uv.lock README.md ./

# Install dependencies without installing the project
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-editable

# Copy application source
COPY src ./src

# Install project (editable so the bind-mounted src/ in docker-compose
# dev is what actually gets imported, letting uvicorn --reload pick up
# live edits instead of reloading a stale copy baked into site-packages)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked


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