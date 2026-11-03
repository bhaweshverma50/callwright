"""arq jobs worker (T014). Run with ``uv run arq app.core.jobs.WorkerSettings``.

Features register job functions and cron entries here; the worker builds one ``Database`` and
one Redis client at startup and passes them through ``ctx``.
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq import cron
from arq.connections import ArqRedis, RedisSettings, create_pool
from arq.cron import CronJob

from app.core.config import get_settings
from app.core.db import Database
from app.core.logging import configure_logging
from app.core.queue import ArqJobQueue, JobQueue, redis_settings_for

__all__ = ["ArqJobQueue", "JobQueue", "WorkerSettings", "enqueue"]


def redis_settings() -> RedisSettings:
    return redis_settings_for(get_settings().redis_url)


async def startup(ctx: dict[str, Any]) -> None:
    import httpx

    from app.agent_versions.runtime_port import register as register_agent_versions
    from app.calls.catalog import load_catalog
    from app.core.livekit import build_livekit

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    # The post-call pipeline reads each call's agent version (pricing, analysis): 002 supplies
    # it here as it does in create_app, or every standalone worker run would fail to price.
    register_agent_versions()
    ctx["settings"] = settings
    ctx["db"] = Database(settings.database_url, settings.database_admin_url, pool_size=4)
    # Voice runtime (003): jobs enqueue follow-ups on the worker's own pool.
    ctx["jobs"] = ArqJobQueue(pool=ctx["redis"])
    ctx["livekit"] = build_livekit(settings)
    # Channels (010): the drain cron removes SIP objects of deleted numbers and channels.
    from app.core.sip import build_sip

    ctx["sip"] = build_sip(settings)
    ctx["adapter_catalog"] = load_catalog(settings.adapter_catalog_path)
    ctx["http"] = httpx.AsyncClient(follow_redirects=False)
    # Quality and evaluations (007): the pipeline's analyze and evaluate steps run here.
    from app.evals.install import install as install_quality

    await install_quality(settings, None, queue=ctx["jobs"], sync=False)
    # Testing and simulation (008): dispatch to the text runner, judges, sweeper.
    from app.simulator.install import install as install_simulator

    install_simulator()
    # Issues and auto-fix (009): detection, validation finalize, sweeper and audit.
    from app.issues.install import install as install_issues

    install_issues(settings)


async def shutdown(ctx: dict[str, Any]) -> None:
    for key in ("http", "livekit", "sip"):
        client = ctx.get(key)
        if client is not None:
            await client.aclose()
    db: Database | None = ctx.get("db")
    if db is not None:
        await db.dispose()


async def enqueue(job_name: str, *args: Any, **kwargs: Any) -> None:
    pool: ArqRedis = await create_pool(redis_settings())
    try:
        await pool.enqueue_job(job_name, *args, **kwargs)
    finally:
        await pool.aclose()


def _functions() -> list[Any]:
    from app.analytics_chat.jobs import purge_analytics_audit
    from app.billing.jobs import reconcile_balances
    from app.callbacks.jobs import place_due_callbacks
    from app.calls.jobs import reap_stuck_calls, run_pipeline, settle_stuck_recordings, start_recording
    from app.evals.install import job_functions as quality_jobs
    from app.issues.install import job_functions as issue_jobs
    from app.knowledge.jobs import ingest_document
    from app.phone_numbers.jobs import drain_channels
    from app.simulator.install import job_functions as simulation_jobs
    from app.webhooks_out.jobs import deliver_webhook, purge_webhook_deliveries

    return [
        *simulation_jobs(),
        drain_channels,
        place_due_callbacks,
        reconcile_balances,
        run_pipeline,
        start_recording,
        deliver_webhook,
        reap_stuck_calls,
        settle_stuck_recordings,
        purge_webhook_deliveries,
        purge_analytics_audit,
        ingest_document,
        *quality_jobs(),
        *issue_jobs(),
    ]


def _crons() -> list[CronJob]:
    from app.analytics_chat.jobs import purge_analytics_audit
    from app.billing.jobs import reconcile_balances
    from app.callbacks.jobs import place_due_callbacks
    from app.calls.jobs import reap_stuck_calls, settle_stuck_recordings
    from app.issues.install import crons as issue_crons
    from app.phone_numbers.jobs import drain_channels
    from app.simulator.install import crons as simulation_crons
    from app.webhooks_out.jobs import purge_webhook_deliveries

    return [
        *simulation_crons(),
        *issue_crons(),
        cron(reconcile_balances, hour={3}, minute={0}, run_at_startup=False),
        # 003 R16: stuck calls every 15 s; deliveries older than 30 days once a day.
        cron(reap_stuck_calls, second={0, 15, 30, 45}, run_at_startup=False, unique=True),
        # Recordings whose egress_ended webhook was lost: every minute.
        cron(settle_stuck_recordings, second={50}, run_at_startup=False, unique=True),
        cron(purge_webhook_deliveries, hour={4}, minute={0}, run_at_startup=False),
        cron(purge_analytics_audit, hour={4}, minute={30}, run_at_startup=False),
        # 010 R8: draining numbers and WhatsApp channels are removed once idle (every 30 s).
        cron(drain_channels, second={5, 35}, run_at_startup=False, unique=True),
        # 011: scheduled callbacks are dialled once due (every minute).
        cron(place_due_callbacks, second={20}, run_at_startup=False, unique=True),
    ]


class WorkerSettings:
    functions: ClassVar[list[Any]] = _functions()
    cron_jobs: ClassVar[list[CronJob]] = _crons()
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings()
    poll_delay = get_settings().arq_poll_delay_s
