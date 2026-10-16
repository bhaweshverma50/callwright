"""validate_config classification (T009, T093, T095; research R8, R10)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.agents import hooks
from app.agents.checks import validate_config
from app.agents.defaults import default_config
from app.agents.validation import PureContext, validate_pure
from app.llms.service import load_catalog as llm_catalog
from app.llms.service import parse_catalog
from app.pricing import engine
from app.voices.catalog import load_catalog as voice_catalog

FULL_PRICING = engine.Catalog(
    version=1,
    effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    rates=(
        engine.Rate("stt", "deepgram", None, "Auto", Decimal("0.0085")),
        engine.Rate("stt", "sarvam", None, "Auto", Decimal("0.006")),
        engine.Rate("llm", "azure_openai", "gpt-5.1", "GPT-5.1", Decimal("0.0165")),
        engine.Rate("tts", "elevenlabs", "eleven_flash_v2_5", "Flash", Decimal("0.045")),
        engine.Rate("tts", "cartesia", "sonic-2", "Sonic 2", Decimal("0.0275")),
        engine.Rate("nc", "sanas", "vi", "VI", Decimal("0")),
    ),
)


def cfg(**top: Any) -> dict[str, Any]:
    base = default_config("single_prompt")
    base["prompt"] = "You help callers."
    base.update(top)
    return base


def issues(result: Any, kind: str) -> dict[str, str]:
    return {i["pointer"]: i["code"] for i in getattr(result, kind)}


def test_clean_config_has_no_issues_with_prices() -> None:
    result = validate_pure("single_prompt", cfg(), PureContext(pricing=FULL_PRICING))
    assert result.valid and result.publish_blockers == [] and result.errors == []


def test_fixed_temperature_normalised_with_warning() -> None:
    result = validate_pure(
        "single_prompt", cfg(llm={"provider": "openai", "model": "gpt-5.2", "temperature": 0.3})
    )
    assert result.valid
    assert result.normalized_config["llm"]["temperature"] == 1.0
    assert issues(result, "warnings")["/llm/temperature"] == "temperature_fixed"


def test_ranged_temperature_out_of_range_is_error_and_clamped_on_model_change() -> None:
    ranged = parse_catalog(
        {
            "default": {"provider": "azure_openai", "model": "gpt-5.1"},
            "providers": [{"id": "azure_openai", "label": "Azure"}],
            "models": [
                {
                    "id": "gpt-5.1",
                    "label": "GPT-5.1",
                    "providers": ["azure_openai"],
                    "temperature": {"fixed": 1.0},
                },
                {
                    "id": "narrow",
                    "label": "Narrow",
                    "providers": ["azure_openai"],
                    "temperature": {"min": 0, "max": 1, "step": 0.1, "default": 0.5},
                },
            ],
        }
    )
    config = cfg(llm={"provider": "azure_openai", "model": "narrow", "temperature": 1.6})
    same = validate_pure(
        "single_prompt", config, PureContext(llm_catalog=ranged, previous_llm=("azure_openai", "narrow"))
    )
    assert issues(same, "errors")["/llm/temperature"] == "out_of_range"
    changed = validate_pure(
        "single_prompt", config, PureContext(llm_catalog=ranged, previous_llm=("azure_openai", "gpt-5.1"))
    )
    assert changed.valid
    assert changed.normalized_config["llm"]["temperature"] == 1.0
    assert issues(changed, "warnings")["/llm/temperature"] == "temperature_clamped"


def test_unknown_catalog_entries_are_errors() -> None:
    result = validate_pure(
        "single_prompt",
        cfg(
            language="xx",
            llm={"provider": "acme", "model": "gpt-5.1", "temperature": 1},
            stt={"provider": "deepgram", "model": "nova-9"},
            tts={"provider": "elevenlabs", "model": "eleven_v9", "voice_id": "EXAVITQu4vr4xnSDxMaL"},
            noise_cancellation={"provider": "sanas", "model": "zz"},
        ),
    )
    errors = issues(result, "errors")
    assert errors["/language"] == "not_in_catalog"
    assert errors["/llm/provider"] == "not_in_catalog"
    assert errors["/stt/model"] == "not_in_catalog"
    assert errors["/tts/model"] == "not_in_catalog"
    assert errors["/noise_cancellation"] == "not_in_catalog"


def test_unpriced_components_are_publish_blockers() -> None:
    config = cfg(
        llm={"provider": "openai", "model": "gpt-5.2", "temperature": 1.0},
        tts={"provider": "fishaudio", "model": "s1", "voice_id": "933563129e564b19a115bedd57b7406a"},
        noise_cancellation={"provider": "ai_coustics", "model": "standard"},
    )
    result = validate_pure("single_prompt", config, PureContext(pricing=FULL_PRICING))
    assert result.valid
    blockers = issues(result, "publish_blockers")
    assert blockers == {"/llm/model": "unpriced", "/tts/model": "unpriced", "/noise_cancellation": "unpriced"}


def test_withdrawn_model_is_publish_blocker() -> None:
    lc = llm_catalog()
    withdrawn = replace(lc, models=tuple(replace(m, withdrawn=m.id == "gpt-5.2") for m in lc.models))
    result = validate_pure(
        "single_prompt",
        cfg(llm={"provider": "openai", "model": "gpt-5.2", "temperature": 1.0}),
        PureContext(llm_catalog=withdrawn),
    )
    assert result.valid
    assert issues(result, "publish_blockers") == {"/llm/model": "withdrawn"}


def test_voice_of_another_provider_replaced() -> None:
    result = validate_pure(
        "single_prompt",
        cfg(
            language="de",
            tts={"provider": "cartesia", "model": "sonic-2", "voice_id": "EXAVITQu4vr4xnSDxMaL"},
        ),
    )
    assert result.valid
    assert result.normalized_config["tts"]["voice_id"] == "ac197a78-cec7-4c50-93e5-93bdc1910b11"
    assert issues(result, "warnings")["/tts/voice_id"] == "component_replaced"


def test_curated_provider_requires_listed_voice() -> None:
    result = validate_pure(
        "single_prompt", cfg(tts={"provider": "fishaudio", "model": "s1", "voice_id": "0" * 32})
    )
    assert result.normalized_config["tts"]["voice_id"] == "933563129e564b19a115bedd57b7406a"


def test_provider_switch_fills_provider_defaults() -> None:
    result = validate_pure("single_prompt", cfg(language="ja", tts={"provider": "fishaudio"}))
    assert result.valid
    assert result.normalized_config["tts"]["model"] == "s2.1-pro"
    assert result.normalized_config["tts"]["voice_id"] == "5161d41404314212af1254556477c17d"


def test_stt_model_must_cover_language() -> None:
    result = validate_pure(
        "single_prompt", cfg(language="fr", stt={"provider": "deepgram", "model": "flux-general-en"})
    )
    assert issues(result, "errors")["/stt/model"] == "stt_language_unsupported"
    auto = validate_pure("single_prompt", cfg(language="fr", stt={"provider": "sarvam", "model": None}))
    assert issues(auto, "errors")["/stt/model"] == "stt_language_unsupported"
    ok = validate_pure("single_prompt", cfg(language="fr", stt={"provider": "deepgram", "model": None}))
    assert ok.valid


def test_single_model_stt_auto_selected() -> None:
    vc = voice_catalog()
    sarvam = vc.stt_provider("sarvam")
    assert sarvam is not None
    no_auto = replace(sarvam, supports_auto=False, models=sarvam.models[:1])
    patched = replace(vc, stt=(*[p for p in vc.stt if p.provider != "sarvam"], no_auto))
    result = validate_pure(
        "single_prompt",
        cfg(language="hi", stt={"provider": "sarvam", "model": None}),
        PureContext(voice_catalog=patched),
    )
    assert result.valid
    assert result.normalized_config["stt"]["model"] == "saarika:v2.5"


def test_greeting_warnings() -> None:
    empty = validate_pure("single_prompt", cfg(begin_message="", start_speaker="agent"))
    assert issues(empty, "warnings")["/begin_message"] == "generated_greeting"
    unused = validate_pure("single_prompt", cfg(start_speaker="user"))
    assert unused.valid
    assert issues(unused, "warnings")["/begin_message"] == "greeting_unused"
    assert unused.normalized_config["begin_message"] == "Hi, thanks for calling. How can I help you today?"
    silent = validate_pure("single_prompt", cfg(start_speaker="user", begin_message=None))
    assert "/begin_message" not in issues(silent, "warnings")


def test_voicemail_message_required() -> None:
    config = cfg()
    config["advanced"]["voicemail_detection"] = {"enabled": True, "action": "leave_message", "message": " "}
    result = validate_pure("single_prompt", config)
    assert issues(result, "errors")["/advanced/voicemail_detection/message"] == "required"


def test_background_audio_rules() -> None:
    config = cfg()
    config["advanced"]["background_audio"] = {"enabled": True, "source": None, "volume": 0.8}
    assert (
        issues(validate_pure("single_prompt", config), "errors")["/advanced/background_audio/source"]
        == "required"
    )
    config["advanced"]["background_audio"]["source"] = {"kind": "builtin", "id": "jungle"}
    assert (
        issues(validate_pure("single_prompt", config), "errors")["/advanced/background_audio/source"]
        == "not_in_catalog"
    )
    config["advanced"]["background_audio"]["source"] = {
        "kind": "upload",
        "key": "workspaces/ws_B/ambient/x.mp3",
    }
    other = validate_pure("single_prompt", config, PureContext(workspace_id="ws_A"))
    assert issues(other, "errors")["/advanced/background_audio/source"] == "missing_reference"
    config["advanced"]["background_audio"]["source"] = {
        "kind": "upload",
        "key": "workspaces/ws_A/ambient/x.mp3",
    }
    gone = validate_pure("single_prompt", config, PureContext(workspace_id="ws_A", ambient_keys=frozenset()))
    assert gone.valid and issues(gone, "publish_blockers") == {
        "/advanced/background_audio/source": "missing_reference"
    }


def test_pronunciation_rows() -> None:
    config = cfg()
    config["advanced"]["pronunciation"] = [
        {"word": "SQL", "replacement": "sequel"},
        {"word": " ", "replacement": "x"},
        {"word": "nginx", "replacement": ""},
        {"word": "sql", "replacement": "S Q L"},
    ]
    result = validate_pure("single_prompt", config)
    assert issues(result, "errors") == {"/advanced/pronunciation[sql]/word": "duplicate_entry"}
    config["advanced"]["pronunciation"].pop()
    ok = validate_pure("single_prompt", config)
    assert ok.normalized_config["advanced"]["pronunciation"] == [{"word": "SQL", "replacement": "sequel"}]


def test_flow_block_only_for_flow_agents() -> None:
    result = validate_pure("single_prompt", cfg(flow={"graph": {}}))
    assert issues(result, "errors")["/flow"] == "invalid_format"


def test_webhook_url_checks() -> None:
    config = cfg()
    config["advanced"]["webhook_url"] = "https://10.0.0.1/x"
    assert (
        issues(validate_pure("single_prompt", config), "errors")["/advanced/webhook_url"] == "private_address"
    )
    config["advanced"]["webhook_url"] = "  "
    assert validate_pure("single_prompt", config).normalized_config["advanced"]["webhook_url"] is None


async def test_hook_results_merged() -> None:
    def tools_validator(ctx: hooks.HookContext) -> hooks.HookIssues:
        missing = [t for t in ctx.value or [] if t != "tool_ok"]
        return hooks.HookIssues(
            publish_blockers=[
                {"pointer": f"/tool_ids[{t}]", "code": "missing_reference", "message": "gone"}
                for t in missing
            ]
        )

    async def evals_validator(ctx: hooks.HookContext) -> hooks.HookIssues:
        return hooks.HookIssues(errors=[{"pointer": "/evals", "code": "invalid_format", "message": "bad"}])

    with hooks.registered(validators={"tool_ids": tools_validator, "evals": evals_validator}):
        result = await validate_config("single_prompt", cfg(tool_ids=["tool_ok", "tool_gone"]))
    assert issues(result, "publish_blockers") == {"/tool_ids[tool_gone]": "missing_reference"}
    assert issues(result, "errors") == {"/evals": "invalid_format"}
    assert not result.valid
    clean = await validate_config("single_prompt", cfg(tool_ids=["tool_gone"]))
    assert clean.valid and clean.publish_blockers == []
