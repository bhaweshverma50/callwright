"""Phrase checks (007 T056; FR-009, FR-012, US5 scenario 3 and the independent test)."""

from __future__ import annotations

import pytest

from app.evaluators.custom.phrase_check import PatternError, check_phrase, compile_pattern
from tests.unit.evaluators.helpers import context, messages

CALL = messages(
    ("agent", "Hello."),
    ("user", "Is approval guaranteed?"),
    ("agent", "Yes, approval is GUARANTEED for you."),
)


def run(**config: object) -> tuple[str, str]:
    out = check_phrase(context(msgs=CALL), {"mode": "forbidden", "target": "agent", **config})
    return out.items[0].verdict, out.items[0].rationale


def test_forbidden_pattern_quotes_matching_turn() -> None:
    verdict, rationale = run(pattern="guarantee(d)?", is_regex=True)
    assert verdict == "fail" and "line 2" in rationale and "approval is GUARANTEED" in rationale


def test_target_speaker() -> None:
    assert run(pattern="Is approval", target="agent")[0] == "pass"
    assert run(pattern="Is approval", target="user")[0] == "fail"
    assert run(pattern="Is approval", target="both")[0] == "fail"


def test_required_mode() -> None:
    assert run(pattern="hello", mode="required")[0] == "pass"
    assert run(pattern="goodbye", mode="required")[0] == "fail"


def test_case_sensitivity() -> None:
    assert run(pattern="guaranteed", case_sensitive=True)[0] == "pass"
    assert run(pattern="GUARANTEED", case_sensitive=True)[0] == "fail"
    assert run(pattern="guaranteed")[0] == "fail"


def test_plain_text_is_escaped() -> None:
    assert run(pattern="guarantee(d)?")[0] == "pass"  # literal parentheses, no regex
    assert run(pattern="GUARANTEED for you.")[0] == "fail"


@pytest.mark.parametrize("pattern", ["(unclosed", r"(a)\1", "(?=lookahead)", "x" * 501, ""])
def test_invalid_or_unbounded_patterns_rejected(pattern: str) -> None:
    with pytest.raises(PatternError):
        compile_pattern(pattern, is_regex=True, case_sensitive=False)


def test_no_lines_from_target_is_not_applicable() -> None:
    out = check_phrase(
        context(msgs=messages(("agent", "Hi"))), {"pattern": "x", "mode": "forbidden", "target": "user"}
    )
    assert out.items[0].verdict == "not_applicable"
