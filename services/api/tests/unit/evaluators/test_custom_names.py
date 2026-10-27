"""Machine-name derivation for custom checks (007 T086, FR-044). Versioning, the 50 limit and the
derived-name conflict run against the database in tests/contract/test_evaluators_contract.py."""

from __future__ import annotations

import pytest

from app.evaluators.service import derive_name


@pytest.mark.parametrize(
    ("display", "name"),
    [
        ("No guarantees", "no_guarantees"),
        ("  Confirms DOB!! ", "confirms_dob"),
        ("3 strikes rule", "strikes_rule"),
        ("__Weird--Name__", "weird_name"),
        ("Ünïcode café", "n_code_caf"),
        ("!!!", ""),
        ("x" * 100, "x" * 64),
    ],
)
def test_derive_name(display: str, name: str) -> None:
    assert derive_name(display) == name
