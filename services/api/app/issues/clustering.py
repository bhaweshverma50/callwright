"""Pure parts of issue detection (009 T018, T019; spec FR-002, FR-004, SC-004, research R1).

* ``failures_from``: one failure per (call, evaluator, flow node). Turn failures collapse to one
  row per call joining their reasons; items that name a flow node give one row per failing node.
* ``group_failures``: by (evaluator, node), most recent first, capped (2,000 by default).
* ``cluster_vectors``: agglomerative clustering (cosine distance, average linkage, distance
  threshold 0.25). Deterministic for the same vectors in the same order.
* ``keep_clusters``: clusters covering at least three distinct calls, largest first.
* ``match_issue``: the existing issue whose centroid has cosine similarity of at least 0.85;
  issues that are not applied win over applied ones, then the most similar.
* ``decide``: create, update, update counts only (dismissed issues; applied issues seen again on
  calls from before the fix) or open a recurrence (an applied issue matched by at least three
  calls of a version created at or after the apply).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

DISTANCE_THRESHOLD = 0.25
MATCH_SIMILARITY = 0.85
MIN_CALLS = 3
MAX_NEW = 20
GROUP_CAP = 2000
NO_REASON = "The check failed without a stated reason."


@dataclass(frozen=True)
class ResultRow:
    """One current evaluator run of a call in the window, with its items
    ``(flow_node_id, flow_node_label, verdict, rationale)``."""

    result_id: str
    call_id: str
    evaluator_id: str
    evaluator_version: int
    scope: str
    verdict: str | None
    rationale: str | None
    items: tuple[tuple[str | None, str | None, str, str | None], ...]
    call_origin: str
    agent_version_id: str | None
    base_call_id: str | None
    failed_at: datetime


@dataclass(frozen=True)
class Failure:
    result_id: str
    call_id: str
    evaluator_id: str
    evaluator_version: int
    node_id: str | None
    node_label: str | None
    reason: str
    call_origin: str
    agent_version_id: str | None
    base_call_id: str | None
    failed_at: datetime

    @property
    def node_key(self) -> str:
        return self.node_id or ""


def _join(reasons: Sequence[str | None]) -> str:
    parts = [" ".join(str(r).split()) for r in reasons if r and str(r).strip()]
    return "; ".join(dict.fromkeys(parts)) or NO_REASON


def failures_from(rows: Sequence[ResultRow]) -> list[Failure]:
    out: list[Failure] = []
    for r in rows:

        def make(node: str | None, label: str | None, reason: str, r: ResultRow = r) -> Failure:
            return Failure(
                r.result_id,
                r.call_id,
                r.evaluator_id,
                r.evaluator_version,
                node,
                label,
                reason,
                r.call_origin,
                r.agent_version_id,
                r.base_call_id,
                r.failed_at,
            )

        failing = [i for i in r.items if i[2] == "fail"]
        if failing:
            by_node: dict[str | None, list[tuple[str | None, str | None, str, str | None]]] = {}
            for item in failing:
                by_node.setdefault(item[0], []).append(item)
            for node, items in by_node.items():
                label = next((i[1] for i in items if i[1]), None)
                out.append(make(node, label, _join([i[3] for i in items])))
        elif r.verdict == "fail":
            out.append(make(None, None, _join([r.rationale])))
    return out


def group_failures(
    failures: Sequence[Failure], cap: int = GROUP_CAP
) -> dict[tuple[str, str | None], list[Failure]]:
    groups: dict[tuple[str, str | None], list[Failure]] = {}
    for f in failures:
        groups.setdefault((f.evaluator_id, f.node_id), []).append(f)
    return {
        key: sorted(items, key=lambda f: (f.failed_at, f.result_id), reverse=True)[:cap]
        for key, items in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or ""))
    }


def cluster_vectors(
    vectors: Sequence[Sequence[float]], threshold: float = DISTANCE_THRESHOLD
) -> list[list[int]]:
    """Index groups, ordered by their first member."""
    if not vectors:
        return []
    if len(vectors) == 1:
        return [[0]]
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering

    matrix = np.asarray(vectors, dtype=np.float64)
    norms = np.linalg.norm(matrix, axis=1)
    matrix[norms == 0] = 1e-9  # cosine needs non-zero vectors
    model = AgglomerativeClustering(
        n_clusters=None, metric="cosine", linkage="average", distance_threshold=threshold
    )
    labels = model.fit_predict(matrix)
    groups: dict[int, list[int]] = {}
    for index, label in enumerate(labels):
        groups.setdefault(int(label), []).append(index)
    return sorted(groups.values(), key=lambda g: g[0])


def distinct_calls(failures: Sequence[Failure]) -> int:
    return len({f.call_id for f in failures})


def keep_clusters(
    failures: Sequence[Failure], clusters: Sequence[Sequence[int]], min_calls: int = MIN_CALLS
) -> list[list[int]]:
    kept = [list(c) for c in clusters if distinct_calls([failures[i] for i in c]) >= min_calls]
    return sorted(kept, key=lambda c: (-distinct_calls([failures[i] for i in c]), c[0]))


def centroid(vectors: Sequence[Sequence[float]]) -> list[float]:
    if not vectors:
        return []
    size = len(vectors[0])
    mean = [sum(v[i] for v in vectors) / len(vectors) for i in range(size)]
    norm = math.sqrt(sum(x * x for x in mean)) or 1.0
    return [x / norm for x in mean]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@dataclass(frozen=True)
class Candidate:
    issue_id: str
    status: str
    centroid: Sequence[float] | None
    applied_at: datetime | None = None


def match_issue(
    point: Sequence[float], candidates: Sequence[Candidate], threshold: float = MATCH_SIMILARITY
) -> Candidate | None:
    scored = [(cosine(point, c.centroid or []), c) for c in candidates]
    # A tiny tolerance keeps the 0.85 boundary inclusive despite float rounding.
    eligible = [(s, c) for s, c in scored if s >= threshold - 1e-9]
    if not eligible:
        return None
    eligible.sort(key=lambda sc: (sc[1].status != "applied", sc[0], sc[1].issue_id), reverse=True)
    return eligible[0][1]


Action = Literal["create", "update", "counts_only", "recurrence"]


@dataclass(frozen=True)
class Decision:
    action: Action
    issue_id: str | None = None
    failures: list[Failure] = field(default_factory=list)


def decide(
    match: Candidate | None, failures: Sequence[Failure], version_created: Mapping[str, datetime]
) -> Decision:
    if match is None:
        return Decision("create", None, list(failures))
    if match.status in ("open", "validating", "validated"):
        return Decision("update", match.issue_id, list(failures))
    if match.status == "applied" and match.applied_at is not None:
        later = [
            f
            for f in failures
            if f.agent_version_id is not None
            and f.agent_version_id in version_created
            and version_created[f.agent_version_id] >= match.applied_at
        ]
        if distinct_calls(later) >= MIN_CALLS:
            return Decision("recurrence", match.issue_id, later)
    return Decision("counts_only", match.issue_id, list(failures))


def origin_of(failures: Sequence[Failure]) -> str:
    calls: dict[str, str] = {}
    for f in failures:
        calls[f.call_id] = f.call_origin
    if not calls:
        return "real"
    share = sum(1 for o in calls.values() if o == "simulation") / len(calls)
    if share >= 0.8:
        return "simulated"
    if share <= 0.2:
        return "real"
    return "mixed"
