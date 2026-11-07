"""FastAPI app factory (T021, T083). Run with ``uv run uvicorn app.main:app --port 8100``.

Routers mount under ``/v1``: core's health route, then every feature's routers in
``app/features.py`` order. The lifespan builds the shared clients on ``app.state`` (settings,
database, Redis, token verifier, identity provider, payment gateway, LiveKit, job queue, storage,
SIP, WhatsApp Graph) and runs every feature's ``install`` hook, as the jobs worker does; tests
build their own app with ``create_app(settings)``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from callwright_contract.adapters import load_catalog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app import features
from app.auth.idp import build_idp
from app.billing.stripe_gateway import build_gateway
from app.channels.sip import build_sip
from app.channels.whatsapp.graph_client import build_graph as build_whatsapp_graph
from app.core.auth import TokenVerifier
from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.errors import UnhandledErrorMiddleware, install_error_handlers
from app.core.feature import Runtime
from app.core.health import router as health_router
from app.core.livekit import build_livekit
from app.core.logging import configure_logging
from app.core.queue import ArqJobQueue
from app.core.storage import build_store
from app.core.vm_waker import REDIS_DOWN_ERRORS, ActivityMarker, VmWaker, redis_down_handler
from app.llms.client import LlmClient

logger = logging.getLogger(__name__)
API_PREFIX = "/v1"
_GLOBAL_INSTRUMENTATION = False


def _setup_tracing(app: FastAPI, settings: Settings) -> None:
    """OpenTelemetry for FastAPI, SQLAlchemy, httpx and Redis (T083). Spans are exported over
    OTLP when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set; trace ids are always generated so problem
    responses and logs carry them."""
    global _GLOBAL_INSTRUMENTATION
    from opentelemetry import trace
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    if not _GLOBAL_INSTRUMENTATION:
        provider = TracerProvider(resource=Resource.create({"service.name": "callwright-api"}))
        if settings.otel_exporter_otlp_endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=f"{settings.otel_exporter_otlp_endpoint.rstrip('/')}/v1/traces")
                )
            )
        trace.set_tracer_provider(provider)
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        HTTPXClientInstrumentor().instrument()
        RedisInstrumentor().instrument()
        _GLOBAL_INSTRUMENTATION = True
    FastAPIInstrumentor.instrument_app(app, excluded_urls=f"{API_PREFIX}/health")


def _instrument_db(db: Database) -> None:
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    # The instrumentation's declared range stops before SQLAlchemy 2.1; the engine hooks it uses
    # are unchanged, so the dependency check is skipped.
    SQLAlchemyInstrumentor().instrument(
        engines=[db.engine.sync_engine, db.admin_engine.sync_engine], skip_dep_check=True
    )


def build_redis(settings: Settings) -> Redis:
    """The API's Redis client: short timeouts (a stopped VM must not hang requests), a health
    check on idle pooled connections and one retry, so connections broken by a VM restart are
    replaced instead of failing the next request."""
    client: Redis = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=settings.redis_connect_timeout_s,
        socket_timeout=settings.redis_socket_timeout_s,
        health_check_interval=30,
        retry=Retry(NoBackoff(), 1),
        retry_on_error=[RedisConnectionError, RedisTimeoutError],
    )
    return client


def _log_hosting_flags(settings: Settings) -> None:
    if settings.auth_auto_verify_email:
        logger.warning(
            "AUTH_AUTO_VERIFY_EMAIL is on: registration confirms accounts without an email check "
            "(ENV=%s). Use it only for a demo.",
            settings.env,
        )
    dev_routes = settings.dev_routes_enabled or settings.fake_checkout_enabled
    if settings.env not in ("dev", "test") and dev_routes:
        logger.warning(
            "development routes are mounted (ENV=%s): dev mail and storage previews %s, fake checkout %s",
            settings.env,
            "on" if settings.dev_routes_enabled else "off",
            "on" if settings.fake_checkout_enabled else "off",
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json, features.secret_fields())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(settings.database_url, settings.database_admin_url, pool_size=settings.db_pool_size)
        redis = build_redis(settings)
        _instrument_db(db)
        app.state.db = db
        app.state.redis = redis
        app.state.verifier = TokenVerifier(settings)
        app.state.idp = build_idp(settings, db)
        app.state.stripe = build_gateway(settings)
        app.state.livekit = build_livekit(settings)
        app.state.adapter_catalog = load_catalog()
        jobs = ArqJobQueue()
        app.state.jobs = jobs
        app.state.webhook_http = httpx.AsyncClient(follow_redirects=False)
        app.state.storage = build_store(settings)
        app.state.llm_client = LlmClient(settings)
        app.state.vm_waker = VmWaker(settings.wake_vm_project, settings.wake_vm_zone, settings.wake_vm_name)
        app.state.sip = build_sip(settings)
        app.state.whatsapp_graph = build_whatsapp_graph(settings)
        await features.install(Runtime("api", settings, db, jobs, app.state.webhook_http))
        try:
            yield
        finally:
            await app.state.whatsapp_graph.aclose()
            await app.state.sip.aclose()
            await app.state.vm_waker.aclose()
            await app.state.webhook_http.aclose()
            await jobs.aclose()
            await app.state.livekit.aclose()
            await redis.aclose()
            await db.dispose()

    app = FastAPI(
        title="Callwright API",
        version=settings.version,
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    install_error_handlers(app)
    for exc_class in REDIS_DOWN_ERRORS:
        app.add_exception_handler(exc_class, redis_down_handler)
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(
        ActivityMarker,
        redis_getter=lambda: getattr(app.state, "redis", None),
        skip_prefixes=(f"{API_PREFIX}/health",),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Retry-After"],
    )
    for router in (health_router, *features.routers(settings)):
        app.include_router(router, prefix=API_PREFIX)
    _log_hosting_flags(settings)
    _setup_tracing(app, settings)
    return app


app = create_app()
