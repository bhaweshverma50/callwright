"""CSV cells that a spreadsheet would read as a formula are defused; plain numbers are not."""

from __future__ import annotations

import pytest

from app.calls.export import _cell


@pytest.mark.parametrize(
    "value",
    ["=SUM(A1)", "+1+cmd", "-1+cmd|' /C calc'!A0", "-2 =1", "@SUM(1)", "\tcmd", "\rcmd", "-", "+"],
)
def test_formula_starts_are_prefixed(value: str) -> None:
    assert _cell(value) == "'" + value


@pytest.mark.parametrize("value", [-5, -0.25, "+12", "-3.5e2", 42, "plain text", "a=b", None])
def test_numbers_and_text_pass_through(value: object) -> None:
    assert _cell(value) == ("" if value is None else str(value))
