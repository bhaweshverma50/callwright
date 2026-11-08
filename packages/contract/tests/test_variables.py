from __future__ import annotations

from datetime import UTC, datetime, timedelta

from callwright_contract.variables import (
    BUILTIN_VARIABLES,
    DOTTED_PLACEHOLDER,
    builtin_values,
    local_now,
    render,
)


def test_render() -> None:
    variables = {"customer_name": "Priya", "order_id": "A1"}
    assert render("Hi {{customer_name}}, order {{ order_id }}.", variables) == "Hi Priya, order A1."
    assert render("{{missing}}|{{ 9bad }}", variables) == "|{{ 9bad }}"


def test_dotted_placeholder_reads_one_level() -> None:
    names = [m.group(1) for m in DOTTED_PLACEHOLDER.finditer("{{task_result.email}} {{ a }} {{a.b.c}}")]
    assert names == ["task_result.email", "a"]


def test_builtin_values_and_local_now() -> None:
    now = datetime(2026, 11, 3, 8, 35, tzinfo=UTC)
    values = builtin_values(
        call_id="call_1",
        channel="sip_outbound",
        direction="outbound",
        from_number="+14155550100",
        to_number="+919800000000",
        timezone="Asia/Kolkata",
        now=now,
    )
    assert set(values) == set(BUILTIN_VARIABLES)
    assert values["user_number"] == "+919800000000" and values["agent_number"] == "+14155550100"
    assert values["current_time"] == "14:05" and values["current_datetime"] == "2026-11-03T14:05+05:30"
    local = local_now(values, now)
    assert (local.hour, local.minute, local.utcoffset()) == (14, 5, timedelta(hours=5, minutes=30))
    unknown = builtin_values(
        call_id="c",
        channel="web",
        direction="inbound",
        from_number=None,
        to_number=None,
        timezone="Mars/Base",
        now=now,
    )
    assert unknown["timezone"] == "UTC" and local_now(unknown, now) == now
