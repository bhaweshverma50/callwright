"""``{{var}}`` substitution (004 T048)."""

from __future__ import annotations

from worker.flow.templating import render


def test_known_values_and_missing_report() -> None:
    text, missing = render(
        "Hi {{ name }}, ref {{booking_ref}} on {{dob}}.", {"name": "Priya", "booking_ref": 7}
    )
    assert text == "Hi Priya, ref 7 on ."
    assert missing == ["dob"]


def test_task_results_and_booleans() -> None:
    text, missing = render(
        "{{task_result.email}} {{ok}}", {"task_result.email": "a@b.c", "ok": True}
    )
    assert (text, missing) == ("a@b.c true", [])


def test_empty_and_none() -> None:
    assert render(None, {}) == ("", [])
    assert render("{{x}}{{x}}", {"x": ""}) == ("", ["x"])
