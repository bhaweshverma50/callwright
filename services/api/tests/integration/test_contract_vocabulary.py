"""The database's CHECK lists equal the contract vocabularies. Migrations are forward-only and keep
their literal lists, so a value added to the contract needs a migration too; this fails until it
has one."""

from __future__ import annotations

import re
from typing import get_args

import pytest
from callwright_contract.calls import CALL_STATUSES, CHANNELS, DISCONNECT_REASONS, Direction
from callwright_contract.protocol import MAX_DIAGNOSTIC_CHARS
from callwright_contract.textsim import SimulationEndReason

from app.calls.origins import ORIGINS
from app.calls.pipeline import PIPELINE_STEPS
from tests.runtime_support import Runtime, owner_sql


def check_values(table: str, column: str) -> set[str]:
    rows = owner_sql(
        "select pg_get_constraintdef(oid) from pg_constraint "
        "where contype = 'c' and conrelid = %s::regclass and conname = %s",
        (table, f"{table}_{column}_check"),
    )
    assert len(rows) == 1, f"no CHECK on {table}.{column}"
    return set(re.findall(r"'([^']*)'::text", rows[0][0]))


@pytest.mark.parametrize(
    ("table", "column", "values"),
    [
        ("calls", "status", CALL_STATUSES),
        ("calls", "disconnect_reason", DISCONNECT_REASONS),
        ("calls", "channel", CHANNELS),
        ("calls", "origin", ORIGINS),
        ("calls", "direction", get_args(Direction)),
        ("call_pipeline_steps", "step", PIPELINE_STEPS),
        ("simulation_runs", "end_reason", get_args(SimulationEndReason)),
    ],
)
def test_check_lists_match_the_contract(
    runtime: Runtime, table: str, column: str, values: tuple[str, ...]
) -> None:
    assert check_values(table, column) == set(values)


def test_diagnostic_limit_matches_the_contract(runtime: Runtime) -> None:
    rows = owner_sql(
        "select pg_get_constraintdef(oid) from pg_constraint where conname = 'calls_diagnostic_check'"
    )
    assert rows == [(f"CHECK ((char_length(diagnostic) <= {MAX_DIAGNOSTIC_CHARS}))",)]
