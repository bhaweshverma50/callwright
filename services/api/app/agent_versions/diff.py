"""Keyed diff between two AgentConfig documents (T058, FR-025, research R12).

Output: ordered ``{op: add | remove | replace, path, old?, new?}`` changes with JSON Pointer paths.
Keyed lists are matched by key, not position, so inserting a variable never mislabels the rest:

* ``dynamic_variables`` by ``name``; ``advanced.pronunciation`` by ``word`` ignoring case;
* ``tool_ids`` and ``kb_ids`` by value (each id added or removed);
* ``tools`` by ``tool_id`` and ``knowledge`` by ``kb_id`` (snapshot blocks).

Keyed items appear as ``/dynamic_variables[order_id]`` (whole item added or removed) or
``/dynamic_variables[order_id]/default`` (field changed). Other lists, and the ``flow`` block
unless 004 registers a differ, are compared as whole values.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

Change = dict[str, Any]
FlowDiffer = Callable[[Any, Any], list[Change]]

KEYED_LISTS: dict[str, tuple[str, bool]] = {
    "/dynamic_variables": ("name", False),
    "/advanced/pronunciation": ("word", True),
    "/tools": ("tool_id", False),
    "/knowledge": ("kb_id", False),
}
VALUE_LISTS = frozenset({"/tool_ids", "/kb_ids"})
_flow_differ: FlowDiffer | None = None


def register_flow_differ(fn: FlowDiffer) -> None:
    """004 registers a node-aware differ for the ``flow`` block."""
    global _flow_differ
    _flow_differ = fn


def _escape(part: str) -> str:
    return part.replace("~", "~0").replace("/", "~1")


def _key_of(item: Any, key: str, fold: bool) -> str | None:
    if isinstance(item, Mapping) and isinstance(item.get(key), str):
        value: str = item[key]
        return value.casefold() if fold else value
    return None


def _diff_keyed(path: str, old: list[Any], new: list[Any], key: str, fold: bool, out: list[Change]) -> None:
    old_by = {k: (i, item) for i, item in enumerate(old) if (k := _key_of(item, key, fold)) is not None}
    new_by = {k: (i, item) for i, item in enumerate(new) if (k := _key_of(item, key, fold)) is not None}
    if len(old_by) != len(old) or len(new_by) != len(new):
        if old != new:
            out.append({"op": "replace", "path": path, "old": old, "new": new})
        return
    for k, (_, item) in old_by.items():
        if k not in new_by:
            out.append({"op": "remove", "path": f"{path}[{item[key]}]", "old": item})
    for k, (_, item) in new_by.items():
        label = f"{path}[{item[key]}]"
        if k not in old_by:
            out.append({"op": "add", "path": label, "new": item})
            continue
        _diff(label, old_by[k][1], item, out, keyed_item=True)


def _diff_values(path: str, old: list[Any], new: list[Any], out: list[Change]) -> None:
    for value in old:
        if value not in new:
            out.append({"op": "remove", "path": f"{path}[{value}]", "old": value})
    for value in new:
        if value not in old:
            out.append({"op": "add", "path": f"{path}[{value}]", "new": value})


def _diff(path: str, old: Any, new: Any, out: list[Change], *, keyed_item: bool = False) -> None:
    if path == "/flow" and _flow_differ is not None:
        out.extend(_flow_differ(old, new))
        return
    if isinstance(old, Mapping) and isinstance(new, Mapping):
        for key in _ordered_keys(old, new):
            child = f"{path}/{_escape(str(key))}"
            if key not in new:
                out.append({"op": "remove", "path": child, "old": old[key]})
            elif key not in old:
                out.append({"op": "add", "path": child, "new": new[key]})
            else:
                _diff(child, old[key], new[key], out)
        return
    if isinstance(old, list) and isinstance(new, list):
        if path in KEYED_LISTS:
            key, fold = KEYED_LISTS[path]
            _diff_keyed(path, old, new, key, fold, out)
            return
        if path in VALUE_LISTS:
            _diff_values(path, old, new, out)
            return
    if _same_number(old, new):
        return
    if old != new or type(old) is not type(new):
        out.append({"op": "replace", "path": path or "/", "old": old, "new": new})


# Field order of AgentConfig v1 (data-model.md section 4), so changes read top to bottom.
FIELD_ORDER = (
    "schema_version",
    "type",
    "language",
    "llm",
    "provider",
    "model",
    "temperature",
    "prompt",
    "begin_message",
    "start_speaker",
    "dynamic_variables",
    "name",
    "default",
    "description",
    "stt",
    "tts",
    "voice_id",
    "speed",
    "expressiveness",
    "volume",
    "noise_cancellation",
    "call_behavior",
    "end_on_silence_s",
    "max_duration_s",
    "ring_duration_ms",
    "interruption_sensitivity",
    "responsiveness",
    "advanced",
    "webhook_url",
    "webhook_timeout_ms",
    "voicemail_detection",
    "enabled",
    "action",
    "message",
    "dtmf",
    "timeout_ms",
    "termination_key",
    "digits",
    "background_audio",
    "source",
    "analysis_model",
    "pronunciation",
    "word",
    "replacement",
    "recording",
    "language_switching",
    "languages",
    "tool_ids",
    "kb_ids",
    "tools",
    "knowledge",
    "flow",
    "evals",
)
_RANK = {name: i for i, name in enumerate(FIELD_ORDER)}


def _ordered_keys(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[Any]:
    return sorted(set(old) | set(new), key=lambda k: (_RANK.get(str(k), len(_RANK)), str(k)))


def _same_number(a: Any, b: Any) -> bool:
    numbers = (int, float)
    return (
        isinstance(a, numbers)
        and isinstance(b, numbers)
        and not isinstance(a, bool)
        and not isinstance(b, bool)
        and float(a) == float(b)
    )


def diff_configs(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[Change]:
    """Changes that turn ``old`` into ``new``, in document order (stable across runs)."""
    out: list[Change] = []
    _diff("", old, new, out)
    return out
