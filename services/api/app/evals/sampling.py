"""Deterministic judge sampling (007 T083, FR-037, research R14).

The same call always gets the same decision for the same evaluator and rate, so a re-delivered
pipeline job decides the same way. Sampling applies only to automatic (``pipeline``) evaluation
of live calls; reruns, datasets and simulations always evaluate.
"""

from __future__ import annotations

import hashlib


def selected(call_id: str, evaluator_name: str, sample_rate_pct: int) -> bool:
    if sample_rate_pct >= 100:
        return True
    bucket = int(hashlib.sha256(f"{call_id}:{evaluator_name}".encode()).hexdigest()[:8], 16) % 100
    return bucket < sample_rate_pct


def applies(trigger: str, origin: str) -> bool:
    return trigger == "pipeline" and origin == "live"
