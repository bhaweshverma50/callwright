"""Catalog lookup, version selection and publish validation (T062, research R3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.errors import ProblemError
from app.pricing import engine
from app.pricing.service import EntryInput, validate_effective_from, validate_entries

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def _catalog() -> engine.Catalog:
    return engine.Catalog(
        1,
        NOW,
        (
            engine.Rate("stt", "deepgram", None, "Auto", Decimal("0.0085")),
            engine.Rate("stt", "deepgram", "nova-2", "Nova-2", Decimal("0.0058")),
            engine.Rate("platform", "callwright", None, "Fee", Decimal("0.05")),
        ),
    )


def test_exact_model_match_wins() -> None:
    rate = _catalog().lookup("stt", "deepgram", "nova-2")
    assert rate is not None and rate.rate_per_min_usd == Decimal("0.0058")


def test_provider_fallback_for_unknown_or_auto_model() -> None:
    catalog = _catalog()
    for model in ("nova-9", None):
        rate = catalog.lookup("stt", "deepgram", model)
        assert rate is not None and rate.model is None


def test_unpriced_when_no_row() -> None:
    assert _catalog().lookup("stt", "assemblyai", "universal-streaming") is None
    assert _catalog().lookup("tts", "deepgram", None) is None


def _entry(
    component: str,
    provider: str = "p",
    model: str | None = None,
    bundles: tuple[engine.Bundle, ...] = (),
    rate: str = "0.01",
) -> EntryInput:
    return EntryInput(component, provider, model, "label", Decimal(rate), bundles)


def test_valid_entry_set() -> None:
    entries = [
        _entry("stt"),
        _entry("llm", bundles=(engine.Bundle("llm_input_tokens", 20000),)),
        _entry("platform", "callwright"),
    ]
    assert validate_entries(entries) == []


def test_bundles_only_on_llm_and_tts() -> None:
    errors = validate_entries([_entry("stt", bundles=(engine.Bundle("tts_chars", 750),)), _entry("platform")])
    assert errors[0]["pointer"] == "/entries/0/bundles"


def test_exactly_one_platform_row() -> None:
    assert validate_entries([_entry("stt")])[0]["pointer"] == "/entries"
    two = validate_entries([_entry("platform", "a"), _entry("platform", "b")])
    assert any(e["pointer"] == "/entries" for e in two)


def test_duplicate_keys_rejected() -> None:
    errors = validate_entries([_entry("stt", "x", "m"), _entry("stt", "x", "m"), _entry("platform")])
    assert errors[0]["code"] == "duplicate"


def test_publish_rejects_past_or_non_increasing_effective_from() -> None:
    assert validate_effective_from(NOW - timedelta(minutes=1), None, NOW)[0]["code"] == "out_of_range"
    assert validate_effective_from(NOW, None, NOW)  # not strictly in the future
    later = NOW + timedelta(days=2)
    assert validate_effective_from(NOW + timedelta(days=1), later, NOW)  # not after the latest version
    assert validate_effective_from(later + timedelta(minutes=1), later, NOW) == []
    naive = datetime(2030, 1, 1)
    assert validate_effective_from(naive, None, NOW)[0]["code"] == "invalid_format"


def test_bundle_validation() -> None:
    with pytest.raises(ValueError):
        engine.Bundle("seconds", 10)
    with pytest.raises(ValueError):
        engine.Bundle("tts_chars", 0)


def test_problem_type_for_validation() -> None:
    from app.core.errors import validation_failed

    problem = validation_failed(validate_entries([_entry("stt")]))
    assert isinstance(problem, ProblemError) and problem.status == 422
