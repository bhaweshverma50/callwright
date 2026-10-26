"""Call list query parsing (006 T013, T088; FR-004, FR-037, FR-038)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.calls.queries import date_window, digits, parse_list_query, split_csv
from app.core.errors import ProblemError


def test_split_csv_keeps_known_values_in_order_without_duplicates() -> None:
    assert split_csv("failed, completed,bogus,failed", ("completed", "failed")) == ["failed", "completed"]
    assert split_csv(None, ("a",)) == []
    assert split_csv("", ("a",)) == []


def test_defaults() -> None:
    q = parse_list_query({})
    assert q.sort == "started_at" and q.order == "desc"
    assert q.origins == ["live", "test"]
    assert q.statuses == [] and q.agent_ids == []


def test_unknown_filter_values_are_dropped() -> None:
    q = parse_list_query(
        {"status": "completed,exploded", "channel": "whatsapp,fax", "agent_id": "agt_1,usr_2"}
    )
    assert q.statuses == ["completed"]
    assert q.channels == ["whatsapp"]
    assert q.agent_ids == ["agt_1"]


def test_origin_filter_can_include_simulation() -> None:
    assert parse_list_query({"origin": "live,test,simulation"}).origins == ["live", "test", "simulation"]
    # Only unknown values falls back to the default rather than hiding everything.
    assert parse_list_query({"origin": "nonsense"}).origins == ["live", "test"]


def test_sort_whitelist() -> None:
    with pytest.raises(ProblemError) as exc:
        parse_list_query({"sort": "summary"})
    assert exc.value.status == 422
    with pytest.raises(ProblemError):
        parse_list_query({"order": "sideways"})
    assert parse_list_query({"sort": "cost_usd", "order": "asc"}).sort == "cost_usd"


@pytest.mark.parametrize(
    ("typed", "expected"),
    [("+1555", "1555"), ("1 (555)", "1555"), ("+1-555-123 4567", "15551234567"), ("abc", "")],
)
def test_phone_digits(typed: str, expected: str) -> None:
    assert digits(typed) == expected


def test_phone_filter_ignores_formatting_and_empty_digits() -> None:
    assert parse_list_query({"from_number": "+1 (555)"}).from_digits == "1555"
    assert parse_list_query({"to_number": "--"}).to_digits is None


def test_call_id_prefix_needs_eight_characters() -> None:
    with pytest.raises(ProblemError):
        parse_list_query({"call_id": "call_1"})
    assert parse_list_query({"call_id": "call_01JA"}).call_id == "call_01JA"


def test_single_day_in_kolkata_includes_previous_utc_evening() -> None:
    start, end = date_window("2026-10-01", "2026-10-01", "Asia/Kolkata")
    assert start == datetime(2026, 9, 30, 18, 30, tzinfo=UTC)
    assert end == datetime(2026, 10, 1, 18, 30, tzinfo=UTC)
    call = datetime(2026, 9, 30, 20, 0, tzinfo=UTC)
    assert start is not None and end is not None and start <= call < end


def test_open_ended_dates() -> None:
    start, end = date_window("2026-10-01", None, "UTC")
    assert start == datetime(2026, 10, 1, tzinfo=UTC) and end is None
    start, end = date_window(None, "2026-10-01", "UTC")
    assert start is None and end == datetime(2026, 10, 2, tzinfo=UTC)


def test_end_before_start_rejected() -> None:
    with pytest.raises(ProblemError) as exc:
        parse_list_query({"start_date": "2026-10-10", "end_date": "2026-10-01"})
    assert exc.value.status == 422


def test_bad_timezone_and_bad_date_rejected() -> None:
    with pytest.raises(ProblemError):
        parse_list_query({"start_date": "2026-10-10", "tz": "Mars/Base"})
    with pytest.raises(ProblemError):
        parse_list_query({"start_date": "10/10/2026"})


def test_quality_filters_parsed() -> None:
    q = parse_list_query({"label": "good,unannotated,meh", "eval_status": "failed,odd"})
    assert q.labels == ["good", "unannotated"]
    assert q.eval_statuses == ["failed"]
