"""The voice worker's harness builds its claims with the tables this API sends (003 T022): the
control ranges and the speech recognition Auto rules. ``UPDATE_GOLDEN=1`` rewrites the file."""

from __future__ import annotations

import json
import os
from pathlib import Path

from callwright_contract.adapters import load_catalog

from app.agents.defaults import default_config
from app.calls.service import runtime_values

TARGET = (
    Path(__file__).resolve().parents[3]
    / "voice-worker"
    / "tests"
    / "harness"
    / "configs"
    / "claim_tables.json"
)


def test_worker_claim_tables_are_current() -> None:
    values = runtime_values(default_config(), load_catalog())
    tables = values.model_dump(mode="json", include={"controls", "stt_auto_rules"})
    text = json.dumps(tables, indent=2, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_GOLDEN") or not TARGET.exists():
        TARGET.write_text(text)
    assert json.loads(TARGET.read_text()) == tables
