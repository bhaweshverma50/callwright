"""Canonical JSON and the content hash of a version (T015, research R3).

Canonical form: keys sorted, no insignificant whitespace, UTF-8 without escaping non-ASCII,
floats in their shortest round-trip form. Snapshot-only blocks (``tools``, ``knowledge``) are
part of the hash, so a version is identified by everything a call would run with. 008 uses the
same function for simulation targets, so hashes are comparable across features.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


def _normalise(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalise(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_normalise(v) for v in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite numbers cannot be hashed")
        # 1.0 and 1 describe the same setting; hash them identically.
        return int(value) if value.is_integer() else value
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(_normalise(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(config: Any) -> str:
    return hashlib.sha256(canonical_json(config).encode("utf-8")).hexdigest()
