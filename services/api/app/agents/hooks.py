"""Hook registries for blocks other features own (T016, T086, research R5, R14, R15).

002 stores, hashes, diffs and versions every AgentConfig block, but some blocks belong to later
features. Instead of importing them (which would invert the build order, architecture section
3), 002 calls whatever they register here at import time of their module:

* ``register_validator(block, fn)``: called by ``agents.service.validate_config`` (save, publish,
  ``POST /v1/agents/validate``) with a :class:`HookContext`. Returns a :class:`HookIssues`
  (errors block save, publish blockers block publish, warnings inform). Used by 004 (``flow``),
  005 (``tool_ids``, ``kb_ids``: ``missing_reference``), 007 (``evals``) and 010.
* ``register_snapshot_resolver(block, fn)``: called when a version is recorded
  (``agent_versions.service.create_version`` and ``snapshot_for_test``). The return value is
  written to ``config[block]`` of the version only, never to the draft. 005 registers ``tools``
  (full tool definitions, secrets as masked refs, FR-028) and ``knowledge`` (kb ids plus retrieval
  settings, T089); 004 may register ``flow`` (compiled graph). The content hash covers resolved
  blocks, so a changed tool definition yields a new test snapshot.
* ``register_usage_checker(fn)``: called by ``agents.service.delete_agent``; returns the live
  attachments (phone numbers, WhatsApp channels, outbound campaigns) that block deletion with
  ``409 agent_in_use``. Registered by 010.
* ``register_duplicate_hook(fn)``: called by ``agents.service.duplicate_agent`` after the copy
  is written, in the same transaction (004 copies the flow draft).

Flow-node overrides (004): every per-node model, voice or STT override MUST be validated with
``agents.service.validate_override(path, value)``, which uses the same ``controls`` range table
that ``GET /v1/voices/catalog`` serves (FR-047, T104). Do not keep a second range table.

Hooks may be plain functions or coroutines. Registration is process-wide; tests use
``registered(...)`` to install hooks temporarily.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

Issue = dict[str, str]


@dataclass
class HookIssues:
    errors: list[Issue] = field(default_factory=list)
    publish_blockers: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)


@dataclass(frozen=True)
class HookContext:
    """What a validator or snapshot resolver sees. ``session`` is scoped to ``workspace_id``
    (RLS) and is ``None`` for pure validation without a database (unit tests)."""

    block: str
    value: Any
    config: Mapping[str, Any]
    agent_type: str
    workspace_id: str | None
    agent_id: str | None
    session: AsyncSession | None


@dataclass(frozen=True)
class Attachment:
    kind: str
    id: str
    label: str


@dataclass(frozen=True)
class UsageContext:
    session: AsyncSession
    workspace_id: str
    agent_id: str


@dataclass(frozen=True)
class DuplicateContext:
    session: AsyncSession
    workspace_id: str
    source_agent_id: str
    new_agent_id: str
    config: Mapping[str, Any]


Validator = Callable[[HookContext], HookIssues | Awaitable[HookIssues]]
SnapshotResolver = Callable[[HookContext], Any]
UsageChecker = Callable[[UsageContext], list[Attachment] | Awaitable[list[Attachment]]]
DuplicateHook = Callable[[DuplicateContext], Awaitable[None] | None]

_validators: dict[str, list[Validator]] = {}
_resolvers: dict[str, SnapshotResolver] = {}
_usage_checkers: list[UsageChecker] = []
_duplicate_hooks: list[DuplicateHook] = []

# Snapshot-only blocks: written by resolvers into versions, never accepted on a draft save.
SNAPSHOT_ONLY_BLOCKS = frozenset({"tools", "knowledge"})


def register_validator(block: str, fn: Validator) -> None:
    _validators.setdefault(block, []).append(fn)


def register_snapshot_resolver(block: str, fn: SnapshotResolver) -> None:
    if block in _resolvers and _resolvers[block] is not fn:
        raise ValueError(f"a snapshot resolver for {block!r} is already registered")
    _resolvers[block] = fn


def register_usage_checker(fn: UsageChecker) -> None:
    _usage_checkers.append(fn)


def register_duplicate_hook(fn: DuplicateHook) -> None:
    _duplicate_hooks.append(fn)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def run_validators(make_context: Callable[[str], HookContext]) -> HookIssues:
    merged = HookIssues()
    for block, fns in list(_validators.items()):
        for fn in list(fns):
            result: HookIssues = await _maybe_await(fn(make_context(block)))
            merged.errors.extend(result.errors)
            merged.publish_blockers.extend(result.publish_blockers)
            merged.warnings.extend(result.warnings)
    return merged


async def run_snapshot_resolvers(make_context: Callable[[str], HookContext]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for block, fn in sorted(_resolvers.items()):
        out[block] = await _maybe_await(fn(make_context(block)))
    return out


async def run_usage_checkers(ctx: UsageContext) -> list[Attachment]:
    found: list[Attachment] = []
    for fn in list(_usage_checkers):
        found.extend(await _maybe_await(fn(ctx)))
    return found


async def run_duplicate_hooks(ctx: DuplicateContext) -> None:
    for fn in list(_duplicate_hooks):
        await _maybe_await(fn(ctx))


@contextmanager
def registered(
    *,
    validators: Mapping[str, Validator] | None = None,
    resolvers: Mapping[str, SnapshotResolver] | None = None,
    usage_checkers: list[UsageChecker] | None = None,
    duplicate_hooks: list[DuplicateHook] | None = None,
) -> Iterator[None]:
    """Install hooks for the duration of a block (tests). A resolver given here temporarily
    replaces one registered by a feature module (005 registers ``tools`` and ``knowledge``)."""
    replaced = {block: _resolvers.pop(block) for block in resolvers or {} if block in _resolvers}
    for block, v in (validators or {}).items():
        register_validator(block, v)
    for block, r in (resolvers or {}).items():
        register_snapshot_resolver(block, r)
    for u in usage_checkers or []:
        register_usage_checker(u)
    for d in duplicate_hooks or []:
        register_duplicate_hook(d)
    try:
        yield
    finally:
        for block, v in (validators or {}).items():
            _validators[block].remove(v)
            if not _validators[block]:
                del _validators[block]
        for block in resolvers or {}:
            _resolvers.pop(block, None)
        _resolvers.update(replaced)
        for u in usage_checkers or []:
            _usage_checkers.remove(u)
        for d in duplicate_hooks or []:
            _duplicate_hooks.remove(d)
