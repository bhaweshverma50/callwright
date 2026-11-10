"""VOICE_VENDOR_KEYS: which providers the voice worker can run decides live-call admission."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from callwright_contract.adapters import load_catalog
from pydantic import SecretStr

from app.calls import service as calls
from app.calls.components import describe, not_set_up
from app.core.config import get_settings
from app.core.vendors import provider_runnable, runnable_providers
from app.llms import service as llms
from app.voices import catalog as voices
from tests.runtime_support import Runtime, agent_config
from tests.unit.test_admission import request

DEEPGRAM_OPENAI_ELEVEN = "deepgram,openai,elevenlabs"
SARVAM = {"provider": "sarvam", "model": "saaras:v3"}


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    def set_keys(keys: str | None, anthropic: bool = False) -> None:
        settings = get_settings().model_copy(
            update={
                "voice_vendor_keys": keys,
                "anthropic_api_key": SecretStr("k") if anthropic else None,
            }
        )
        monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
        monkeypatch.setattr(calls, "get_settings", lambda: settings)
        monkeypatch.setattr("app.agents.vendors.get_settings", lambda: settings)

    yield set_keys


def test_rule() -> None:
    off = get_settings().model_copy(update={"voice_vendor_keys": None, "anthropic_api_key": None})
    on = off.model_copy(update={"voice_vendor_keys": DEEPGRAM_OPENAI_ELEVEN})
    assert runnable_providers(off) is None
    for provider in ("sarvam", "azure_openai", "cartesia", "sanas", "none"):
        assert provider_runnable(provider, off, runnable_providers(off))
    listed = runnable_providers(on)
    assert provider_runnable("deepgram", on, listed)
    assert not provider_runnable("sarvam", on, listed)
    assert provider_runnable("sanas", on, listed)  # passthrough, no key
    assert not provider_runnable("ai_coustics", on, listed)
    assert provider_runnable("none", on, listed)
    # Azure falls back to OpenAI in the worker.
    assert provider_runnable("azure_openai", on, listed)
    only_eleven = on.model_copy(update={"voice_vendor_keys": "elevenlabs"})
    assert not provider_runnable("azure_openai", only_eleven, runnable_providers(only_eleven))
    # Anthropic needs its key even when gating is off, or a listing.
    assert not provider_runnable("anthropic", off, None)
    assert provider_runnable("anthropic", off.model_copy(update={"anthropic_api_key": SecretStr("k")}), None)
    assert provider_runnable(
        "anthropic", on.model_copy(update={"voice_vendor_keys": "anthropic"}), {"anthropic"}
    )


def test_text_names_the_vendor(gate: object) -> None:
    from app.calls.components import resolve

    components = resolve(agent_config(language="hi", stt=SARVAM), load_catalog())
    assert describe(components.stt) == "Sarvam AI speech recognition"
    assert not_set_up(components.stt) == "Sarvam AI speech recognition is not set up on this platform."


async def test_gating_off_admits_sarvam(runtime: Runtime, gate) -> None:  # type: ignore[no-untyped-def]
    gate(None)
    _, ws = await runtime.workspace()
    agent = runtime.versions.add_agent(ws, agent_config(language="hi", stt=SARVAM))
    admission = await calls.admit(runtime.db, request(ws, agent.agent_id), catalog=runtime.catalog)
    assert admission.admitted, admission.refusal


async def test_missing_key_refuses_live_calls_with_the_reason(runtime: Runtime, gate) -> None:  # type: ignore[no-untyped-def]
    gate(DEEPGRAM_OPENAI_ELEVEN)
    _, ws = await runtime.workspace()
    agent = runtime.versions.add_agent(ws, agent_config(language="hi", stt=SARVAM))
    admission = await calls.admit(runtime.db, request(ws, agent.agent_id), catalog=runtime.catalog)
    assert admission.refusal is not None and admission.refusal.code == "unsupported_vendor"
    assert admission.refusal.diagnostic == "unsupported_vendor:stt/sarvam"
    assert admission.refusal.detail == "Sarvam AI speech recognition is not set up on this platform."
    simulation = await calls.admit(
        runtime.db, request(ws, agent.agent_id, origin="simulation"), catalog=runtime.catalog
    )
    assert simulation.refusal is None or simulation.refusal.code != "unsupported_vendor"


async def test_azure_runs_on_openai_and_listed_vendors_are_admitted(runtime: Runtime, gate) -> None:  # type: ignore[no-untyped-def]
    gate(DEEPGRAM_OPENAI_ELEVEN)
    _, ws = await runtime.workspace()
    config = agent_config(llm={"provider": "azure_openai", "model": "gpt-5-mini", "temperature": 1.0})
    agent = runtime.versions.add_agent(ws, config)
    admission = await calls.admit(runtime.db, request(ws, agent.agent_id), catalog=runtime.catalog)
    assert admission.admitted, admission.refusal


async def test_anthropic_follows_the_key_or_the_listing(runtime: Runtime, gate) -> None:  # type: ignore[no-untyped-def]
    claude = {"provider": "anthropic", "model": "claude-haiku-5-5", "temperature": 1.0}
    _, ws = await runtime.workspace()
    agent = runtime.versions.add_agent(ws, agent_config(llm=claude))
    for keys, has_key, admitted in (
        (DEEPGRAM_OPENAI_ELEVEN, False, False),
        (DEEPGRAM_OPENAI_ELEVEN, True, True),
        (DEEPGRAM_OPENAI_ELEVEN + ",anthropic", False, True),
    ):
        gate(keys, anthropic=has_key)
        admission = await calls.admit(runtime.db, request(ws, agent.agent_id), catalog=runtime.catalog)
        assert admission.admitted is admitted


def test_catalogs_mark_unavailable_providers(gate) -> None:  # type: ignore[no-untyped-def]
    gate(DEEPGRAM_OPENAI_ELEVEN)
    speech = voices.catalog_json(None)
    stt = {p["provider"]: p["available"] for p in speech["stt"]}
    assert stt["deepgram"] and not stt["sarvam"]
    assert {p["provider"]: p["available"] for p in speech["tts"]}["elevenlabs"]
    assert not {p["provider"]: p["available"] for p in speech["tts"]}["cartesia"]
    assert {n["provider"]: n["available"] for n in speech["noise_cancellation"]}["sanas"]
    llm = {p["id"]: p["available"] for p in llms.catalog_json(None)["providers"]}
    assert llm["openai"] and llm["azure_openai"] and not llm["anthropic"]
    gate(None)
    assert all(p["available"] for p in voices.catalog_json(None)["stt"])


def test_deploy_script_maps_every_catalog_provider() -> None:
    script = Path(__file__).parents[4] / "deploy/cloudrun/deploy.sh"
    if not script.exists():
        pytest.skip("deploy scripts are not part of the image")
    text = script.read_text()
    block = text[text.index("VENDOR_PROVIDER_SECRETS=(") :].split(")", 1)[0]
    mapped = set(re.findall(r"^\s*(?:\"?)([a-z_]+):", block, re.M))
    providers = {e.provider for e in load_catalog().entries if e.provider != "none"}
    assert mapped == providers
