"""The mass-archive allowance (022 T068, FR-014): max(2, 20%) per sync, otherwise hold them all."""

from __future__ import annotations

import pytest

from app.knowledge.sources import guard


@pytest.mark.parametrize(
    ("active", "allowed"),
    [(0, 2), (1, 2), (8, 2), (10, 2), (11, 2), (15, 3), (100, 20), (101, 20), (200, 40)],
)
def test_allowance(active: int, allowed: int) -> None:
    assert guard.allowance(active) == allowed


def test_within_the_allowance_archives_everything() -> None:
    assert guard.decide(["a", "b"], 8) == guard.Archive(["a", "b"])
    assert guard.decide([f"d{i}" for i in range(20)], 100) == guard.Archive([f"d{i}" for i in range(20)])


def test_over_the_allowance_holds_everything() -> None:
    held = guard.decide([f"d{i}" for i in range(25)], 100)
    assert isinstance(held, guard.Hold)
    assert (held.would_archive, held.of, len(held.doc_ids)) == (25, 100, 25)
    assert guard.message(25, 100) == "This sync would archive 25 of 100 documents"
