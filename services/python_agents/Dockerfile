# syntax=docker/dockerfile:1
# ============================================
# Production image for the Python engine (services/python_agents)
# ============================================
#
# Build: DOCKER_BUILDKIT=1 docker build -f services/python_agents/Dockerfile -t python-agents:latest .
# Run:   docker run --rm -e ANTHROPIC_API_KEY python-agents:latest
#
# Supply chain:
# - The base image and the uv binary are pinned by digest; Renovate or
#   Dependabot bump tag and digest together, and the image is rebuilt rather
#   than patched in place (a fixed runtime only helps once it is redeployed).
# - Dependencies come from uv.lock (`uv sync --frozen`), the exact resolution
#   CI tests, instead of `pip install .` resolving whatever PyPI serves at
#   build time. The dev extra (test and audit tools, ~90 packages) and the
#   tests are not in the image.
# - No secrets are baked in: the key arrives through the environment at run
#   time (.env.example). The root .dockerignore keeps .env* out of the context.
# - Runtime: slim base, tini as PID 1, non-root user, no build tools; the venv
#   has no pip (the base image's /usr/local pip stays, unused and root-owned).

# ============================================
# STAGE 1: Builder
# ============================================
FROM python:3.11-slim-bookworm@sha256:f06d01d4ba3f8ad5af45a3ec87df19c1d317d8e8961edc0fabda61811af6f7cf AS builder

# uv from its release image (digest pinned), the same version that produced
# uv.lock and that CI runs.
COPY --from=ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c /uv /uvx /usr/local/bin/

# The image's interpreter, never a download; bytecode compiled at install so
# the runtime stage starts fast without writing .pyc files.
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON=/usr/local/bin/python3.11 \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies first (cache hit on code-only changes): the lock, the project
# file and the README the build backend reads.
COPY services/python_agents/pyproject.toml services/python_agents/uv.lock services/python_agents/README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --extra database

# Then the package itself, installed (not editable) into the same venv.
COPY services/python_agents/src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable --extra database

# ============================================
# STAGE 2: Runtime
# ============================================
FROM python:3.11-slim-bookworm@sha256:f06d01d4ba3f8ad5af45a3ec87df19c1d317d8e8961edc0fabda61811af6f7cf AS runtime

LABEL org.opencontainers.image.source="https://github.com/Pkanna10/autonomous-ai-platform" \
      org.opencontainers.image.description="Python 3.11 LangGraph engine for the autonomous AI platform" \
      org.opencontainers.image.licenses="ISC"

# tini: PID 1 signal forwarding and zombie reaping for long engine runs.
RUN apt-get update && \
    apt-get install -y --no-install-recommends tini && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# PYTHONUNBUFFERED: logs survive a crash. PYTHONDONTWRITEBYTECODE is not set
# because the venv already carries compiled bytecode. TZ=UTC for log times.
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    TZ=UTC \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Non-root system user: no password, no home directory, no shell.
RUN groupadd -r appuser && \
    useradd -r -g appuser -s /usr/sbin/nologin appuser

# The venv (interpreter path identical in both stages) is the whole payload.
# Root-owned and world-readable: the runtime user cannot modify installed
# code (bytecode is already compiled, so nothing needs to write here).
COPY --from=builder /app/.venv /app/.venv

USER appuser

# The interpreter and the package import; a broken image restarts instead of
# sitting "healthy".
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=90s \
    CMD ["python", "-c", "import autonomous_ai_agents"]

ENTRYPOINT ["/usr/bin/tini", "--"]

# Default command. The CLI arrives in Step 4; until then override it with
# `docker run ... python -m <module>`.
CMD ["python", "-m", "autonomous_ai_agents.orchestrator"]
