"""Agents on vendors the voice worker cannot run on this deployment (``VOICE_VENDOR_KEYS``).

The answer depends on the deployment, not on the agent, so it is never stored on a version: it is
worked out when the editor validates (a warning on the affected picker), when an agent is
published (a blocker) and when the agents list is read (the Needs attention tab). Saving stays
allowed: the agent can be edited towards a vendor that works.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from callwright_contract.adapters import load_catalog
from sqlalchemy import ColumnElement, and_, case, false, func, or_

from app.agents.defaults import nc_default
from app.calls import components as comp
from app.core.config import get_settings
from app.core.vendors import provider_runnable, runnable_providers
from app.llms.service import load_catalog as load_llm_catalog
from app.voices.catalog import load_catalog as load_speech_catalog

Issue = dict[str, str]

CODE = "vendor_unavailable"
_POINTERS = {
    "stt": "/stt/provider",
    "llm": "/llm/provider",
    "tts": "/tts/provider",
    "nc": "/noise_cancellation/provider",
}


def unavailable(config: Mapping[str, Any]) -> list[comp.Vendor]:
    """The config's vendors this deployment cannot run (empty when it does not gate)."""
    return comp.unavailable_vendors(comp.resolve(config, load_catalog()), get_settings())


def issues(config: Mapping[str, Any]) -> list[Issue]:
    return [
        {"pointer": _POINTERS[v.kind], "code": CODE, "message": comp.not_set_up(v)}
        for v in unavailable(config)
    ]


def messages(*configs: Mapping[str, Any] | None) -> list[str]:
    """Readable reasons for the agents list, without repeats across the configs."""
    out: list[str] = []
    for config in configs:
        for issue in issues(config) if config else []:
            if issue["message"] not in out:
                out.append(issue["message"])
    return out


def unavailable_provider_ids() -> list[str]:
    """Every catalog provider id (aliases included) this deployment cannot run."""
    settings = get_settings()
    listed = runnable_providers(settings)
    names = {n for e in load_catalog().entries for n in (e.provider, *e.aliases)}
    return sorted(n for n in names if not provider_runnable(n, settings, listed))


def attention_condition(draft_config: Any, pinned_config: Any, pinned_exists: Any) -> ColumnElement[bool]:
    """SQL: the draft or the published config picks an unavailable provider (defaults applied)."""
    bad = unavailable_provider_ids()
    if not bad:
        return false()
    speech = load_speech_catalog()
    nc = nc_default()

    def uses_bad(cfg: Any) -> ColumnElement[bool]:
        checks = [
            func.coalesce(cfg[key]["provider"].as_string(), default).in_(bad)
            for key, default in (
                ("stt", speech.stt_default["provider"]),
                ("llm", load_llm_catalog().default_provider),
                ("tts", speech.tts_default_provider),
            )
        ]
        nc_provider = case(
            (cfg.has_key("noise_cancellation"), cfg["noise_cancellation"]["provider"].as_string()),
            else_=nc["provider"] if nc else None,
        )
        checks.append(nc_provider.in_(bad))
        return or_(*checks)

    return or_(uses_bad(draft_config), and_(pinned_exists, uses_bad(pinned_config)))
