"""Canonical JSON and hash stability (T010, research R3)."""

from __future__ import annotations

import pytest

from app.agent_versions.canonical import canonical_json, content_hash


def test_key_order_and_whitespace_do_not_matter() -> None:
    a = {"b": 1, "a": {"y": [1, 2], "x": "z"}}
    b = {"a": {"x": "z", "y": [1, 2]}, "b": 1}
    assert canonical_json(a) == canonical_json(b) == '{"a":{"x":"z","y":[1,2]},"b":1}'
    assert content_hash(a) == content_hash(b)


def test_unicode_kept_and_hash_is_hex() -> None:
    value = {"prompt": "Grüß Gott, नमस्ते"}
    assert "Grüß" in canonical_json(value)
    digest = content_hash(value)
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)


def test_list_order_matters() -> None:
    assert content_hash({"tool_ids": ["a", "b"]}) != content_hash({"tool_ids": ["b", "a"]})


def test_integral_floats_hash_like_ints() -> None:
    assert content_hash({"speed": 1.0}) == content_hash({"speed": 1})
    assert content_hash({"speed": 1.1}) != content_hash({"speed": 1})


def test_snapshot_only_tools_change_the_hash() -> None:
    base = {"prompt": "x", "tool_ids": ["tool_1"]}
    with_tools = {**base, "tools": [{"tool_id": "tool_1", "url": "https://a"}]}
    edited = {**base, "tools": [{"tool_id": "tool_1", "url": "https://b"}]}
    assert len({content_hash(base), content_hash(with_tools), content_hash(edited)}) == 3


def test_stable_known_value() -> None:
    assert content_hash({}) == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"


def test_non_finite_refused() -> None:
    with pytest.raises(ValueError):
        content_hash({"x": float("nan")})
