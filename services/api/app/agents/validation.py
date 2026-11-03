"""The one AgentConfig validator (T019, T093, T095; research R8 to R10, R20).

``validate_pure`` is synchronous and needs no database: structure and ranges (Pydantic models in
``schemas.py``), catalog membership (``llms`` and ``voices`` YAML joined with the 001 pricing
catalog), variables, greeting, webhook syntax and cross-field rules. ``agents.service.
validate_config`` wraps it with the database-backed parts (pricing catalog, uploaded ambient
files, webhook DNS, registered hooks).

Every problem is collected in one pass (SC-004) and classified:

* ``errors`` block save;
* ``publish_blockers`` allow save but block publish (unpriced or withdrawn components, missing
  references);
* ``warnings`` inform only.

Each issue carries a JSON Pointer into the config. Keyed list items use the key in brackets
(``/dynamic_variables[order_id]/default``). ``normalized_config`` has defaults filled, fixed
temperatures applied, foreign voices replaced, auto-detected variables added and empty
pronunciation rows dropped. When there are errors, each failing field carries its default in
``normalized_config`` so the document stays well-formed; it is only meaningful when ``valid``.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, TypeGuard

from pydantic import ValidationError

from app.agents import defaults, variables
from app.agents.hooks import SNAPSHOT_ONLY_BLOCKS
from app.agents.schemas import (
    CURRENT_SCHEMA_VERSION,
    AgentConfigV1,
    UnsupportedSchemaVersion,
    upcast,
)
from app.agents.webhook_url import check_syntax
from app.caller_language import options as caller_options
from app.llms.service import LlmCatalog
from app.llms.service import load_catalog as load_llm_catalog
from app.pricing import engine
from app.voices.catalog import VoiceCatalog
from app.voices.catalog import load_catalog as load_voice_catalog

Issue = dict[str, str]

LABELS: dict[str, str] = {
    "/schema_version": "Format version",
    "/type": "Agent type",
    "/language": "Language",
    "/llm": "Language model",
    "/llm/provider": "Model provider",
    "/llm/model": "Model",
    "/llm/temperature": "Temperature",
    "/prompt": "System prompt",
    "/begin_message": "Greeting",
    "/start_speaker": "Who speaks first",
    "/dynamic_variables": "Variables",
    "/dynamic_variables/*/name": "Variable name",
    "/dynamic_variables/*/default": "Default value",
    "/dynamic_variables/*/description": "Variable description",
    "/stt": "Speech recognition",
    "/stt/provider": "Speech recognition provider",
    "/stt/model": "Speech recognition model",
    "/tts": "Voice",
    "/tts/provider": "Voice provider",
    "/tts/model": "Voice model",
    "/tts/voice_id": "Voice",
    "/tts/speed": "Voice speed",
    "/tts/expressiveness": "Expressiveness",
    "/tts/volume": "Volume",
    "/noise_cancellation": "Noise cancellation",
    "/call_behavior/end_on_silence_s": "End call after silence",
    "/call_behavior/max_duration_s": "Maximum call duration",
    "/call_behavior/ring_duration_ms": "Ring time",
    "/call_behavior/interruption_sensitivity": "Interruption sensitivity",
    "/call_behavior/responsiveness": "Responsiveness",
    "/advanced/webhook_url": "Webhook address",
    "/advanced/webhook_timeout_ms": "Webhook timeout",
    "/advanced/voicemail_detection/action": "Voicemail action",
    "/advanced/voicemail_detection/message": "Voicemail message",
    "/advanced/dtmf/timeout_ms": "Keypad pause",
    "/advanced/dtmf/termination_key": "End key",
    "/advanced/dtmf/digits": "Digits to collect",
    "/advanced/background_audio/source": "Background sound",
    "/advanced/background_audio/volume": "Background volume",
    "/advanced/analysis_model": "Analysis model",
    "/advanced/pronunciation": "Pronunciation dictionary",
    "/advanced/pronunciation/*/word": "Word",
    "/advanced/pronunciation/*/replacement": "Pronunciation",
    "/advanced/recording": "Call recording",
    "/advanced/language_switching": "Caller language switching",
    "/advanced/language_switching/enabled": "Caller language switching",
    "/advanced/language_switching/languages": "Caller languages",
    "/tool_ids": "Tools",
    "/kb_ids": "Knowledge bases",
}
# Unit suffixes for range messages (the catalog ``controls`` carry the same units).
UNITS = {"s": " seconds", "ms": " ms", "x": "x"}


@dataclass
class ConfigValidationResult:
    valid: bool
    errors: list[Issue]
    publish_blockers: list[Issue]
    warnings: list[Issue]
    normalized_config: dict[str, Any]

    def json(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "publish_blockers": self.publish_blockers,
            "warnings": self.warnings,
            "normalized_config": self.normalized_config,
        }


@dataclass
class PureContext:
    pricing: engine.Catalog | None = None
    allow_http_webhook: bool = False
    previous_llm: tuple[str, str] | None = None
    workspace_id: str | None = None
    ambient_keys: frozenset[str] | None = None
    llm_catalog: LlmCatalog | None = None
    voice_catalog: VoiceCatalog | None = None


@dataclass
class _Collector:
    errors: list[Issue] = field(default_factory=list)
    publish_blockers: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    reset: list[tuple[Any, ...]] = field(default_factory=list)

    def error(self, pointer: str, code: str, message: str, reset: tuple[Any, ...] | None = None) -> None:
        self.errors.append({"pointer": pointer, "code": code, "message": message})
        if reset is not None:
            self.reset.append(reset)

    def blocker(self, pointer: str, code: str, message: str) -> None:
        self.publish_blockers.append({"pointer": pointer, "code": code, "message": message})

    def warn(self, pointer: str, code: str, message: str) -> None:
        self.warnings.append({"pointer": pointer, "code": code, "message": message})


# Helpers ----------------------------------------------------------------------------------


OTHER_RANGES: dict[str, tuple[int | float, int | float]] = {
    "/advanced/dtmf/digits": (1, 99),
    "/llm/temperature": (0, 2),
}


def _num(value: Any) -> str:
    """Readable number: thousands separators for whole numbers, no trailing zeros otherwise."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, Decimal):
        value = int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        return f"{int(value):,}"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _temp(value: float) -> str:
    return f"{value:.1f}" if round(value, 1) == value else f"{value:g}"


def _pattern(loc: tuple[Any, ...]) -> str:
    return "/" + "/".join("*" if isinstance(p, int) else str(p) for p in loc)


def label_for(loc: tuple[Any, ...]) -> str:
    pattern = _pattern(loc)
    if pattern in LABELS:
        return LABELS[pattern]
    last = next((str(p) for p in reversed(loc) if not isinstance(p, int)), "value")
    return last.replace("_", " ").capitalize()


def pointer_for(loc: tuple[Any, ...], raw: Mapping[str, Any]) -> str:
    """JSON Pointer for a location; items of keyed lists use their key in brackets."""
    parts: list[str] = []
    node: Any = raw
    i = 0
    loc = tuple(loc)
    while i < len(loc):
        part = loc[i]
        key_name = {"dynamic_variables": "name", "pronunciation": "word"}.get(str(part))
        if (
            key_name
            and i + 1 < len(loc)
            and isinstance(loc[i + 1], int)
            and isinstance(node, Mapping)
            and isinstance(node.get(part), list)
        ):
            items = node[part]
            index = loc[i + 1]
            item = items[index] if 0 <= index < len(items) else None
            key = item.get(key_name) if isinstance(item, Mapping) else None
            if isinstance(key, str) and key.strip():
                parts.append(f"{part}[{key}]")
            else:
                parts.extend([str(part), str(index)])
            node = item
            i += 2
            continue
        parts.append(str(part).replace("~", "~0").replace("/", "~1"))
        if isinstance(node, Mapping):
            node = node.get(part)
        elif isinstance(node, list) and isinstance(part, int) and 0 <= part < len(node):
            node = node[part]
        else:
            node = None
        i += 1
    return "/" + "/".join(parts)


_TYPE_MESSAGES = {
    "int_type": "Enter a whole number.",
    "int_parsing": "Enter a whole number.",
    "int_from_float": "Enter a whole number.",
    "float_type": "Enter a number.",
    "float_parsing": "Enter a number.",
    "string_type": "Enter text.",
    "bool_type": "Choose on or off.",
    "bool_parsing": "Choose on or off.",
    "list_type": "Expected a list.",
    "dict_type": "Expected an object.",
    "model_type": "Expected an object.",
    "model_attributes_type": "Expected an object.",
    "union_tag_invalid": "Choose a built-in sound or an uploaded file.",
    "union_tag_not_found": "Choose a built-in sound or an uploaded file.",
}


def _range_message(
    label: str, loc: tuple[Any, ...], vc: VoiceCatalog, etype: str, ctx: Mapping[str, Any]
) -> str:
    control = vc.control(_pattern(loc))
    if control is not None:
        unit = UNITS.get(control.unit or "", "")
        return f"{label} must be between {_num(control.min)} and {_num(control.max)}{unit}."
    if _pattern(loc) in OTHER_RANGES:
        low, high = OTHER_RANGES[_pattern(loc)]
        return f"{label} must be between {_num(low)} and {_num(high)}."
    if etype in {"string_too_short"} and ctx.get("min_length") == 1:
        return f"{label} is required."
    if etype == "string_too_long":
        return f"{label} can be at most {_num(ctx.get('max_length'))} characters."
    if etype == "string_too_short":
        return f"{label} must be at least {_num(ctx.get('min_length'))} characters."
    if etype == "too_long":
        return f"{label} can have at most {_num(ctx.get('max_length'))} entries."
    if etype == "too_short":
        return f"{label} needs at least {_num(ctx.get('min_length'))} entries."
    bounds = {"ge": "at least", "gt": "more than", "le": "at most", "lt": "less than"}
    for key, words in bounds.items():
        if key in ctx:
            return f"{label} must be {words} {_num(ctx[key])}."
    return f"{label} is out of range."


def _pydantic_issue(err: Mapping[str, Any], raw: Mapping[str, Any], vc: VoiceCatalog) -> Issue:
    loc = tuple(p for p in err.get("loc", ()) if p not in ("builtin", "upload"))
    etype = str(err.get("type", ""))
    ctx = err.get("ctx") or {}
    label = label_for(loc)
    pointer = pointer_for(loc, raw)
    if etype == "missing":
        return {"pointer": pointer, "code": "required", "message": f"{label} is required."}
    if etype == "extra_forbidden":
        return {"pointer": pointer, "code": "unknown_field", "message": "This setting is not recognised."}
    if etype in {
        "greater_than_equal",
        "less_than_equal",
        "greater_than",
        "less_than",
        "string_too_long",
        "string_too_short",
        "too_long",
        "too_short",
    }:
        if etype == "string_too_short" and ctx.get("min_length") == 1:
            return {"pointer": pointer, "code": "required", "message": f"{label} is required."}
        return {
            "pointer": pointer,
            "code": "out_of_range",
            "message": _range_message(label, loc, vc, etype, ctx),
        }
    if etype == "literal_error":
        expected = str(ctx.get("expected", "")).replace("'", "")
        return {
            "pointer": pointer,
            "code": "invalid_format",
            "message": f"{label} must be one of {expected}.",
        }
    if etype == "string_pattern_mismatch":
        if loc and loc[-1] == "name" and "dynamic_variables" in loc:
            return {
                "pointer": pointer,
                "code": "invalid_variable",
                "message": "Variable names start with a letter or underscore and use only letters, digits "
                "and underscores (max 64).",
            }
        return {
            "pointer": pointer,
            "code": "invalid_format",
            "message": f"{label} is not in the expected format.",
        }
    message = _TYPE_MESSAGES.get(etype, f"{label} is not valid.")
    return {"pointer": pointer, "code": "invalid_format", "message": message}


def _get(node: Any, *path: Any) -> Any:
    for part in path:
        if isinstance(node, Mapping):
            node = node.get(part)
        elif isinstance(node, list) and isinstance(part, int) and 0 <= part < len(node):
            node = node[part]
        else:
            return None
    return node


def _set(node: Any, path: tuple[Any, ...], value: Any) -> None:
    for part in path[:-1]:
        node = node[part]
    node[path[-1]] = value


def _is_text(value: Any) -> TypeGuard[str]:
    return isinstance(value, str)


# Defaults overlay -------------------------------------------------------------------------


def _deep_fill(target: dict[str, Any], base: Mapping[str, Any]) -> None:
    """Fill keys missing from ``target`` with ``base`` values, recursing into objects present
    in both. Explicit values (including ``None``) are kept."""
    for key, value in base.items():
        if key not in target:
            target[key] = copy.deepcopy(value)
        elif isinstance(target[key], dict) and isinstance(value, Mapping):
            _deep_fill(target[key], value)


def fill_defaults(
    config: Mapping[str, Any], agent_type: str, vc: VoiceCatalog | None = None
) -> dict[str, Any]:
    """Overlay ``config`` on the platform defaults for its language and type.

    Provider-aware: a ``tts`` block naming another provider is completed with that provider's
    default model and the language's default voice, not the default provider's values.
    """
    vc = vc or load_voice_catalog()
    out = copy.deepcopy(dict(config))
    language = out.get("language") if _is_text(out.get("language")) and out.get("language") else None
    language = language or defaults.DEFAULT_LANGUAGE
    base = defaults.default_config(agent_type, language)
    tts = out.get("tts")
    if isinstance(tts, dict) and _is_text(tts.get("provider")) and tts["provider"] != base["tts"]["provider"]:
        if vc.tts_provider(tts["provider"]) is not None:
            base["tts"] = defaults.tts_defaults(language, tts["provider"])
    stt = out.get("stt")
    if isinstance(stt, dict) and _is_text(stt.get("provider")) and "model" not in stt:
        stt["model"] = None
    _deep_fill(out, base)
    return out


# Main ---------------------------------------------------------------------------------------


def _check_llm(
    cfg: dict[str, Any], ctx: PureContext, lc: LlmCatalog, out: _Collector, *, pointer: str, analysis: bool
) -> None:
    block = _get(cfg, *pointer.strip("/").split("/"))
    if not isinstance(block, dict):
        return
    provider, model_id = block.get("provider"), block.get("model")
    if not (_is_text(provider) and _is_text(model_id) and provider and model_id):
        return
    label = "analysis model" if analysis else "model"
    if not lc.has_provider(provider):
        out.error(
            f"{pointer}/provider", "not_in_catalog", f"The {label} provider {provider!r} is not offered."
        )
        return
    model = lc.model(provider, model_id)
    if model is None:
        out.error(f"{pointer}/model", "not_in_catalog", f"{model_id!r} is not offered by {provider}.")
        return
    if model.withdrawn:
        out.blocker(
            f"{pointer}/model", "withdrawn", f"{model.label} is no longer offered. Choose another model."
        )
    if ctx.pricing is not None and ctx.pricing.lookup("llm", provider, model_id) is None:
        out.blocker(f"{pointer}/model", "unpriced", f"{model.label} has no price yet, so it cannot go live.")
    if analysis:
        return
    rule = model.temperature
    temp = block.get("temperature")
    if not isinstance(temp, int | float) or isinstance(temp, bool):
        return
    if rule.is_fixed:
        assert rule.fixed is not None
        if float(temp) != rule.fixed:
            block["temperature"] = rule.fixed
            out.warn(
                f"{pointer}/temperature",
                "temperature_fixed",
                f"{model.label} only supports temperature {_temp(rule.fixed)}; "
                f"it was set to {_temp(rule.fixed)}.",
            )
        return
    assert rule.min is not None and rule.max is not None
    if rule.min <= float(temp) <= rule.max:
        return
    changed = ctx.previous_llm is not None and ctx.previous_llm != (provider, model_id)
    if changed:
        clamped = min(max(float(temp), rule.min), rule.max)
        block["temperature"] = clamped
        out.warn(
            f"{pointer}/temperature",
            "temperature_clamped",
            f"Temperature was set to {_temp(clamped)} to fit {model.label}'s range.",
        )
    else:
        out.error(
            f"{pointer}/temperature",
            "out_of_range",
            f"Temperature must be between {_temp(rule.min)} and {_temp(rule.max)} for {model.label}.",
            reset=("llm", "temperature"),
        )


def _check_speech(cfg: dict[str, Any], ctx: PureContext, vc: VoiceCatalog, out: _Collector) -> None:
    raw_language = cfg.get("language")
    language: str = raw_language if isinstance(raw_language, str) else ""
    lang_obj = vc.language(language) if language else None
    lang_ok = lang_obj is not None
    if language and not lang_ok:
        out.error(
            "/language", "not_in_catalog", f"The language {language!r} is not offered.", reset=("language",)
        )
    stt = cfg.get("stt")
    if isinstance(stt, dict) and _is_text(stt.get("provider")) and stt["provider"]:
        provider = vc.stt_provider(stt["provider"])
        model_id = stt.get("model")
        if provider is None:
            out.error(
                "/stt/provider",
                "not_in_catalog",
                f"The speech recognition provider {stt['provider']!r} is not offered.",
            )
        elif model_id is None and not provider.supports_auto:
            choices = provider.models_for_language(language) if lang_ok else []
            if len(choices) == 1:
                stt["model"] = choices[0].id
            elif provider.default_model:
                stt["model"] = provider.default_model
            else:
                out.error("/stt/model", "required", "Choose a speech recognition model.")
        elif _is_text(model_id) and provider.model(model_id) is None:
            out.error("/stt/model", "not_in_catalog", f"{model_id!r} is not offered by {provider.label}.")
        if provider is not None:
            model_id = stt.get("model")
            model = provider.model(model_id) if _is_text(model_id) else None
            if model is not None and model.withdrawn:
                out.blocker(
                    "/stt/model", "withdrawn", f"{model.label} is no longer offered. Choose another model."
                )
            known = model_id is None or model is not None
            model_key = model_id if isinstance(model_id, str) else None
            if known and lang_obj is not None and not provider.covers(model_key, language):
                name = model.label if model is not None else f"{provider.label} Auto"
                out.error(
                    "/stt/model", "stt_language_unsupported", f"{name} does not support {lang_obj.label}."
                )
            if (
                known
                and ctx.pricing is not None
                and ctx.pricing.lookup("stt", provider.provider, model_key) is None
            ):
                out.blocker(
                    "/stt/model", "unpriced", f"{provider.label} speech recognition has no price yet."
                )
    tts = cfg.get("tts")
    if isinstance(tts, dict) and _is_text(tts.get("provider")) and tts["provider"]:
        provider_t = vc.tts_provider(tts["provider"])
        if provider_t is None:
            out.error(
                "/tts/provider", "not_in_catalog", f"The voice provider {tts['provider']!r} is not offered."
            )
        else:
            model_id = tts.get("model")
            if _is_text(model_id) and model_id:
                model_t = provider_t.model(model_id)
                if model_t is None:
                    out.error(
                        "/tts/model", "not_in_catalog", f"{model_id!r} is not offered by {provider_t.label}."
                    )
                else:
                    if model_t.withdrawn:
                        out.blocker(
                            "/tts/model",
                            "withdrawn",
                            f"{model_t.label} is no longer offered. Choose another.",
                        )
                    if (
                        ctx.pricing is not None
                        and ctx.pricing.lookup("tts", provider_t.provider, model_id) is None
                    ):
                        out.blocker(
                            "/tts/model",
                            "unpriced",
                            f"{model_t.label} has no price yet, so it cannot go live.",
                        )
            voice = tts.get("voice_id")
            if _is_text(voice) and voice.strip() and not provider_t.owns_voice(voice):
                replacement = provider_t.voice_for(language if lang_ok else defaults.DEFAULT_LANGUAGE)
                tts["voice_id"] = replacement
                name = provider_t.curated_name(replacement) or replacement
                out.warn(
                    "/tts/voice_id",
                    "component_replaced",
                    f"The voice does not belong to {provider_t.label}; {name} was chosen instead.",
                )
    nc = cfg.get("noise_cancellation")
    if isinstance(nc, dict) and _is_text(nc.get("provider")) and _is_text(nc.get("model")):
        option = vc.nc_option(nc["provider"], nc["model"])
        if option is None:
            out.error(
                "/noise_cancellation", "not_in_catalog", "This noise cancellation option is not offered."
            )
        elif ctx.pricing is not None and ctx.pricing.lookup("nc", option.provider, option.model) is None:
            out.blocker("/noise_cancellation", "unpriced", f"{option.label} has no price yet.")


def _check_variables(cfg: dict[str, Any], agent_type: str, out: _Collector) -> None:
    texts: list[str | None] = []
    prompt, greeting = cfg.get("prompt"), cfg.get("begin_message")
    texts.extend(t for t in (prompt, greeting) if _is_text(t))
    if agent_type == "flow" and isinstance(cfg.get("flow"), dict):
        texts.extend(_strings(cfg["flow"]))
    found = variables.extract(texts)
    for raw in found.invalid:
        out.warn("/prompt", "invalid_variable", f"{raw} is not a valid variable placeholder and is ignored.")
    declared = cfg.get("dynamic_variables")
    if not isinstance(declared, list):
        return
    names = [v.get("name") for v in declared if isinstance(v, dict)]
    for name in found.names:
        if not variables.is_reserved(name) and name not in names:
            declared.append({"name": name, "default": None})
            names.append(name)
    seen: set[str] = set()
    for item in declared:
        if not isinstance(item, dict) or not _is_text(item.get("name")):
            continue
        name = item["name"]
        pointer = f"/dynamic_variables[{name}]/name"
        if name in seen:
            out.error(pointer, "duplicate_entry", f"The variable {name} is listed more than once.")
        seen.add(name)
        if variables.is_valid_name(name) and variables.is_reserved(name):
            out.error(pointer, "reserved_variable", f"{name} is a built-in variable and cannot be declared.")
            continue
        default = item.get("default")
        if default is None or (_is_text(default) and not default.strip()):
            out.warn(
                f"/dynamic_variables[{name}]/default",
                "variable_without_default",
                f"{name} has no default; calls must supply a value.",
            )
        elif name not in found.names:
            out.warn(
                f"/dynamic_variables[{name}]/default",
                "unused_default",
                f"{name} has a default but is not used in the prompt or greeting.",
            )


def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, Mapping):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


def _check_text_rules(cfg: dict[str, Any], agent_type: str, ctx: PureContext, out: _Collector) -> None:
    prompt = cfg.get("prompt")
    if agent_type == "single_prompt" and _is_text(prompt) and not prompt.strip():
        out.error("/prompt", "required", "Write the system prompt.")
    greeting = cfg.get("begin_message")
    speaker = cfg.get("start_speaker")
    has_greeting = _is_text(greeting) and bool(greeting.strip())
    if speaker == "agent" and not has_greeting:
        out.warn(
            "/begin_message",
            "generated_greeting",
            "No greeting: the agent writes its opening line from the prompt.",
        )
    if speaker == "user" and has_greeting:
        out.warn(
            "/begin_message",
            "greeting_unused",
            "The greeting is kept but not spoken while the caller speaks first.",
        )
    if agent_type == "single_prompt" and cfg.get("flow") is not None:
        out.error("/flow", "invalid_format", "Only flow agents have a flow.", reset=("flow",))
    advanced = cfg.get("advanced")
    if not isinstance(advanced, dict):
        return
    url = advanced.get("webhook_url")
    if _is_text(url):
        if not url.strip():
            advanced["webhook_url"] = None
        else:
            issue = check_syntax(url, allow_http=ctx.allow_http_webhook)
            if issue is not None:
                out.error(
                    "/advanced/webhook_url", issue.code, issue.message, reset=("advanced", "webhook_url")
                )
    vm = advanced.get("voicemail_detection")
    if isinstance(vm, dict) and vm.get("enabled") is True and vm.get("action") == "leave_message":
        message = vm.get("message")
        if not (_is_text(message) and message.strip()):
            out.error(
                "/advanced/voicemail_detection/message",
                "required",
                "Write the message to leave on voicemail.",
            )
    bg = advanced.get("background_audio")
    if isinstance(bg, dict):
        source = bg.get("source")
        if bg.get("enabled") is True and source is None:
            out.error("/advanced/background_audio/source", "required", "Choose a background sound.")
        if isinstance(source, dict) and source.get("kind") == "builtin" and _is_text(source.get("id")):
            if source["id"] not in (ctx.voice_catalog or load_voice_catalog()).ambient_ids():
                out.error(
                    "/advanced/background_audio/source",
                    "not_in_catalog",
                    "This built-in sound is not offered.",
                    reset=("advanced", "background_audio", "source"),
                )
        if isinstance(source, dict) and source.get("kind") == "upload" and _is_text(source.get("key")):
            key = source["key"]
            if ctx.workspace_id is not None and not key.startswith(f"workspaces/{ctx.workspace_id}/ambient/"):
                out.error(
                    "/advanced/background_audio/source",
                    "missing_reference",
                    "This uploaded sound does not belong to this workspace.",
                    reset=("advanced", "background_audio", "source"),
                )
            elif ctx.ambient_keys is not None and key not in ctx.ambient_keys:
                out.blocker(
                    "/advanced/background_audio/source",
                    "missing_reference",
                    "This uploaded sound was deleted.",
                )
    entries = advanced.get("pronunciation")
    if isinstance(entries, list):
        words: set[str] = set()
        for entry in entries:
            if isinstance(entry, dict) and _is_text(entry.get("word")):
                folded = entry["word"].strip().casefold()
                if folded in words:
                    out.error(
                        f"/advanced/pronunciation[{entry['word']}]/word",
                        "duplicate_entry",
                        f"{entry['word']} is listed more than once.",
                    )
                words.add(folded)


def _check_language_switching(cfg: dict[str, Any], vc: VoiceCatalog, out: _Collector) -> None:
    """012: listed caller languages must be offered; ones the agent's speech recognition and
    voice cannot handle are kept with a warning (they come back when the voice changes)."""
    switching = _get(cfg, "advanced", "language_switching")
    if not isinstance(switching, dict) or not isinstance(switching.get("languages"), list):
        return
    pointer = "/advanced/language_switching/languages"
    codes = switching["languages"]
    supported: set[str] | None = None
    seen: set[str] = set()
    for code in codes:
        if not _is_text(code):
            continue
        lang = vc.language(code)
        if lang is None or code == "multi":
            out.error(pointer, "not_in_catalog", f"The language {code!r} is not offered.")
            continue
        if code in seen:
            out.error(pointer, "duplicate_entry", f"{lang.label} is listed more than once.")
            continue
        seen.add(code)
        if supported is None:
            supported = caller_options.supported_codes(cfg, vc)
        if code not in supported:
            out.warn(
                pointer,
                "language_unsupported",
                f"{lang.label} is not supported by this agent's speech recognition and voice, "
                "so callers cannot switch to it.",
            )


def _drop_empty_pronunciation(cfg: dict[str, Any]) -> None:
    entries = _get(cfg, "advanced", "pronunciation")
    if not isinstance(entries, list):
        return
    kept = []
    for entry in entries:
        if isinstance(entry, dict):
            word, repl = entry.get("word"), entry.get("replacement")
            if (word is None or (_is_text(word) and not word.strip())) or (
                repl is None or (_is_text(repl) and not repl.strip())
            ):
                continue
            if _is_text(word):
                entry["word"] = word.strip()
            if _is_text(repl):
                entry["replacement"] = repl.strip()
        kept.append(entry)
    cfg["advanced"]["pronunciation"] = kept


def _reset_paths(cfg: dict[str, Any], paths: list[tuple[Any, ...]], agent_type: str, language: str) -> None:
    """Make failing locations well-formed: list items are dropped, unknown keys removed, and
    other values replaced by the nearest default."""
    base = defaults.default_config(agent_type, language)
    removals: dict[tuple[Any, ...], set[int]] = {}
    for loc in paths:
        if not loc:
            continue
        index_at = next((i for i, part in enumerate(loc) if isinstance(part, int)), None)
        if index_at is not None:
            removals.setdefault(tuple(loc[:index_at]), set()).add(loc[index_at])
            continue
        path = tuple(loc)
        while path:
            parent = cfg if len(path) == 1 else _get(cfg, *path[:-1])
            if _has(base, path):
                if isinstance(parent, dict):
                    parent[path[-1]] = copy.deepcopy(_get(base, *path))
                    break
            elif isinstance(base if len(path) == 1 else _get(base, *path[:-1]), Mapping):
                if isinstance(parent, dict):
                    parent.pop(path[-1], None)
                break
            path = path[:-1]
    for list_path, indexes in removals.items():
        items = _get(cfg, *list_path)
        if isinstance(items, list):
            _set(cfg, list_path, [item for i, item in enumerate(items) if i not in indexes])


def _has(base: Any, path: tuple[Any, ...]) -> bool:
    node = base
    for part in path:
        if not isinstance(node, Mapping) or part not in node:
            return False
        node = node[part]
    return True


def validate_pure(agent_type: str, config: Any, ctx: PureContext | None = None) -> ConfigValidationResult:
    """Validate and normalise ``config`` for an agent of ``agent_type`` (no I/O)."""
    ctx = ctx or PureContext()
    lc = ctx.llm_catalog or load_llm_catalog()
    vc = ctx.voice_catalog or load_voice_catalog()
    out = _Collector()
    if not isinstance(config, Mapping):
        out.error("", "invalid_format", "The configuration must be an object.")
        normalized = defaults.default_config(agent_type)
        return ConfigValidationResult(False, out.errors, [], [], normalized)
    raw = {k: v for k, v in copy.deepcopy(dict(config)).items() if k not in SNAPSHOT_ONLY_BLOCKS}
    if "schema_version" not in raw:
        raw["schema_version"] = CURRENT_SCHEMA_VERSION
    try:
        raw = upcast(raw)
    except UnsupportedSchemaVersion as exc:
        out.error("/schema_version", "invalid_format", str(exc))
        raw["schema_version"] = CURRENT_SCHEMA_VERSION
    raw["type"] = agent_type
    cfg = fill_defaults(raw, agent_type, vc)
    if isinstance(cfg.get("advanced"), dict) and isinstance(cfg["advanced"].get("pronunciation"), list):
        _drop_empty_pronunciation(cfg)

    _check_llm(cfg, ctx, lc, out, pointer="/llm", analysis=False)
    _check_llm(cfg, ctx, lc, out, pointer="/advanced/analysis_model", analysis=True)
    _check_speech(cfg, ctx, vc, out)
    _check_variables(cfg, agent_type, out)
    _check_text_rules(cfg, agent_type, ctx, out)
    _check_language_switching(cfg, vc, out)

    model: AgentConfigV1 | None = None
    try:
        model = AgentConfigV1.model_validate(cfg)
    except ValidationError as exc:
        seen = {(e["pointer"], e["code"]) for e in out.errors}
        for err in exc.errors():
            issue = _pydantic_issue(err, cfg, vc)
            if (issue["pointer"], issue["code"]) not in seen:
                out.errors.append(issue)
                seen.add((issue["pointer"], issue["code"]))
            loc = tuple(p for p in err.get("loc", ()) if p not in ("builtin", "upload"))
            out.reset.append(loc)

    language = cfg.get("language") if _is_text(cfg.get("language")) else defaults.DEFAULT_LANGUAGE
    if model is not None and not out.errors:
        normalized = model.model_dump(mode="json")
    else:
        normalized = _normalize_with_errors(cfg, out.reset, agent_type, str(language), vc)
    return ConfigValidationResult(
        valid=not out.errors,
        errors=out.errors,
        publish_blockers=out.publish_blockers,
        warnings=out.warnings,
        normalized_config=normalized,
    )


def _normalize_with_errors(
    cfg: dict[str, Any], resets: list[tuple[Any, ...]], agent_type: str, language: str, vc: VoiceCatalog
) -> dict[str, Any]:
    if vc.language(language) is None:
        language = defaults.DEFAULT_LANGUAGE
    working = copy.deepcopy(cfg)
    _reset_paths(working, resets, agent_type, language)
    for _ in range(3):
        try:
            return AgentConfigV1.model_validate(working).model_dump(mode="json")
        except ValidationError as exc:
            locs = [
                tuple(p for p in e.get("loc", ()) if p not in ("builtin", "upload")) for e in exc.errors()
            ]
            _reset_paths(working, locs, agent_type, language)
    return defaults.default_config(agent_type, language)


# Overrides (FR-047, T104) ---------------------------------------------------------------------


def validate_override(path: str, value: Any, vc: VoiceCatalog | None = None) -> list[Issue]:
    """Validate one tunable setting against the shared ``controls`` table.

    ``path`` is a JSON Pointer (``/tts/speed``) or dotted path (``tts.speed``). Returns an empty
    list when ``value`` is a number inside the control's range; unknown paths are refused so a
    caller never invents its own range.
    """
    vc = vc or load_voice_catalog()
    control = vc.control(path)
    pointer = path if path.startswith("/") else "/" + path.replace(".", "/")
    if control is None:
        return [
            {"pointer": pointer, "code": "not_in_catalog", "message": "This setting cannot be overridden."}
        ]
    if isinstance(value, bool) or not isinstance(value, int | float):
        return [{"pointer": pointer, "code": "invalid_format", "message": "Enter a number."}]
    number = Decimal(str(value))
    if number < control.min or number > control.max:
        unit = UNITS.get(control.unit or "", "")
        return [
            {
                "pointer": pointer,
                "code": "out_of_range",
                "message": f"{control.label} must be between {_num(control.min)} and "
                f"{_num(control.max)}{unit}.",
            }
        ]
    return []


def clamp_override(path: str, value: float, vc: VoiceCatalog | None = None) -> float:
    """Clamp ``value`` into the control's range and snap it to the nearest step."""
    vc = vc or load_voice_catalog()
    control = vc.control(path)
    if control is None:
        raise KeyError(path)
    number = min(max(Decimal(str(value)), control.min), control.max)
    steps = ((number - control.min) / control.step).to_integral_value()
    snapped = min(control.min + steps * control.step, control.max)
    return float(snapped)
