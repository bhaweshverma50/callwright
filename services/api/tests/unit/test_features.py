"""Feature manifests (``app/features.py``): id prefixes and job names are declared once."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from app import features, worker

APP = Path(__file__).resolve().parents[2] / "app"
LITERAL_PREFIX = re.compile(
    r"""\b(?:new_id|path_id|is_valid_id|require_id)\((?:[^()"']*,\s*)?["']([a-z]+)["']"""
)


def test_id_prefixes_are_owned_by_one_feature() -> None:
    counts = Counter(p for f in features.FEATURES for p in f.id_prefixes)
    assert [p for p, n in counts.items() if n > 1] == []


def test_every_id_prefix_in_use_is_declared() -> None:
    declared = {p for f in features.FEATURES for p in f.id_prefixes}
    used = {
        (m.group(1), str(path.relative_to(APP)))
        for path in APP.rglob("*.py")
        if "migrations" not in path.parts
        for m in LITERAL_PREFIX.finditer(path.read_text())
    }
    assert used, "the pattern no longer finds id literals"
    assert sorted(u for u in used if u[0] not in declared) == []


def test_worker_registers_every_job_under_its_declared_name() -> None:
    assert [f.name for f in worker.WorkerSettings.functions] == list(features.job_functions())
    registered = set(features.job_functions().values())
    assert all(cron.coroutine in registered for cron in worker.WorkerSettings.cron_jobs)
