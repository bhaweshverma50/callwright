"""Which languages an agent offers callers (012) and the agent setting's validation."""

from __future__ import annotations

from typing import Any

from app.agents.defaults import default_config
from app.agents.schemas import upcast
from app.agents.validation import validate_pure
from app.caller_language.options import language_options, supported_codes


def config(**top: Any) -> dict[str, Any]:
    base = default_config("single_prompt")
    base["prompt"] = "You help callers."
    for key, value in top.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


def codes(cfg: dict[str, Any]) -> list[str]:
    return [o["code"] for o in language_options(cfg)]


def test_default_agent_offers_one_code_per_language_with_its_own_first() -> None:
    options = language_options(config())
    assert options[0] == {
        "code": "en-US",
        "label": "English (US)",
        "stt_model": "nova-3",
        "tts_model": "eleven_multilingual_v2",
    }
    found = codes(config())
    assert {"hi", "es", "fr", "de", "pt", "ja", "zh"} <= set(found)
    assert not [c for c in found[1:] if c.startswith("en")]
    assert "hi-Latn" not in found and "es-419" not in found
    assert "he" not in found  # Nova-3 hears Hebrew but Multilingual v2 does not speak it
    hindi = next(o for o in options if o["code"] == "hi")
    assert hindi["stt_model"] == "nova-2" and hindi["tts_model"] == "eleven_multilingual_v2"


def test_english_only_voice_switches_to_its_multilingual_model() -> None:
    cfg = config(
        tts={"provider": "elevenlabs", "model": "eleven_flash_v2", "voice_id": "EXAVITQu4vr4xnSDxMaL"}
    )
    hindi = next(o for o in language_options(cfg) if o["code"] == "hi")
    assert hindi["tts_model"] == "eleven_flash_v2_5"
    assert language_options(cfg)[0]["tts_model"] == "eleven_flash_v2"


def test_speech_recognition_limits_the_choice() -> None:
    cfg = config(stt={"provider": "assemblyai", "model": None})
    assert set(codes(cfg)[1:]) == {"es", "fr", "de", "it", "pt"}
    fixed = config(stt={"provider": "deepgram", "model": "nova-3"})
    hindi = next(o for o in language_options(fixed) if o["code"] == "hi")
    assert hindi["stt_model"] == "nova-2"  # the provider's model that hears Hindi


def test_listed_languages_disabled_and_flow() -> None:
    listed = config(advanced={"language_switching": {"enabled": True, "languages": ["hi", "he", "fr"]}})
    assert codes(listed) == ["en-US", "hi", "fr"]
    off = config(advanced={"language_switching": {"enabled": False, "languages": []}})
    assert language_options(off) == []
    flow = default_config("flow")
    assert codes(flow) == codes(config())  # flow agents switch language too
    nothing = config(advanced={"language_switching": {"enabled": True, "languages": ["he"]}})
    assert language_options(nothing) == []  # nothing to switch to


def test_old_versions_read_as_enabled() -> None:
    old = config()
    del old["advanced"]["language_switching"]
    assert upcast(old)["advanced"]["language_switching"] == {"enabled": True, "languages": []}
    assert len(language_options(old)) > 1
    assert "hi" in supported_codes(old) and "he" not in supported_codes(old)


def test_validation_of_the_setting() -> None:
    cfg = config(advanced={"language_switching": {"enabled": True, "languages": ["hi", "he"]}})
    result = validate_pure("single_prompt", cfg)
    assert result.valid
    warnings = [w for w in result.warnings if w["pointer"] == "/advanced/language_switching/languages"]
    assert [w["code"] for w in warnings] == ["language_unsupported"]
    assert "Hebrew" in warnings[0]["message"]
    assert result.normalized_config["advanced"]["language_switching"]["languages"] == ["hi", "he"]

    bad = config(advanced={"language_switching": {"enabled": True, "languages": ["xx", "hi", "hi", "multi"]}})
    errors = {(e["pointer"], e["code"]) for e in validate_pure("single_prompt", bad).errors}
    assert ("/advanced/language_switching/languages", "not_in_catalog") in errors
    assert ("/advanced/language_switching/languages", "duplicate_entry") in errors

    defaults = validate_pure("single_prompt", config())
    assert defaults.normalized_config["advanced"]["language_switching"] == {"enabled": True, "languages": []}
    assert defaults.normalized_config["tts"]["model"] == "eleven_multilingual_v2"
