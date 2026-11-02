# syntax=docker/dockerfile:1.7
# Callwright voice worker image. One image, two process roles chosen by WORKER_ROLE:
#   live    (default) LiveKit Agents worker, service `voice` in deploy/vm/docker-compose.yml;
#   textsim 008 text simulations, an arq consumer of queue arq:textsim (service `textsim`).
# Both start through the same ENTRYPOINT (python -m worker.entry); textsim ignores the CMD.
#
# Build from the repository root (the root .dockerignore keeps the context small):
#   docker build -f services/voice-worker/Dockerfile -t callwright-voice-worker .
#
# Plugin model files (the turn detector's ONNX models from Hugging Face; Silero VAD ships inside
# its wheel) are downloaded at build time into HF_HOME, and the runtime runs with
# HF_HUB_OFFLINE=1, so a call never waits on a download.
# Health: the agent server (or the textsim listener) answers on WORKER_HEALTH_PORT (8190).

ARG PYTHON_IMAGE=python:3.12-slim

FROM ghcr.io/astral-sh/uv:0.7.12 AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /srv/services/voice-worker
COPY services/voice-worker/pyproject.toml services/voice-worker/uv.lock ./
# The project itself is not installed (its wheel would also package tests/); the code runs from
# /srv/services/voice-worker on PYTHONPATH.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

FROM build AS models
ENV PATH=/opt/venv/bin:$PATH \
    HF_HOME=/opt/hf
# Imports every installed livekit plugin and runs its download step (turn detector models).
# The second pass runs offline and fails the build if anything is missing from the cache.
RUN python -m livekit.agents download-files \
    && HF_HUB_OFFLINE=1 python -m livekit.agents download-files

FROM ${PYTHON_IMAGE} AS runtime
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/srv/services/voice-worker \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1 \
    WORKER_ROLE=live \
    WORKER_HEALTH_PORT=8190
RUN groupadd --system --gid 10001 callwright \
    && useradd --system --uid 10001 --gid callwright --create-home --home-dir /home/callwright \
       --shell /usr/sbin/nologin callwright
COPY --from=build /opt/venv /opt/venv
COPY --from=models /opt/hf /opt/hf
WORKDIR /srv/services/voice-worker
COPY services/voice-worker/pyproject.toml ./
COPY services/voice-worker/worker ./worker
USER callwright:callwright
EXPOSE 8190
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('WORKER_HEALTH_PORT', '8190') + '/', timeout=4)"]
ENTRYPOINT ["python", "-m", "worker.entry"]
CMD ["start"]
