"""Every API feature, once. ``app.main`` (routers and install in the lifespan) and ``app.worker``
(install, jobs and crons) both read this list, so the API process and the jobs worker always
install the same features."""

from __future__ import annotations

import inspect

from arq.cron import CronJob
from fastapi import APIRouter

from app.agents.install import FEATURE as agents
from app.analysis_vars.install import FEATURE as analysis_vars
from app.analytics_chat.install import FEATURE as analytics_chat
from app.annotations.install import FEATURE as annotations_feature
from app.auth.install import FEATURE as auth
from app.billing.install import FEATURE as billing
from app.calibration.install import FEATURE as calibration
from app.call_events.install import FEATURE as call_events
from app.callbacks.install import FEATURE as callbacks
from app.caller_language.install import FEATURE as caller_language
from app.calls.install import FEATURE as calls
from app.channels.install import FEATURE as channels
from app.core.config import Settings
from app.core.feature import Feature, JobFunction, Runtime
from app.dashboard.install import FEATURE as dashboard
from app.datasets.install import FEATURE as datasets
from app.demo.install import FEATURE as demo
from app.dev.install import FEATURE as dev
from app.evals.install import FEATURE as evals
from app.evaluators.install import FEATURE as evaluators
from app.flows.install import FEATURE as flows
from app.issues.install import FEATURE as issues
from app.knowledge.install import FEATURE as knowledge
from app.livekit_hooks.install import FEATURE as livekit_hooks
from app.llms.install import FEATURE as llms
from app.outbound.install import FEATURE as outbound
from app.preferences.install import FEATURE as preferences
from app.pricing.install import FEATURE as pricing
from app.prompt_ai.install import FEATURE as prompt_ai
from app.recordings.install import FEATURE as recordings
from app.review.install import FEATURE as review
from app.sessions.install import FEATURE as sessions
from app.simulator.install import FEATURE as simulator
from app.templates.install import FEATURE as templates
from app.test_cases.install import FEATURE as test_cases
from app.test_runs.install import FEATURE as test_runs
from app.tools.install import FEATURE as tools
from app.usage.install import FEATURE as usage
from app.voice_commands.install import FEATURE as voice_commands
from app.voices.install import FEATURE as voices
from app.webhooks_out.install import FEATURE as webhooks_out
from app.workspaces.install import FEATURE as workspaces

# Router order is mount order.
FEATURES: tuple[Feature, ...] = (
    auth,
    workspaces,
    billing,
    pricing,
    usage,
    sessions,
    calls,
    recordings,
    dashboard,
    analytics_chat,
    voice_commands,
    call_events,
    webhooks_out,
    livekit_hooks,
    agents,
    templates,
    llms,
    voices,
    prompt_ai,
    tools,
    knowledge,
    channels,
    outbound,
    callbacks,
    caller_language,
    preferences,
    flows,
    demo,
    analysis_vars,
    evaluators,
    evals,
    annotations_feature,
    review,
    calibration,
    test_cases,
    test_runs,
    simulator,
    datasets,
    issues,
    dev,
)


def routers(settings: Settings) -> list[APIRouter]:
    out: list[APIRouter] = []
    for feature in FEATURES:
        out.extend(feature.routers)
        out.extend(router for flag, router in feature.conditional_routers if getattr(settings, flag))
    return out


async def install(runtime: Runtime) -> list[str]:
    """Run every feature's install hook; returns the names of the features that have one."""
    installed: list[str] = []
    for feature in FEATURES:
        if feature.install is None:
            continue
        result = feature.install(runtime)
        if inspect.isawaitable(result):
            await result
        installed.append(feature.name)
    return installed


def job_functions() -> dict[str, JobFunction]:
    jobs: dict[str, JobFunction] = {}
    for feature in FEATURES:
        for name, fn in feature.jobs.items():
            if name in jobs:
                raise ValueError(f"job {name!r} is declared by two features")
            jobs[name] = fn
    return jobs


def crons() -> list[CronJob]:
    return [cron for feature in FEATURES for cron in feature.crons]


def secret_fields() -> list[str]:
    return [name for feature in FEATURES for name in feature.secret_fields]
