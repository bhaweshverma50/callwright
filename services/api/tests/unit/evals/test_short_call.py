from datetime import UTC, datetime, timedelta
from typing import Any

from app.calls.models import Call
from app.evals.short_call import too_short
from tests.conftest import make_settings

START = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)


def _call(seconds: int, caller: str, origin: str = "live") -> Call:
    items: list[dict[str, Any]] = [
        {"type": "message", "role": "agent", "text": "Hello, this is the bank. May I speak with Jordan?"},
        {"type": "message", "role": "user", "text": caller},
    ]
    return Call(
        origin=origin,
        connected_at=START,
        ended_at=START + timedelta(seconds=seconds),
        transcript={"items": items},
    )


LONG = "Yes, this is Jordan. I can pay the whole amount on Friday, is that all right?"


def test_short_duration_or_little_caller_speech_is_too_short() -> None:
    s = make_settings()  # defaults: 15 s, 40 caller characters
    assert too_short(_call(13, LONG), s)  # 13 s call
    assert too_short(_call(120, "Yeah. Sure."), s)  # caller said 11 characters
    assert not too_short(_call(120, LONG), s)


def test_simulations_skip_the_duration_rule_and_zero_turns_rules_off() -> None:
    assert not too_short(_call(3, LONG, origin="simulation"), make_settings())
    off = make_settings(analysis_min_duration_s=0, analysis_min_caller_chars=0)
    assert not too_short(_call(5, "Ok."), off)
