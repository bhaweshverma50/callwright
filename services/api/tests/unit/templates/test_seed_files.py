"""Template seed files (T069): parse, unique slugs, every category used, valid when overlaid."""

from __future__ import annotations

import re

import pytest

from app.agents.validation import validate_pure
from app.templates.jobs import load_seed
from app.templates.service import CATEGORIES, partial_config

SEEDS = load_seed()


def test_unique_slugs_and_categories() -> None:
    ids = [t["id"] for t in SEEDS]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[a-z0-9-]{3,64}", i) for i in ids)
    assert {t["category"] for t in SEEDS} == set(CATEGORIES)


@pytest.mark.parametrize("seed", SEEDS, ids=[t["id"] for t in SEEDS])
def test_overlay_validates(seed: dict) -> None:  # type: ignore[type-arg]
    overlay, warnings = partial_config(seed["config"])
    assert warnings == []
    result = validate_pure("single_prompt", overlay)
    assert result.valid, result.errors
    assert result.publish_blockers == []
    assert len(seed["name"]) <= 80 and len(seed["description"]) <= 300
    assert seed["direction"] in {"inbound", "outbound"}
