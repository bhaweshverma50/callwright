"""LLM catalog loading and the pricing join (T008, data-model 8.2)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from callwright_contract.adapters import load_catalog as load_adapter_catalog

from app.llms.service import catalog_json, load_catalog, parse_catalog
from app.pricing import engine

PRICING = engine.Catalog(
    version=1,
    effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    rates=(
        engine.Rate(
            "llm",
            "azure_openai",
            "gpt-5.1",
            "GPT-5.1",
            Decimal("0.0165"),
            (engine.Bundle("llm_input_tokens", 20000),),
        ),
    ),
)

RANGED = {
    "default": {"provider": "acme", "model": "m1"},
    "providers": [{"id": "acme", "label": "Acme"}],
    "models": [
        {
            "id": "m1",
            "label": "M1",
            "providers": ["acme"],
            "temperature": {"min": 0, "max": 1, "step": 0.1, "default": 0.7},
        },
        {
            "id": "m0",
            "label": "M0",
            "providers": ["acme"],
            "temperature": {"fixed": 1.0, "reason": "x"},
            "withdrawn": True,
        },
    ],
}


def test_launch_models() -> None:
    cat = load_catalog()
    assert (cat.default_provider, cat.default_model) == ("azure_openai", "gpt-5.1")
    for provider in ("azure_openai", "openai"):
        assert [m.id for m in cat.models_for(provider)] == ["gpt-5.1", "gpt-5.2", "gpt-5-mini"]
    assert all(m.temperature.fixed == 1.0 for m in cat.models)


def test_fixed_and_ranged_rules() -> None:
    cat = parse_catalog(RANGED)
    m1 = cat.model("acme", "m1")
    assert m1 is not None and not m1.temperature.is_fixed and m1.temperature.default_value == 0.7
    assert cat.model("acme", "m0") is not None, "withdrawn models stay resolvable"
    assert [m.id for m in cat.models_for("acme")] == ["m1"]
    assert [m.id for m in cat.models_for("acme", include_withdrawn=True)] == ["m1", "m0"]


def test_pricing_join() -> None:
    body = catalog_json(PRICING)
    azure = next(p for p in body["providers"] if p["id"] == "azure_openai")
    by_id = {m["id"]: m for m in azure["models"]}
    assert by_id["gpt-5.1"]["price_per_min_usd"] == "0.016500"
    assert by_id["gpt-5.1"]["input_tokens_bundle_per_min"] == 20000
    assert by_id["gpt-5.2"]["price_per_min_usd"] is None
    assert by_id["gpt-5.1"]["temperature"] == {
        "fixed": 1.0,
        "reason": "This model only supports temperature 1.0",
    }


def test_withdrawn_hidden_unless_asked() -> None:
    body = catalog_json(None, catalog=parse_catalog(RANGED))
    assert [m["id"] for m in body["providers"][0]["models"]] == ["m1"]
    body = catalog_json(None, include_withdrawn=True, catalog=parse_catalog(RANGED))
    assert [m["id"] for m in body["providers"][0]["models"]] == ["m1", "m0"]


def test_fixed_temperatures_agree_with_the_worker_catalog() -> None:
    """The editor locks temperature for exactly the models the voice worker runs at the default."""
    adapters = load_adapter_catalog()
    for model in load_catalog().models:
        for provider in model.providers:
            entry = adapters.entry("llm", provider)
            assert entry is not None and (model.id in entry.fixed_temperature) == model.temperature.is_fixed
