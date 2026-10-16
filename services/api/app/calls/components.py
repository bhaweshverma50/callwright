"""Vendor selection of an AgentConfig, as the worker builds it (003 R8, R22, worker pipeline.py).

Defaults mirror the worker: STT Deepgram, LLM Azure OpenAI ``gpt-5.1``, TTS ElevenLabs with the
provider's default model, noise cancellation Sanas ``vi`` when the key is absent and off when it
is ``null``. ``stt.model = null`` is Auto, resolved per language from the adapter catalog.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.calls.catalog import AdapterCatalog
from app.pricing import engine

DEFAULT_LANGUAGE = "en-US"
DEFAULT_LLM = ("azure_openai", "gpt-5.1")
DEFAULT_STT_PROVIDER = "deepgram"
DEFAULT_TTS_PROVIDER = "elevenlabs"
DEFAULT_NC: Mapping[str, str] = {"provider": "sanas", "model": "vi"}


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


def resolve(config: Mapping[str, Any], catalog: AdapterCatalog) -> ResolvedComponents:
    language = str(config.get("language") or DEFAULT_LANGUAGE)
    stt_raw = _section(config, "stt")
    stt_provider = catalog.canonical_provider("stt", str(stt_raw.get("provider") or DEFAULT_STT_PROVIDER))
    stt_model = stt_raw.get("model") or None
    stt_auto = stt_model is None
    if stt_auto:
        stt_model = catalog.resolve_auto_stt(stt_provider, language)
    llm_raw = _section(config, "llm")
    llm_provider = catalog.canonical_provider("llm", str(llm_raw.get("provider") or DEFAULT_LLM[0]))
    llm_model = str(llm_raw.get("model") or DEFAULT_LLM[1])
    tts_raw = _section(config, "tts")
    tts_provider = catalog.canonical_provider("tts", str(tts_raw.get("provider") or DEFAULT_TTS_PROVIDER))
    tts_entry = catalog.entry("tts", tts_provider)
    tts_model = tts_raw.get("model") or (tts_entry.default_model if tts_entry else None)
    nc_raw = config.get("noise_cancellation", DEFAULT_NC)
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


def unsupported(components: ResolvedComponents, catalog: AdapterCatalog) -> str | None:
    """Diagnostic for the first vendor the worker cannot run, else None."""
    if components.stt.model is None:
        return f"stt_language_unsupported:{components.stt.provider}/{components.language}"
    for vendor in components.vendors():
        if not catalog.supports(vendor.kind, vendor.provider, vendor.model):
            suffix = (
                f"/{vendor.model}" if vendor.model and catalog.entry(vendor.kind, vendor.provider) else ""
            )
            return f"unsupported_vendor:{vendor.kind}/{vendor.provider}{suffix}"
    return None


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
