"""CLI entry points import their modules alone (no app.main), so ORM mappings must resolve
without other modules being imported first (regression: seed_demo failed on a missing FK target)."""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.parametrize("module", ["app.usage.seed_demo", "app.billing.jobs", "app.dev.make_admin"])
def test_module_mappers_configure_alone(module: str) -> None:
    code = (
        f"import {module}\n"
        "from app.core.db import Base\n"
        "import app.billing.models, app.usage.models, app.pricing.models\n"
        "for table in Base.metadata.sorted_tables:\n"
        "    [fk.column for fk in table.foreign_keys]\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
