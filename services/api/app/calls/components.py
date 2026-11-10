"""Vendor selection of an AgentConfig (003 R8, R22): what a call runs, decided here and sent to
the worker fully resolved.

Missing choices take the platform defaults (002's catalogs: language, the speech catalog's STT
and TTS providers and noise cancellation, the language model catalog's default model; TTS models
the adapter's default); noise cancellation ``null`` is off. ``stt.model = null`` is Auto, picked
per language by 002's speech catalog (``VoiceCatalog.stt_auto``, the rule the agent builder
shows); a picked model that does not list the call's language counts as no model (refused with
``stt_language_unsupported``, FR-045). ``unsupported`` checks the result against the vendors the
worker can run, so a model it cannot run is refused at admission.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from callwright_contract import diagnostics as diag
from callwright_contract.adapters import AdapterCatalog

from app.agents.defaults import ADVANCED_DEFAULTS, CALL_BEHAVIOR_DEFAULTS, nc_default
from app.core.vendors import provider_runnable, runnable_providers
from app.llms.service import label_for as llm_label
from app.llms.service import load_catalog as load_llm_catalog
from app.pricing import engine
from app.voices.catalog import DEFAULT_LANGUAGE
from app.voices.catalog import load_catalog as load_speech_catalog


@dataclass(frozen=True)
class Vendor:
    kind: str
    provider: str
    model: str | None


@dataclass(frozen=True)
class ResolvedComponents:
    language: str
    stt: Vendor
    llm: Vendor
    tts: Vendor
    nc: Vendor | None
    stt_auto: bool

    def vendors(self) -> list[Vendor]:
        out = [self.stt, self.llm, self.tts]
        if self.nc is not None:
            out.append(self.nc)
        return out

    def pricing(self, usage: Mapping[str, Any] | None = None) -> engine.Components:
        """Pricing selection; the STT model actually metered wins over the configured one."""
        stt_model = self.stt.model
        metered = _first(usage, "stt")
        if metered is not None and metered.get("model"):
            stt_model = str(metered["model"])
        return engine.Components(
            stt=engine.Selection(self.stt.provider, stt_model),
            llm=engine.Selection(self.llm.provider, self.llm.model),
            tts=engine.Selection(self.tts.provider, self.tts.model),
            nc=engine.Selection(self.nc.provider, self.nc.model) if self.nc is not None else None,
        )


def _section(config: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = config.get(key)
    return value if isinstance(value, Mapping) else {}


def _first(usage: Mapping[str, Any] | None, kind: str) -> Mapping[str, Any] | None:
    rows = (usage or {}).get(kind)
    if isinstance(rows, Sequence) and rows and isinstance(rows[0], Mapping):
        return rows[0]
    return None


def auto_stt_model(provider: str, language: str) -> str | None:
    """The model speech recognition Auto runs for ``language``, or None when none covers it."""
    auto = load_speech_catalog().stt_auto_rules().get(provider)
    return auto.resolve(language) if auto is not None else None


def resolve(config: Mapping[str, Any], catalog: AdapterCatalog) -> ResolvedComponents:
    speech = load_speech_catalog()
    llms = load_llm_catalog()
    language = str(config.get("language") or DEFAULT_LANGUAGE)
    stt_raw = _section(config, "stt")
    stt_provider = catalog.canonical_provider(
        "stt", str(stt_raw.get("provider") or speech.stt_default["provider"])
    )
    stt_model = stt_raw.get("model") or None
    stt_auto = stt_model is None
    if stt_auto:
        stt_model = auto_stt_model(stt_provider, language)
    llm_raw = _section(config, "llm")
    llm_provider = catalog.canonical_provider("llm", str(llm_raw.get("provider") or llms.default_provider))
    llm_model = str(llm_raw.get("model") or llms.default_model)
    tts_raw = _section(config, "tts")
    tts_provider = catalog.canonical_provider(
        "tts", str(tts_raw.get("provider") or speech.tts_default_provider)
    )
    tts_entry = catalog.entry("tts", tts_provider)
    tts_model = tts_raw.get("model") or (tts_entry.default_model if tts_entry else None)
    nc_raw = config.get("noise_cancellation", nc_default())
    nc: Vendor | None = None
    if isinstance(nc_raw, Mapping) and nc_raw and nc_raw.get("provider") not in (None, "none"):
        nc = Vendor("nc", str(nc_raw.get("provider")), nc_raw.get("model"))
    return ResolvedComponents(
        language=language,
        stt=Vendor("stt", stt_provider, str(stt_model) if stt_model else None),
        llm=Vendor("llm", llm_provider, llm_model),
        tts=Vendor("tts", tts_provider, str(tts_model) if tts_model else None),
        nc=nc,
        stt_auto=stt_auto,
    )


def with_defaults(config: Mapping[str, Any], components: ResolvedComponents) -> dict[str, Any]:
    """``config`` as the worker runs it: language and vendors resolved (``stt.model`` stays null
    for Auto) and the call-behaviour, keypad, voicemail and background-audio defaults applied."""
    out = dict(config)
    out["language"] = components.language
    out["stt"] = {**_section(config, "stt"), "provider": components.stt.provider}
    out["llm"] = {
        **_section(config, "llm"),
        "provider": components.llm.provider,
        "model": components.llm.model,
    }
    out["tts"] = {
        **_section(config, "tts"),
        "provider": components.tts.provider,
        "model": components.tts.model,
    }
    nc = components.nc
    out["noise_cancellation"] = {"provider": nc.provider, "model": nc.model} if nc is not None else None
    out["call_behavior"] = {**CALL_BEHAVIOR_DEFAULTS, **_section(config, "call_behavior")}
    advanced = dict(_section(config, "advanced"))
    for key in ("dtmf", "voicemail_detection", "background_audio"):
        advanced[key] = {**ADVANCED_DEFAULTS[key], **_section(advanced, key)}
    out["advanced"] = advanced
    return out


def unsupported(components: ResolvedComponents, catalog: AdapterCatalog) -> str | None:
    """Diagnostic for the first vendor the worker cannot run, else None."""
    if components.stt.model is None:
        return diag.diagnostic(diag.STT_LANGUAGE_UNSUPPORTED, components.stt.provider, components.language)
    for vendor in components.vendors():
        if not catalog.supports(vendor.kind, vendor.provider, vendor.model):
            known = catalog.entry(vendor.kind, vendor.provider) is not None
            return diag.diagnostic(
                diag.UNSUPPORTED_VENDOR, vendor.kind, vendor.provider, vendor.model if known else None
            )
    return None


_NOUN = {"stt": "speech recognition", "llm": "language model", "tts": "voice", "nc": "noise cancellation"}


def describe(vendor: Vendor) -> str:
    """``Sarvam speech recognition``: the vendor as a person reads it."""
    speech = load_speech_catalog()
    label = vendor.provider
    if vendor.kind == "llm":
        label = llm_label(vendor.provider)
    elif vendor.kind == "stt":
        found = speech.stt_provider(vendor.provider)
        label = found.label if found is not None else label
    elif vendor.kind == "tts":
        found_tts = speech.tts_provider(vendor.provider)
        label = found_tts.label if found_tts is not None else label
    else:
        label = next((n.label for n in speech.noise_cancellation if n.provider == vendor.provider), label)
    return f"{label} {_NOUN[vendor.kind]}"


def not_set_up(vendor: Vendor) -> str:
    return f"{describe(vendor)} is not set up on this platform."


def unavailable_vendors(components: ResolvedComponents, settings: object) -> list[Vendor]:
    """The agent's vendors this deployment cannot run, in stt, llm, tts, nc order."""
    listed = runnable_providers(settings)
    return [v for v in components.vendors() if not provider_runnable(v.provider, settings, listed)]


def usage_meters(usage: Mapping[str, Any] | None) -> dict[str, int]:
    """Sum a cumulative usage snapshot into 001's bundle meters (all models of a component)."""
    usage = usage or {}

    def total(kind: str, key: str) -> int:
        rows = usage.get(kind) or []
        return sum(int(r.get(key) or 0) for r in rows if isinstance(r, Mapping))

    return {
        "llm_input_tokens": total("llm", "input_tokens"),
        "llm_output_tokens": total("llm", "output_tokens"),
        "tts_chars": total("tts", "characters"),
    }
