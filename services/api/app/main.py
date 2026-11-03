"""FastAPI app factory (T021, T083). Run with ``uv run uvicorn app.main:app --port 8100``.

Routers mount under ``/v1``. ``app.state`` carries the settings, the database (app and admin
engines), Redis, the token verifier, the identity provider and the payment gateway; tests build
their own app with ``create_app(settings)``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.agent_versions.router import router as agent_versions_router
from app.agent_versions.runtime_port import register as register_agent_versions
from app.agents.router import router as agents_router
from app.analysis_vars.router import router as analysis_vars_router
from app.analytics_chat.router import router as analytics_chat_router
from app.annotations.router import router as annotations_router
from app.auth.idp import build_idp
from app.auth.router import router as auth_router
from app.billing.router import router as billing_router
from app.billing.stripe_gateway import build_gateway
from app.calibration.router import router as calibration_router
from app.call_events.router import router as call_events_router
from app.callbacks.router import internal_router as callbacks_internal_router
from app.callbacks.router import router as callbacks_router
from app.caller_language.router import internal_router as caller_language_internal_router
from app.caller_language.router import router as caller_language_router
from app.calls.catalog import load_catalog
from app.calls.read_router import router as calls_read_router
from app.calls.router import router as calls_router
from app.core.auth import TokenVerifier
from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.errors import UnhandledErrorMiddleware, install_error_handlers
from app.core.health import router as health_router
from app.core.livekit import build_livekit
from app.core.logging import configure_logging
from app.core.queue import ArqJobQueue
from app.core.sip import build_sip
from app.core.storage import build_store
from app.core.storage import dev_router as dev_storage_router
from app.core.vm_waker import REDIS_DOWN_ERRORS, ActivityMarker, VmWaker, redis_down_handler
from app.dashboard.router import router as dashboard_router
from app.datasets.router import router as datasets_router
from app.demo.router import router as demo_router
from app.dev.router import checkout_router as fake_checkout_router
from app.dev.router import router as dev_router
from app.evals.install import install as install_quality
from app.evals.router import router as evals_router
from app.evaluators.router import router as evaluators_router
from app.flows.hooks import register as register_flows
from app.flows.router import router as flows_router
from app.issues.install import install as install_issues
from app.issues.router import router as issues_router
from app.knowledge.router import internal_router as knowledge_internal_router
from app.knowledge.router import router as knowledge_router
from app.livekit_hooks.router import router as livekit_hooks_router
from app.llms.client import LlmClient
from app.llms.router import router as llms_router
from app.outbound.router import router as outbound_router
from app.phone_numbers.install import install as install_channels
from app.phone_numbers.router import router as phone_numbers_router
from app.pricing.router import router as pricing_router
from app.prompt_ai.router import router as prompt_ai_router
from app.recordings.router import router as recordings_router
from app.review.router import router as review_router
from app.sessions.router import router as sessions_router
from app.simulator.install import install as install_simulator
from app.simulator.internal_router import router as simulator_internal_router
from app.simulator.router import router as simulator_router
from app.templates.router import router as templates_router
from app.test_cases.router import router as test_cases_router
from app.test_runs.router import internal_router as test_runs_internal_router
from app.test_runs.router import router as test_runs_router
from app.tools.router import router as tools_router
from app.usage.router import router as usage_router
from app.voice_commands.router import router as voice_commands_router
from app.voices.router import router as voices_router
from app.webhooks_out.router import router as webhooks_out_router
from app.whatsapp.graph_client import build_graph as build_whatsapp_graph
from app.whatsapp.router import public_router as whatsapp_public_router
from app.whatsapp.router import router as whatsapp_router
from app.workspaces.router import router as workspaces_router

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
    configure_logging(settings.log_level, settings.log_json)

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
        # 002 supplies the agent versions 003 admits and claims calls with.
        register_agent_versions()
        # 004: flow snapshot resolver and validator, duplicate and mock hooks; flows may run.
        register_flows()
        # Voice runtime (003): media server, worker catalog, job queue, outbound webhook client.
        app.state.livekit = build_livekit(settings)
        app.state.adapter_catalog = load_catalog(settings.adapter_catalog_path)
        jobs = ArqJobQueue()
        app.state.jobs = jobs
        app.state.webhook_http = httpx.AsyncClient(follow_redirects=False)
        app.state.storage = build_store(settings)
        app.state.llm_client = LlmClient(settings)
        app.state.vm_waker = VmWaker(settings.wake_vm_project, settings.wake_vm_zone, settings.wake_vm_name)
        # Channels (010): SIP trunks and dispatch rules, WhatsApp Cloud API, inbound routing.
        app.state.sip = build_sip(settings)
        app.state.whatsapp_graph = build_whatsapp_graph(settings)
        install_channels(app.state)
        # Quality and evaluations (007): post-call analysis and evaluator pipeline handlers, the
        # 006 quality port and the built-in evaluator catalog.
        await install_quality(settings, db, queue=jobs)
        # Testing and simulation (008): offline replies for drafting, judging and persona briefs.
        install_simulator()
        # Issues and auto-fix (009): naming and drafting models, embedder, validation hook.
        install_issues(settings)
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
    for router in (
        health_router,
        auth_router,
        workspaces_router,
        billing_router,
        pricing_router,
        usage_router,
        sessions_router,
        calls_router,
        calls_read_router,
        recordings_router,
        dashboard_router,
        analytics_chat_router,
        voice_commands_router,
        call_events_router,
        webhooks_out_router,
        livekit_hooks_router,
        agents_router,
        agent_versions_router,
        templates_router,
        llms_router,
        voices_router,
        prompt_ai_router,
        tools_router,
        knowledge_router,
        knowledge_internal_router,
        phone_numbers_router,
        outbound_router,
        callbacks_router,
        callbacks_internal_router,
        caller_language_router,
        caller_language_internal_router,
        whatsapp_router,
        whatsapp_public_router,
        flows_router,
        demo_router,
        analysis_vars_router,
        evaluators_router,
        evals_router,
        annotations_router,
        review_router,
        calibration_router,
        test_cases_router,
        test_runs_router,
        test_runs_internal_router,
        simulator_router,
        simulator_internal_router,
        datasets_router,
        issues_router,
    ):
        app.include_router(router, prefix=API_PREFIX)
    if settings.dev_routes_enabled:
        app.include_router(dev_router, prefix=API_PREFIX)
        app.include_router(dev_storage_router, prefix=API_PREFIX)
    if settings.fake_checkout_enabled:
        app.include_router(fake_checkout_router, prefix=API_PREFIX)
    _log_hosting_flags(settings)
    _setup_tracing(app, settings)
    return app


app = create_app()
