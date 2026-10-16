"""Speech catalog loader (T018, data-model.md sections 8.1 and 8.3 to 8.6). Pure: no I/O beyond
reading ``catalog.yaml`` once.

``catalog_json`` joins every option with the 001 pricing catalog (``price_per_min_usd`` or
``null``). ``controls`` is the single range table for the editor and every override UI (FR-047);
``app.agents.service.validate_override`` validates against it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.pricing import engine

CATALOG_PATH = Path(__file__).with_name("catalog.yaml")


@dataclass(frozen=True)
class Language:
    code: str
    label: str


@dataclass(frozen=True)
class SttModel:
    id: str
    label: str
    description: str | None
    languages: tuple[str, ...]
    builtin_turn_detection: bool
    withdrawn: bool = False


@dataclass(frozen=True)
class SttProvider:
    provider: str
    label: str
    supports_auto: bool
    default_model: str | None
    auto_label: str
    auto_description: str | None
    auto_default: str | None
    auto_by_language: Mapping[str, str]
    models: tuple[SttModel, ...]

    def model(self, model_id: str) -> SttModel | None:
        return next((m for m in self.models if m.id == model_id), None)

    def auto_languages(self) -> tuple[str, ...]:
        seen: list[str] = []
        for m in self.models:
            if m.withdrawn:
                continue
            for code in m.languages:
                if code not in seen:
                    seen.append(code)
        return tuple(seen)

    def covers(self, model_id: str | None, language: str) -> bool:
        if model_id is None:
            return language in self.auto_languages()
        model = self.model(model_id)
        return model is not None and language in model.languages

    def models_for_language(self, language: str) -> list[SttModel]:
        return [m for m in self.models if not m.withdrawn and language in m.languages]


@dataclass(frozen=True)
class TtsModel:
    id: str
    label: str
    description: str | None
    withdrawn: bool = False


@dataclass(frozen=True)
class CuratedVoice:
    voice_id: str
    name: str
    description: str | None
    gender: str | None
    languages: tuple[str, ...]
    preview_url: str | None = None


@dataclass(frozen=True)
class TtsProvider:
    provider: str
    label: str
    default_model: str
    capabilities: Mapping[str, bool]
    voice_listing: Mapping[str, Any]
    voice_id_pattern: str | None
    default_voice: str
    default_voice_by_language: Mapping[str, str]
    models: tuple[TtsModel, ...]
    curated_voices: tuple[CuratedVoice, ...] = ()

    def model(self, model_id: str) -> TtsModel | None:
        return next((m for m in self.models if m.id == model_id), None)

    @property
    def curated(self) -> bool:
        return self.voice_listing.get("source") == "curated"

    def voice_for(self, language: str) -> str:
        """Default voice for ``language``: exact code, then its base language, then the
        provider default."""
        by = self.default_voice_by_language
        return by.get(language) or by.get(language.split("-")[0]) or self.default_voice

    def owns_voice(self, voice_id: str) -> bool:
        """Whether ``voice_id`` can belong to this provider (curated list, else id shape)."""
        if self.curated:
            return any(v.voice_id == voice_id for v in self.curated_voices)
        if self.voice_id_pattern:
            return re.fullmatch(self.voice_id_pattern, voice_id) is not None
        return bool(voice_id)

    def curated_name(self, voice_id: str) -> str | None:
        return next((v.name for v in self.curated_voices if v.voice_id == voice_id), None)


@dataclass(frozen=True)
class NoiseCancellation:
    provider: str
    model: str
    label: str
    description: str | None
    default: bool


@dataclass(frozen=True)
class Control:
    path: str
    label: str
    min: Decimal
    max: Decimal
    step: Decimal
    unit: str | None
    display: str

    def json(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "label": self.label,
            "min": _num(self.min),
            "max": _num(self.max),
            "step": _num(self.step),
            "unit": self.unit,
            "display": self.display,
        }

    def on_step(self, value: Decimal) -> bool:
        return ((value - self.min) / self.step) % 1 == 0


def _num(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


@dataclass(frozen=True)
class VoiceCatalog:
    languages: tuple[Language, ...]
    stt_default: Mapping[str, Any]
    stt_by_language: Mapping[str, Mapping[str, Any]]
    tts_default_provider: str
    stt: tuple[SttProvider, ...]
    tts: tuple[TtsProvider, ...]
    noise_cancellation: tuple[NoiseCancellation, ...]
    ambient_sounds: tuple[tuple[str, str], ...]
    controls: tuple[Control, ...] = field(default=())

    # Lookups ---------------------------------------------------------------------------
    def language(self, code: str) -> Language | None:
        return next((lang for lang in self.languages if lang.code == code), None)

    def stt_provider(self, provider: str) -> SttProvider | None:
        return next((p for p in self.stt if p.provider == provider), None)

    def tts_provider(self, provider: str) -> TtsProvider | None:
        return next((p for p in self.tts if p.provider == provider), None)

    def nc_option(self, provider: str, model: str) -> NoiseCancellation | None:
        return next((n for n in self.noise_cancellation if n.provider == provider and n.model == model), None)

    def default_nc(self) -> NoiseCancellation | None:
        return next((n for n in self.noise_cancellation if n.default), None)

    def ambient_ids(self) -> tuple[str, ...]:
        return tuple(sound_id for sound_id, _ in self.ambient_sounds)

    def control(self, path: str) -> Control | None:
        pointer = path if path.startswith("/") else "/" + path.replace(".", "/")
        return next((c for c in self.controls if c.path == pointer), None)

    # Defaults ----------------------------------------------------------------------------
    def stt_default_for(self, language: str) -> dict[str, Any]:
        chosen = self.stt_by_language.get(language) or self.stt_default
        return {"provider": str(chosen["provider"]), "model": chosen.get("model")}

    def tts_default_for(self, language: str, provider: str | None = None) -> dict[str, Any]:
        tts = self.tts_provider(provider or self.tts_default_provider)
        if tts is None:
            tts = self.tts_provider(self.tts_default_provider)
        assert tts is not None
        return {"provider": tts.provider, "model": tts.default_model, "voice_id": tts.voice_for(language)}

    def resolve_auto_stt(self, provider: str, language: str) -> str | None:
        """The model Auto resolves to for ``language`` (003 RuntimeConfig, data-model 8.3)."""
        stt = self.stt_provider(provider)
        if stt is None:
            return None
        if not stt.supports_auto:
            return stt.default_model
        rule = stt.auto_by_language
        return rule.get(language) or rule.get(language.split("-")[0]) or stt.auto_default


def _parse_language_map(raw: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    return {str(k): v for k, v in (raw or {}).items()}


def parse_catalog(data: Mapping[str, Any]) -> VoiceCatalog:
    stt = tuple(
        SttProvider(
            provider=str(p["provider"]),
            label=str(p["label"]),
            supports_auto=bool(p.get("supports_auto", False)),
            default_model=p.get("default_model"),
            auto_label=str(p.get("auto_label", "Auto")),
            auto_description=p.get("auto_description"),
            auto_default=(p.get("auto_rule") or {}).get("default"),
            auto_by_language={
                str(k): str(v) for k, v in ((p.get("auto_rule") or {}).get("by_language") or {}).items()
            },
            models=tuple(
                SttModel(
                    id=str(m["id"]),
                    label=str(m["label"]),
                    description=m.get("description"),
                    languages=tuple(str(code) for code in m.get("languages", [])),
                    builtin_turn_detection=bool(m.get("builtin_turn_detection", False)),
                    withdrawn=bool(m.get("withdrawn", False)),
                )
                for m in p["models"]
            ),
        )
        for p in data["stt"]
    )
    tts = tuple(
        TtsProvider(
            provider=str(p["provider"]),
            label=str(p["label"]),
            default_model=str(p["default_model"]),
            capabilities={str(k): bool(v) for k, v in p["capabilities"].items()},
            voice_listing=dict(p["voice_listing"]),
            voice_id_pattern=p.get("voice_id_pattern"),
            default_voice=str(p["default_voice"]),
            default_voice_by_language={
                str(k): str(v) for k, v in (p.get("default_voice_by_language") or {}).items()
            },
            models=tuple(
                TtsModel(
                    id=str(m["id"]),
                    label=str(m["label"]),
                    description=m.get("description"),
                    withdrawn=bool(m.get("withdrawn", False)),
                )
                for m in p["models"]
            ),
            curated_voices=tuple(
                CuratedVoice(
                    voice_id=str(v["voice_id"]),
                    name=str(v["name"]),
                    description=v.get("description"),
                    gender=v.get("gender"),
                    languages=tuple(str(code) for code in v.get("languages", [])),
                    preview_url=v.get("preview_url"),
                )
                for v in p.get("curated_voices") or []
            ),
        )
        for p in data["tts"]
    )
    defaults = data["defaults"]
    return VoiceCatalog(
        languages=tuple(Language(str(lang["code"]), str(lang["label"])) for lang in data["languages"]),
        stt_default=dict(defaults["stt"]),
        stt_by_language=_parse_language_map(defaults.get("stt_by_language")),
        tts_default_provider=str(defaults["tts_provider"]),
        stt=stt,
        tts=tts,
        noise_cancellation=tuple(
            NoiseCancellation(
                provider=str(n["provider"]),
                model=str(n["model"]),
                label=str(n["label"]),
                description=n.get("description"),
                default=bool(n.get("default", False)),
            )
            for n in data["noise_cancellation"]
        ),
        ambient_sounds=tuple((str(s["id"]), str(s["label"])) for s in data["ambient_sounds"]),
        controls=tuple(
            Control(
                path=str(c["path"]),
                label=str(c["label"]),
                min=Decimal(str(c["min"])),
                max=Decimal(str(c["max"])),
                step=Decimal(str(c["step"])),
                unit=c.get("unit"),
                display=str(c.get("display", "decimal")),
            )
            for c in data["controls"]
        ),
    )


@lru_cache(maxsize=1)
def load_catalog() -> VoiceCatalog:
    with CATALOG_PATH.open(encoding="utf-8") as fh:
        return parse_catalog(yaml.safe_load(fh))


def _price(pricing: engine.Catalog | None, component: str, provider: str, model: str | None) -> str | None:
    if pricing is None:
        return None
    rate = pricing.lookup(component, provider, model)
    return engine.fmt6(rate.rate_per_min_usd) if rate is not None else None


def _chars_bundle(pricing: engine.Catalog | None, provider: str, model: str) -> int | None:
    rate = pricing.lookup("tts", provider, model) if pricing is not None else None
    if rate is None:
        return None
    return next((b.per_min for b in rate.bundles if b.unit == "tts_chars"), None)


def catalog_json(
    pricing: engine.Catalog | None, *, include_withdrawn: bool = False, catalog: VoiceCatalog | None = None
) -> dict[str, Any]:
    """Body of ``GET /v1/voices/catalog`` (contracts/voices.yaml ``VoiceCatalog``)."""
    cat = catalog or load_catalog()
    stt_out = []
    for p in cat.stt:
        models: list[dict[str, Any]] = []
        for m in p.models:
            if m.withdrawn and not include_withdrawn:
                continue
            models.append(
                {
                    "id": m.id,
                    "label": m.label,
                    "description": m.description,
                    "languages": list(m.languages),
                    "builtin_turn_detection": m.builtin_turn_detection,
                    "price_per_min_usd": _price(pricing, "stt", p.provider, m.id),
                    "withdrawn": m.withdrawn,
                }
            )
        stt_out.append(
            {
                "provider": p.provider,
                "label": p.label,
                "supports_auto": p.supports_auto,
                "auto": (
                    {
                        "label": p.auto_label,
                        "description": p.auto_description,
                        "languages": list(p.auto_languages()),
                        "price_per_min_usd": _price(pricing, "stt", p.provider, None),
                    }
                    if p.supports_auto
                    else None
                ),
                "default_model": p.default_model,
                "auto_rule": (
                    {"default": p.auto_default, "by_language": dict(p.auto_by_language)}
                    if p.supports_auto and p.auto_default
                    else None
                ),
                "models": models,
            }
        )
    codes = [lang.code for lang in cat.languages]
    tts_out = []
    for t in cat.tts:
        tts_out.append(
            {
                "provider": t.provider,
                "label": t.label,
                "default_model": t.default_model,
                "default_voice_by_language": {code: t.voice_for(code) for code in codes},
                "voice_listing": dict(t.voice_listing),
                "capabilities": dict(t.capabilities),
                "models": [
                    {
                        "id": m.id,
                        "label": m.label,
                        "description": m.description,
                        "chars_bundle_per_min": _chars_bundle(pricing, t.provider, m.id),
                        "price_per_min_usd": _price(pricing, "tts", t.provider, m.id),
                        "withdrawn": m.withdrawn,
                    }
                    for m in t.models
                    if include_withdrawn or not m.withdrawn
                ],
            }
        )
    return {
        "controls": [c.json() for c in cat.controls],
        "languages": [
            {
                "code": lang.code,
                "label": lang.label,
                "stt_default": cat.stt_default_for(lang.code),
                "tts_default": cat.tts_default_for(lang.code),
            }
            for lang in cat.languages
        ],
        "stt": stt_out,
        "tts": tts_out,
        "noise_cancellation": [
            {
                "provider": n.provider,
                "model": n.model,
                "label": n.label,
                "description": n.description,
                "default": n.default,
                "price_per_min_usd": _price(pricing, "nc", n.provider, n.model),
            }
            for n in cat.noise_cancellation
        ],
        "ambient_sounds": [
            {"id": sound_id, "label": label, "preview_url": None} for sound_id, label in cat.ambient_sounds
        ],
    }
