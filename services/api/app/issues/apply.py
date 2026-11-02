"""Apply a validated fix as a new agent version (009 T045; spec FR-020 to FR-022, research R5).

Everything happens in the caller's transaction, with the issue and the agent rows locked so a
concurrent publish cannot slip between the checks and the write:

1. Preconditions (FR-020): the issue is validated, the latest attempt of the current revision
   passed, the published version is still the attempt's base version and the saved draft has no
   changes since it. Refusals are 409 problems: ``wrong_status``, ``no_passing_validation``,
   ``base_version_changed``, ``draft_changed`` (``advisory_fix``, ``stale_revision`` too).
2. The configuration is the treatment batch's snapshot (``fix.variant_snapshot``), whose hash the
   attempt recorded. A tool description fix edits the tool itself when only this agent uses it,
   otherwise an agent-specific copy (same name, new description; secret headers re-stored) and
   the configuration points at the copy (FR-022).
3. ``agent_versions.create_version`` records (and unless ``publish`` is false, publishes) the
   version with release notes ``Fix for <issue id>: <title>``. The new version's content hash,
   with copied tool ids and secret references mapped back to the originals, must equal the
   validated hash; anything else (a tool or knowledge base edited since validation) rolls back.
4. The agent's draft (and a flow agent's graph) is set to the applied configuration so the editor
   shows it; the fix and the issue become ``applied``.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_versions import service as versions
from app.agent_versions.canonical import content_hash
from app.agents.models import Agent
from app.core.config import Settings
from app.core.errors import ProblemError
from app.issues.lifecycle import FINAL, transition, wrong_status
from app.issues.models import Issue, IssueFix
from app.issues.service import agent_deleted, current_fix, draft_matches, get_issue, latest_for_revision
from app.issues.validation import advisory_fix

NOTES_MAX = 500


def refused(code: str) -> ProblemError:
    messages = {
        "no_passing_validation": (
            "Fix not validated",
            "This fix has no passing validation. Validate it, then apply.",
        ),
        "base_version_changed": (
            "Agent changed",
            "Another version was published after this fix was validated. Validate the fix again against the "
            "current version, then apply.",
        ),
        "draft_changed": (
            "Draft changed",
            "The agent's draft has unsaved or saved changes since this fix was validated. Publish or discard "
            "them, validate the fix again, then apply.",
        ),
        "config_changed": (
            "Configuration changed",
            "A tool or knowledge base this agent uses changed since the fix was validated. Validate the fix "
            "again, then apply.",
        ),
        "stale_revision": (
            "Newer fix",
            "This is no longer the current fix. Reload the issue and apply the current one.",
        ),
    }
    title, detail = messages[code]
    return ProblemError(409, code, title, detail)


# Tool ids ---------------------------------------------------------------------------------------


def remap(config: Mapping[str, Any], mapping: Mapping[str, str]) -> dict[str, Any]:
    """``config`` with every id in ``mapping`` replaced (tool ids and secret references), and the
    flow block's graph hashes recomputed for the rewritten graph."""
    if not mapping:
        return copy.deepcopy(dict(config))
    raw = json.dumps(config, ensure_ascii=False)
    for old, new in mapping.items():
        raw = raw.replace(json.dumps(old)[1:-1], json.dumps(new)[1:-1])
    out: dict[str, Any] = json.loads(raw)
    flow = out.get("flow")
    if isinstance(flow, dict) and isinstance(flow.get("graph"), dict):
        from app.flows import compiler

        digest = compiler.graph_hash(flow["graph"])
        if "graph_hash" in flow:
            flow["graph_hash"] = digest
        if isinstance(flow.get("compiled"), dict) and "graph_hash" in flow["compiled"]:
            flow["compiled"]["graph_hash"] = digest
    return out


def normalised_hash(config: Mapping[str, Any], copies: list[dict[str, Any]]) -> str:
    """The content hash with copied tools mapped back to the originals (SC-001 audit too)."""
    back: dict[str, str] = {}
    for c in copies:
        back[str(c["copy_tool_id"])] = str(c["original_tool_id"])
        back.update({str(k): str(v) for k, v in (c.get("secret_refs") or {}).items()})
    return content_hash(remap(config, back))


async def other_users(session: AsyncSession, tool_id: str, agent_id: str) -> set[str]:
    from app.flows import service as flows
    from app.tools import service as tools

    users = {u.agent_id for u in await tools.usages(session, tool_id)}
    users |= {str(u["agent_id"]) for u in await flows.tool_node_usages(session, tool_id)}
    users.discard(agent_id)
    return users


@dataclass
class ToolChange:
    copies: list[dict[str, Any]] = field(default_factory=list)
    forward: dict[str, str] = field(default_factory=dict)


async def change_tool(
    session: AsyncSession, settings: Settings, agent: Agent, fix: IssueFix, user_id: str | None
) -> ToolChange:
    from app.tools import service as tools

    out = ToolChange()
    tool_id = str(fix.payload["tool_id"])
    tool = await tools.get_tool(session, tool_id)
    description = str(fix.payload["proposed_description"])
    if not await other_users(session, tool_id, agent.id):
        tool.description = description
        tool.updated_at = datetime.now(UTC)
        await session.flush()
        return out
    actor = tools.ToolActor(workspace_id=agent.workspace_id, user_id=user_id, allow_http=True)
    copy_ = await tools.duplicate_tool(session, actor, tools.key_wrapper(settings), tool_id)
    copy_.name = tool.name
    copy_.description = description
    await session.flush()
    refs: dict[str, str] = {}
    for old, new in zip(tool.config.get("headers") or [], copy_.config.get("headers") or [], strict=False):
        if old.get("secret_ref") and new.get("secret_ref") and old["secret_ref"] != new["secret_ref"]:
            refs[str(new["secret_ref"])] = str(old["secret_ref"])
    out.forward = {tool_id: copy_.id, **{v: k for k, v in refs.items()}}
    out.copies.append(
        {
            "original_tool_id": tool_id,
            "copy_tool_id": copy_.id,
            "copy_tool_name": copy_.name,
            "secret_refs": refs,
        }
    )
    return out


# Apply ------------------------------------------------------------------------------------------


@dataclass
class Applied:
    issue: Issue
    agent_version_id: str
    published: bool
    release_notes: str
    tool_copies: list[dict[str, Any]]
    draft_updated: bool


def release_notes(issue: Issue, extra: str | None) -> str:
    notes = f"Fix for {issue.id}: {issue.title} (/issues/{issue.id})"
    if extra and extra.strip():
        notes = f"{notes}\n{extra.strip()}"
    return notes[:NOTES_MAX]


async def apply(
    session: AsyncSession,
    settings: Settings,
    issue_id: str,
    *,
    fix_revision: int | None,
    publish: bool,
    extra_notes: str | None,
    user_id: str | None,
) -> Applied:
    issue = await get_issue(session, issue_id, lock=True)
    try:
        agent = await versions.lock_agent(session, issue.agent_id)
    except ProblemError as exc:
        raise agent_deleted() from exc
    if issue.status in FINAL:
        raise wrong_status(issue.status)
    fix = await current_fix(session, issue)
    if fix is not None and fix_revision is not None and fix_revision != fix.revision:
        raise refused("stale_revision")
    if fix is not None and fix.status == "advisory":
        raise advisory_fix()
    if fix is None or issue.status != "validated":
        raise refused("no_passing_validation")
    attempt = await latest_for_revision(session, issue.id, fix.revision)
    if attempt is None or attempt.status != "completed" or attempt.decision != "passed":
        raise refused("no_passing_validation")
    if agent.pinned_version_id != attempt.base_agent_version_id:
        raise refused("base_version_changed")
    if not await draft_matches(session, agent, attempt.base_agent_version_id):
        raise refused("draft_changed")
    validated = dict(fix.variant_snapshot or {})
    if not validated or content_hash(validated) != attempt.variant_config_hash:
        raise refused("no_passing_validation")

    change = ToolChange()
    if fix.kind == "tool_description_edit":
        change = await change_tool(session, settings, agent, fix, user_id)
    config = remap(validated, change.forward)
    notes = release_notes(issue, extra_notes)
    is_flow = agent.type == "flow"
    recorded = await versions.create_version(
        session,
        agent.id,
        config,
        note=notes,
        source="flow_publish" if is_flow else "save",
        publish=publish,
        user_id=user_id,
        allow_http_webhook=True,
    )
    version = recorded.version
    if normalised_hash(version.config, change.copies) != attempt.variant_config_hash:
        raise refused("config_changed")

    # The editor shows what was applied: the draft (and a flow agent's graph).
    draft = {k: v for k, v in versions.draft_part(config).items() if k != "flow"}
    versions.apply_draft(agent, draft, version)
    if is_flow:
        from app.flows import service as flows

        flow_row = await flows.flow_for_agent(session, agent.id)
        graph = (config.get("flow") or {}).get("graph") if isinstance(config.get("flow"), dict) else None
        if flow_row is not None and isinstance(graph, dict):
            flow_row.graph = copy.deepcopy(graph)
            flow_row.revision += 1
            flow_row.updated_at = datetime.now(UTC)
            flow_row.updated_by = user_id
            if publish:
                flow_row.last_published_version_id = version.id

    now = datetime.now(UTC)
    fix.status = "applied"
    issue.status = transition(issue.status, "apply")
    issue.applied_agent_version_id = version.id
    issue.applied_fix_revision = fix.revision
    issue.applied_tool_copies = change.copies
    issue.applied_at = now
    issue.applied_by = user_id
    issue.updated_at = now
    await session.flush()
    copies = [
        {"original_tool_id": c["original_tool_id"], "copy_tool_id": c["copy_tool_id"]} for c in change.copies
    ]
    return Applied(issue, version.id, publish, notes, copies, True)
