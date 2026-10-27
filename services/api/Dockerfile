# syntax=docker/dockerfile:1.7
# Callwright API image. One image, three roles (see docker/entrypoint.sh):
#   api      FastAPI on $PORT (default 8080)
#   worker   arq jobs worker plus a tiny health server on $PORT (Cloud Run needs a listener)
#   migrate  alembic upgrade head, then the agent templates sync; exits
# Pick the role with the ROLE env var or the first container argument.
#
# Build from the repository root (the API reads the voice worker's adapter catalog):
#   docker build -f services/api/Dockerfile -t callwright-api .

ARG PYTHON_IMAGE=python:3.12-slim

FROM ghcr.io/astral-sh/uv:0.7.12 AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /srv/services/api
COPY services/api/pyproject.toml services/api/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

FROM ${PYTHON_IMAGE} AS runtime
# 007: PyAV (recording decode for the long-silences check) and google-re2 (custom phrase
# patterns) install as manylinux wheels that bundle FFmpeg and RE2, so no system packages are needed.
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    ROLE=api
RUN groupadd --system --gid 10001 callwright \
    && useradd --system --uid 10001 --gid callwright --no-create-home --shell /usr/sbin/nologin callwright
COPY --from=build /opt/venv /opt/venv
WORKDIR /srv/services/api
COPY services/api/alembic.ini ./
COPY services/api/app ./app
# Settings.adapter_catalog_path resolves to ../voice-worker/worker/adapters/catalog.json.
COPY services/voice-worker/worker/adapters/catalog.json /srv/services/voice-worker/worker/adapters/catalog.json
COPY --chmod=0755 services/api/docker/entrypoint.sh /usr/local/bin/callwright-entrypoint
USER callwright:callwright
EXPOSE 8080
ENTRYPOINT ["callwright-entrypoint"]
