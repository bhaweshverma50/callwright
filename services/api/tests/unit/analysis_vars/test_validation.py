"""Variable field rules (007 T014, T089; FR-001, FR-046, US1 scenarios 2, 3, 8). Uniqueness and
the 25-variable limit run against the database in tests/contract/test_analysis_vars_contract.py."""

from __future__ import annotations

import pytest

from app.analysis_vars.service import NAME_RULE, validate_fields


def errors(**kw: object) -> dict[str, str]:
    base: dict[str, object] = {
        "name": "appointment_booked",
        "type": "boolean",
        "description": "x",
        "choices": None,
    }
    base.update(kw)
    return {e["pointer"]: e["message"] for e in validate_fields(**base)}  # type: ignore[arg-type]


@pytest.mark.parametrize("name", ["Preferred Day", "1st", "_x", "a" * 65, "with-dash", "", "Day"])
def test_bad_names(name: str) -> None:
    assert errors(name=name) == {"/name": NAME_RULE}
    assert NAME_RULE == "Use lowercase letters, digits and underscores, starting with a letter"


@pytest.mark.parametrize("name", ["a", "appointment_booked", "x1_2", "a" * 64])
def test_good_names(name: str) -> None:
    assert errors(name=name) == {}


@pytest.mark.parametrize("kind", ["boolean", "string", "number"])
def test_choices_rejected_for_non_choice_types(kind: str) -> None:
    assert errors(type=kind, choices=["a", "b"]) == {
        "/choices": "Choices are only accepted for the fixed-set type"
    }


@pytest.mark.parametrize(
    ("choices", "message"),
    [
        (None, "Add 2 to 20 choices"),
        (["Monday"], "Add 2 to 20 choices"),
        ([f"c{i}" for i in range(21)], "Add 2 to 20 choices"),
        (["Monday", "Monday"], "Choices must be unique"),
        (["Monday", ""], "Each choice needs 1 to 64 characters"),
        (["Monday", "x" * 65], "Each choice needs 1 to 64 characters"),
    ],
)
def test_choice_rules(choices: list[str] | None, message: str) -> None:
    assert errors(type="choice", choices=choices) == {"/choices": message}


def test_choice_with_two_to_twenty() -> None:
    assert errors(type="choice", choices=["Monday", "Tuesday"]) == {}
    assert errors(type="choice", choices=[f"c{i}" for i in range(20)]) == {}


def test_description_required_and_bounded() -> None:
    assert "/description" in errors(description="")
    assert "/description" in errors(description=" ")
    assert "/description" in errors(description="x" * 501)
    assert errors(description="x" * 500) == {}


def test_unknown_type() -> None:
    assert set(errors(type="date")) == {"/type"}


def test_patch_checks_only_sent_fields() -> None:
    out = validate_fields(name="Bad Name", type="string", description="", choices=None, partial={})
    assert out == []
