"""The API lifespan and the jobs worker install the same features through ``app/features.py``.

Regressions: the worker once installed its own shorter list, so it lacked 002's agent versions
(every pipeline run failed to price) and 004's flow runtime (due callbacks of flow agents were
refused), and no process ever set the object signer.
"""

from __future__ import annotations

from dataclasses import fields
from typing import Any

import pytest

from app import features, worker
from app.agents import hooks as agent_hooks
from app.calls import ports
from app.core.config import Settings
from app.core.feature import Runtime
from app.evals import runtime as quality_runtime
from app.issues import runtime as issues_runtime
from app.main import create_app


def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    defaults = ports.Registry()
    for f in fields(ports.Registry):
        monkeypatch.setattr(ports.registry, f.name, getattr(defaults, f.name))
    monkeypatch.setattr(agent_hooks, "_validators", {})
    monkeypatch.setattr(agent_hooks, "_resolvers", {})
    monkeypatch.setattr(agent_hooks, "_usage_checkers", [])
    monkeypatch.setattr(agent_hooks, "_duplicate_hooks", [])


def _installed() -> dict[str, Any]:
    r = ports.registry
    return {
        "agent_versions": type(r.agent_versions).__name__,
        "inbound_routers": {k: type(v).__name__ for k, v in r.inbound_routers.items()},
        "outbound_dial": type(r.outbound_dial).__name__,
        "signer": type(r.signer).__name__,
        "run_snapshot": getattr(r.run_snapshot, "__qualname__", None),
        "caller_language": type(r.caller_language).__name__,
        "quality": type(r.quality).__name__,
        "step_handlers": sorted(r.step_handlers),
        "validators": sorted(agent_hooks._validators),
        "resolvers": sorted(agent_hooks._resolvers),
        "usage_checkers": sorted(f"{f.__module__}.{f.__name__}" for f in agent_hooks._usage_checkers),
        "duplicate_hooks": len(agent_hooks._duplicate_hooks),
    }


async def test_api_and_worker_install_the_same_features(
    migrated: None, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(quality_runtime, "_runtime", quality_runtime._runtime)
    monkeypatch.setattr(issues_runtime, "_runtime", issues_runtime._runtime)
    roles: dict[str, list[str]] = {}
    install = features.install

    async def recording_install(runtime: Runtime) -> list[str]:
        roles[runtime.role] = await install(runtime)
        return roles[runtime.role]

    monkeypatch.setattr(features, "install", recording_install)

    _reset(monkeypatch)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        api = _installed()

    _reset(monkeypatch)
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    ctx: dict[str, Any] = {"redis": object()}
    await worker.startup(ctx)
    try:
        in_worker = _installed()
    finally:
        await worker.shutdown(ctx)

    assert roles["api"] == roles["worker"] == [f.name for f in features.FEATURES if f.install]
    assert in_worker == api
    assert api["agent_versions"] == "AgentVersionsAdapter"
    assert api["run_snapshot"] == "run_snapshot"
    assert api["caller_language"] == "CallerLanguage"
    assert api["signer"] == "DevSigner"
    assert api["quality"] == "QualityPort"
    assert api["step_handlers"] == ["analyze", "evaluate"]
    assert api["inbound_routers"] == {"sip_inbound": "PhoneNumberRouter", "whatsapp": "WhatsAppRouter"}
    assert api["outbound_dial"] == "SipOutboundDial"
    assert api["usage_checkers"] == [
        "app.channels.phone_numbers.service.attachments_for_agent",
        "app.channels.whatsapp.service.attachments_for_agent",
    ]
