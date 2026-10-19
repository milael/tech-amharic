# syntax=docker/dockerfile:1
# Multi-stage build with uv: dependencies resolve from uv.lock in a builder
# image; the runtime image has only the virtualenv and the app, and runs as a
# non-root user.

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
# Dependencies first, so code edits don't invalidate this layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev --extra server
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra server

FROM python:3.13-slim-bookworm
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=builder --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
# Apply migrations, then serve. Behind a reverse proxy, keep --proxy-headers.
CMD ["sh", "-c", "alembic upgrade head && uvicorn tech_amharic.server.main:create_app --factory --host 0.0.0.0 --port 8000 --proxy-headers"]
