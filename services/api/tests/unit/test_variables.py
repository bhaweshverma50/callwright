"""Dynamic variables (003 T024, FR-005, FR-006): resolution order, built-ins, limits, missing names."""

from __future__ import annotations

from datetime import UTC, datetime

from app.calls import variables as v

NOW = datetime(2026, 10, 16, 14, 5, tzinfo=UTC)


def builtins(**overrides: str | None) -> dict[str, str]:
    args: dict[str, object] = {
        "call_id": "call_X",
        "channel": "web",
        "direction": "inbound",
        "from_number": None,
        "to_number": None,
        "timezone": "UTC",
        "now": NOW,
    }
    args.update(overrides)
    return v.builtin_values(**args)  # type: ignore[arg-type]


CONFIG = {
    "prompt": "Help {{ customer_name }} at {{company_name}}. Ref {{ order_id }}.",
    "begin_message": "Hi {{customer_name}}",
    "dynamic_variables": [
        {"name": "customer_name", "default": "there"},
        {"name": "company_name", "default": "Acme"},
        {"name": "plan", "default": None},
    ],
}


def test_call_value_then_default_then_empty() -> None:
    out = v.resolve(CONFIG, {"customer_name": "Priya"}, builtins())
    assert out.values["customer_name"] == "Priya"
    assert out.values["company_name"] == "Acme"
    assert out.values["plan"] == ""
    assert out.values["order_id"] == ""
    assert out.missing == ["plan", "order_id"]
    assert out.ignored == []


def test_builtins_cannot_be_overridden_and_are_recorded() -> None:
    out = v.resolve(CONFIG, {"call_id": "evil", "current_date": "1999-01-01"}, builtins())
    assert out.values["call_id"] == "call_X"
    assert out.values["current_date"] == "2026-10-16"
    assert out.ignored == ["call_id", "current_date"]


def test_undeclared_supplied_values_pass_through() -> None:
    out = v.resolve(CONFIG, {"ticket": "T-1"}, builtins())
    assert out.values["ticket"] == "T-1"


def test_builtin_numbers_follow_direction() -> None:
    inbound = builtins(direction="inbound", from_number="+15550001", to_number="+15559999")
    assert inbound["user_number"] == "+15550001" and inbound["agent_number"] == "+15559999"
    outbound = builtins(direction="outbound", from_number="+15559999", to_number="+15550001")
    assert outbound["user_number"] == "+15550001" and outbound["agent_number"] == "+15559999"
    assert set(inbound) == set(v.BUILTIN_VARIABLES)


def test_timezone_rendering_and_unknown_zone_falls_back() -> None:
    kolkata = builtins(timezone="Asia/Kolkata")
    assert kolkata["current_time"] == "19:35"
    assert builtins(timezone="Not/AZone")["timezone"] == "UTC"


def test_validation_limits() -> None:
    assert v.validate_supplied({"ok_name": "x", "_x1": "y"}) == []
    bad = v.validate_supplied({"1bad": "x", "has-dash": "y", "long": "z" * 2001})
    assert {i.pointer for i in bad} == {
        "/dynamic_variables/1bad",
        "/dynamic_variables/has-dash",
        "/dynamic_variables/long",
    }
    assert v.validate_supplied({f"v{i}": "x" for i in range(51)})[0].code == "out_of_range"
    assert v.NAME.match("a" * 64) and not v.NAME.match("a" * 65)


def test_referenced_names_tolerates_whitespace() -> None:
    assert v.referenced_names(["{{a}} {{ b }} {{a}}", None, "{{ not valid-}}"]) == ["a", "b"]
