"""Whether a catalog component is offered, and the template overlay that replaces the ones that
are not with the language defaults (T074, FR-054, research R16).

``llm_offer``, ``stt_offer`` and ``tts_offer`` answer one question for every caller: agent
validation (``agents/validation.py``: errors and publish blockers), flow-node overrides
(``flows/catalogs.py``) and ``template_overlay`` (replacement). Each caller decides what a status
means for it; none looks components up in the catalogs itself.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Literal

from app.agents import defaults
from app.llms.service import LlmCatalog, LlmModel
from app.llms.service import load_catalog as load_llm_catalog
from app.voices.catalog import DEFAULT_LANGUAGE, SttModel, SttProvider, TtsModel, TtsProvider, VoiceCatalog
from app.voices.catalog import load_catalog as load_voice_catalog

# ``unknown_model`` only when a model was named; ``None`` (no model) is ``ok`` with ``model = None``.
Status = Literal["ok", "unknown_provider", "unknown_model", "withdrawn"]


@dataclass(frozen=True)
class LlmOffer:
    status: Status
    model: LlmModel | None


@dataclass(frozen=True)
class SttOffer:
    status: Status
    provider: SttProvider | None
    model: SttModel | None


@dataclass(frozen=True)
class TtsOffer:
    status: Status
    provider: TtsProvider | None
    model: TtsModel | None


def llm_offer(provider: str, model_id: str, lc: LlmCatalog | None = None) -> LlmOffer:
    lc = lc or load_llm_catalog()
    if not lc.has_provider(provider):
        return LlmOffer("unknown_provider", None)
    model = lc.model(provider, model_id)
    if model is None:
        return LlmOffer("unknown_model", None)
    return LlmOffer("withdrawn" if model.withdrawn else "ok", model)


def stt_offer(provider: str, model_id: str | None, vc: VoiceCatalog | None = None) -> SttOffer:
    found = (vc or load_voice_catalog()).stt_provider(provider)
    if found is None:
        return SttOffer("unknown_provider", None, None)
    if model_id is None:
        return SttOffer("ok", found, None)
    model = found.model(model_id)
    if model is None:
        return SttOffer("unknown_model", found, None)
    return SttOffer("withdrawn" if model.withdrawn else "ok", found, model)


def tts_offer(provider: str, model_id: str | None, vc: VoiceCatalog | None = None) -> TtsOffer:
    found = (vc or load_voice_catalog()).tts_provider(provider)
    if found is None:
        return TtsOffer("unknown_provider", None, None)
    if model_id is None:
        return TtsOffer("ok", found, None)
    model = found.model(model_id)
    if model is None:
        return TtsOffer("unknown_model", found, None)
    return TtsOffer("withdrawn" if model.withdrawn else "ok", found, model)


def _replaced(pointer: str, message: str) -> dict[str, str]:
    return {"pointer": pointer, "code": "component_replaced", "message": message}


TEMPLATE_ONLY = ("agent_name", "graph")  # a flow template's graph belongs to the flow, not the config


def template_overlay(template_config: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """A template's AgentConfig overlay for ``create_agent`` (``TEMPLATE_ONLY`` keys dropped) and a
    ``component_replaced`` warning for each component replaced with the language default."""
    config = {k: copy.deepcopy(v) for k, v in template_config.items() if k not in TEMPLATE_ONLY}
    warnings: list[dict[str, str]] = []
    language = str(config.get("language") or DEFAULT_LANGUAGE)
    vc = load_voice_catalog()
    if vc.language(language) is None:
        default_label = vc.language(DEFAULT_LANGUAGE)
        warnings.append(
            _replaced(
                "/language",
                f"The template language {language} is not offered; "
                f"{default_label.label if default_label else DEFAULT_LANGUAGE} is used.",
            )
        )
        language = DEFAULT_LANGUAGE
        config["language"] = language
    llm = config.get("llm")
    if isinstance(llm, dict):
        offer = llm_offer(str(llm.get("provider")), str(llm.get("model")))
        if offer.model is None or offer.status == "withdrawn":
            config["llm"] = {k: v for k, v in defaults.llm_defaults().items() if k != "temperature"}
            warnings.append(
                _replaced(
                    "/llm/model", "The template's model is no longer offered; the default model is used."
                )
            )
        elif offer.model.temperature.is_fixed:
            llm.pop("temperature", None)
    stt = config.get("stt")
    if isinstance(stt, dict):
        model_id = stt.get("model")
        model_key = model_id if isinstance(model_id, str) else None
        stt_found = stt_offer(str(stt.get("provider")), model_key, vc).provider
        if stt_found is None or not stt_found.covers(model_key, language):
            config["stt"] = defaults.stt_defaults(language)
            warnings.append(
                _replaced(
                    "/stt",
                    "The template's speech recognition does not support this language; the default is used.",
                )
            )
    tts = config.get("tts")
    if isinstance(tts, dict):
        tts_found = tts_offer(str(tts.get("provider")), str(tts.get("model")), vc)
        voice = tts.get("voice_id")
        voice_gone = "The template's voice is no longer offered; the default voice for the language is used."
        if tts_found.provider is None or tts_found.model is None or tts_found.status == "withdrawn":
            config["tts"] = {
                k: v
                for k, v in defaults.tts_defaults(language).items()
                if k in ("provider", "model", "voice_id")
            }
            warnings.append(_replaced("/tts/voice_id", voice_gone))
        elif isinstance(voice, str) and not tts_found.provider.owns_voice(voice):
            tts["voice_id"] = tts_found.provider.voice_for(language)
            warnings.append(_replaced("/tts/voice_id", voice_gone))
        elif "voice_id" not in tts:
            tts["voice_id"] = tts_found.provider.voice_for(language)
    return config, warnings
