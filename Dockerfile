# syntax=docker/dockerfile:1.7

# Shared base image pins for Python and the official uv binary image.
ARG PYTHON_IMAGE=python:3.14-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.1

# ------------------------------------------------------------------------------
# Stage: uv-binary
# Purpose: provide pinned uv/uvx binaries from the official Astral image.
# ------------------------------------------------------------------------------
FROM ${UV_IMAGE} AS uv-binary

# ------------------------------------------------------------------------------
# Stage: builder
# Purpose: create the application virtual environment in a cache-friendly way.
# ------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

# Copy uv from the pinned official image instead of installing it with pip.
COPY --from=uv-binary /uv /uvx /bin/

# Install third-party dependencies first so app code changes keep this layer cached.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --no-editable

# Copy the package source, then install the project itself into the virtualenv.
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ------------------------------------------------------------------------------
# Stage: runtime
# Purpose: ship only the built virtual environment and run as a non-root user.
# ------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}" \
    COPILOT_MODEL_PROVIDER_SERVER_HOST=0.0.0.0 \
    COPILOT_MODEL_PROVIDER_SERVER_PORT=8000 \
    COPILOT_MODEL_PROVIDER_RUNTIME_WORKING_DIRECTORY=/var/lib/copilot-model-provider

WORKDIR /app

# Create a dedicated runtime user and a writable working directory for session data.
RUN groupadd --system --gid 10001 copilot-model-provider \
    && useradd --system --uid 10001 --gid copilot-model-provider \
        --create-home --home-dir /home/copilot-model-provider \
        --shell /usr/sbin/nologin copilot-model-provider \
    && mkdir -p /var/lib/copilot-model-provider \
    && chown -R copilot-model-provider:copilot-model-provider /var/lib/copilot-model-provider

# Copy only the built environment into the runtime image.
COPY --from=builder --chown=copilot-model-provider:copilot-model-provider /app/.venv /app/.venv

USER copilot-model-provider

EXPOSE 8000

CMD ["copilot-model-provider"]
