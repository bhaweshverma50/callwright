"""Tool library: CRUD, secrets, attach sets, usages, snapshots, mock coverage (T023, T042, T085).

Every function takes an ``AsyncSession`` scoped to the workspace (RLS). Interfaces for others:

* ``resolve_for_snapshot(session, tool_ids) -> list[ToolSpec]`` (002 publish path via the
  ``tools`` snapshot resolver, 004 flow compile): full definitions, secret headers as
  ``secret_ref`` only.
* ``secrets_for_config(session, wrapper, workspace_id, config)``: plaintext for every
  ``secret_ref`` in a version snapshot (internal tool-secrets endpoint).
* ``mock_coverage(session, agent_id)``: attached HTTP tools without a canned response, plus flow
  webhook nodes reported by 004 through ``register_flow_mock_hook``.
"""

from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.agents import service as agents
from app.core.config import Settings
from app.core.errors import ProblemError, not_found, validation_failed
from app.core.ids import is_valid_id, new_id
from app.core.secrets import KeyWrapper, LocalKeyWrapper, delete_secret, get_secret, put_secret
from app.tools.models import Tool
from app.tools.schemas import CONFIG_MODELS, ToolCreate, ToolSpec, ToolUpdate
from app.tools.validation import Issue, issue, validate_tool

MAX_TOOLS_PER_AGENT = 25
COPY_SUFFIX = "_copy"


@dataclass(frozen=True)
class ToolActor:
    workspace_id: str
    user_id: str | None
    allow_http: bool = False

    def agent_actor(self) -> agents.Actor:
        return agents.Actor(
            workspace_id=self.workspace_id, user_id=self.user_id, allow_http_webhook=self.allow_http
        )


def key_wrapper(settings: Settings) -> KeyWrapper:
    return LocalKeyWrapper(settings.secrets_master_key.get_secret_value())


def tool_in_use(agent_rows: Sequence[tuple[str, str]]) -> ProblemError:
    return ProblemError(
        409,
        "tool_in_use",
        "Tool is in use",
        "Detach the tool from these agents first, or delete with force to detach it from drafts.",
        extra={"agents": [{"agent_id": a, "agent_name": n} for a, n in agent_rows]},
    )


def name_conflict(names: Iterable[str]) -> ProblemError:
    listed = ", ".join(sorted(set(names)))
    return ProblemError(
        422,
        "tool_name_conflict",
        "Tool names must be unique",
        f"An agent cannot use two tools with the same name ({listed}). Rename one of them first.",
    )


# Secret headers ---------------------------------------------------------------------------


def _secret_name(tool_id: str) -> str:
    return f"tool_hdr:{tool_id}:{ULID()}"


async def _store_headers(
    session: AsyncSession,
    wrapper: KeyWrapper,
    workspace_id: str,
    tool_id: str,
    incoming: list[dict[str, Any]],
    existing: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[Issue]]:
    """Stored header list for ``incoming``: new secret values are encrypted, a secret header
    sent without a value keeps its stored secret, and secrets no longer used are deleted."""
    old_secret = [h for h in existing if h.get("secret") and h.get("secret_ref")]
    kept: set[str] = set()
    created: list[str] = []
    stored: list[dict[str, Any]] = []
    issues: list[Issue] = []
    for i, header in enumerate(incoming):
        name = str(header["name"])
        if not header.get("secret"):
            stored.append({"name": name, "value": header.get("value"), "secret": False})
            continue
        value = header.get("value")
        if value:
            ref = _secret_name(tool_id)
            secret = await put_secret(session, wrapper, workspace_id, ref, str(value))
            created.append(ref)
            stored.append({"name": name, "secret": True, "secret_ref": ref, "masked_value": secret.masked})
            continue
        match = next(
            (
                h
                for h in old_secret
                if header.get("secret_ref") and h["secret_ref"] == header.get("secret_ref")
            ),
            None,
        ) or next((h for h in old_secret if str(h["name"]).lower() == name.lower()), None)
        if match is None or match["secret_ref"] in kept:
            issues.append(issue(f"/config/headers/{i}/value", "required", "Enter the secret value."))
            continue
        kept.add(match["secret_ref"])
        stored.append(
            {
                "name": name,
                "secret": True,
                "secret_ref": match["secret_ref"],
                "masked_value": match.get("masked_value"),
            }
        )
    if issues:
        for ref in created:
            await delete_secret(session, workspace_id, ref)
        return [], issues
    for header in old_secret:
        if header["secret_ref"] not in kept:
            await delete_secret(session, workspace_id, str(header["secret_ref"]))
    return stored, []


async def _delete_all_secrets(session: AsyncSession, tool: Tool) -> None:
    for header in tool.config.get("headers") or []:
        if header.get("secret") and header.get("secret_ref"):
            await delete_secret(session, tool.workspace_id, str(header["secret_ref"]))


def public_config(tool: Tool) -> dict[str, Any]:
    """Config as the API returns it: secret header values are never present, only masks."""
    config = copy.deepcopy(tool.config)
    if "headers" in config:
        config["headers"] = [
            {
                "name": h["name"],
                "value": None,
                "secret": True,
                "secret_ref": h.get("secret_ref"),
                "masked_value": h.get("masked_value"),
            }
            if h.get("secret")
            else {"name": h["name"], "value": h.get("value"), "secret": False}
            for h in config["headers"]
        ]
    return config


def snapshot_config(config: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dict(config))
    if "headers" in out:
        out["headers"] = [
            {"name": h["name"], "secret": True, "secret_ref": h.get("secret_ref")}
            if h.get("secret")
            else {"name": h["name"], "value": h.get("value"), "secret": False}
            for h in out["headers"]
        ]
    return out


def tool_view(tool: Tool, usage_count: int = 0) -> dict[str, Any]:
    return {
        "id": tool.id,
        "type": tool.type,
        "name": tool.name,
        "description": tool.description,
        "config": public_config(tool),
        "mock_response": tool.mock_response,
        "usage_count": usage_count,
        "created_at": tool.created_at.isoformat(),
        "updated_at": tool.updated_at.isoformat(),
    }


# CRUD ---------------------------------------------------------------------------------------


def normalized_config(tool_type: str, config: Mapping[str, Any]) -> dict[str, Any]:
    model = CONFIG_MODELS[tool_type].model_validate(dict(config))
    data: dict[str, Any] = model.model_dump(mode="json")
    return data


async def _config_for_write(
    session: AsyncSession,
    wrapper: KeyWrapper,
    actor: ToolActor,
    tool_id: str,
    tool_type: str,
    name: str,
    config: Mapping[str, Any],
    mock_response: str | None,
    existing_headers: list[dict[str, Any]],
) -> dict[str, Any]:
    issues = validate_tool(tool_type, name, config, mock_response, allow_http=actor.allow_http)
    if issues:
        raise validation_failed(issues)
    normalized = normalized_config(tool_type, config)
    if tool_type == "http":
        headers, header_issues = await _store_headers(
            session, wrapper, actor.workspace_id, tool_id, normalized["headers"], existing_headers
        )
        if header_issues:
            raise validation_failed(header_issues)
        normalized["headers"] = headers
    return normalized


async def create_tool(session: AsyncSession, actor: ToolActor, wrapper: KeyWrapper, body: ToolCreate) -> Tool:
    tool_id = new_id("tool")
    config = await _config_for_write(
        session, wrapper, actor, tool_id, body.type, body.name, body.config, body.mock_response, []
    )
    tool = Tool(
        id=tool_id,
        workspace_id=actor.workspace_id,
        type=body.type,
        name=body.name,
        description=body.description,
        config=config,
        mock_response=body.mock_response,
        created_by=actor.user_id,
    )
    session.add(tool)
    await session.flush()
    await session.refresh(tool)
    return tool


async def get_tool(session: AsyncSession, tool_id: str) -> Tool:
    tool = await session.get(Tool, tool_id) if is_valid_id(tool_id, "tool") else None
    if tool is None:
        raise not_found("tool")
    return tool


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_tools(
    session: AsyncSession,
    *,
    tool_type: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Tool], int]:
    query = select(Tool)
    if tool_type:
        query = query.where(Tool.type == tool_type)
    if search:
        pattern = f"%{_escape_like(search.lower())}%"
        query = query.where(
            func.lower(Tool.name).like(pattern, escape="\\")
            | func.lower(Tool.description).like(pattern, escape="\\")
        )
    total = int((await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one())
    rows = (
        await session.execute(
            query.order_by(Tool.updated_at.desc(), Tool.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars()
    return list(rows), total


async def update_tool(
    session: AsyncSession, actor: ToolActor, wrapper: KeyWrapper, tool_id: str, body: ToolUpdate
) -> Tool:
    tool = await get_tool(session, tool_id)
    sent = body.model_fields_set
    name = body.name if body.name is not None else tool.name
    mock = body.mock_response if "mock_response" in sent else tool.mock_response
    if body.config is not None:
        config_in: Mapping[str, Any] = body.config
    else:
        # Re-validate the stored config with the new name and mock (secrets stay as they are).
        config_in = public_config(tool)
    config = await _config_for_write(
        session,
        wrapper,
        actor,
        tool.id,
        tool.type,
        name,
        config_in,
        mock,
        list(tool.config.get("headers") or []),
    )
    tool.name = name
    if body.description is not None:
        tool.description = body.description
    tool.config = config
    tool.mock_response = mock
    tool.updated_at = datetime.now(UTC)
    await session.flush()
    return tool


async def _unique_copy_name(session: AsyncSession, name: str) -> str:
    base = (name + COPY_SUFFIX)[:64]
    taken = set(
        (
            await session.execute(
                select(Tool.name).where(Tool.name.like(f"{_escape_like(base)}%", escape="\\"))
            )
        )
        .scalars()
        .all()
    )
    if base not in taken:
        return base
    for n in range(2, 1000):
        candidate = f"{base[: 64 - len(str(n)) - 1]}_{n}"
        if candidate not in taken:
            return candidate
    return base


async def duplicate_tool(session: AsyncSession, actor: ToolActor, wrapper: KeyWrapper, tool_id: str) -> Tool:
    source = await get_tool(session, tool_id)
    copy_id = new_id("tool")
    config = copy.deepcopy(source.config)
    if "headers" in config:
        headers = []
        for header in config["headers"]:
            if header.get("secret") and header.get("secret_ref"):
                value = await get_secret(session, wrapper, source.workspace_id, str(header["secret_ref"]))
                if value is None:
                    continue
                ref = _secret_name(copy_id)
                await put_secret(session, wrapper, actor.workspace_id, ref, value)
                header = {**header, "secret_ref": ref}
            headers.append(header)
        config["headers"] = headers
    tool = Tool(
        id=copy_id,
        workspace_id=actor.workspace_id,
        type=source.type,
        name=await _unique_copy_name(session, source.name),
        description=source.description,
        config=config,
        mock_response=source.mock_response,
        created_by=actor.user_id,
    )
    session.add(tool)
    await session.flush()
    await session.refresh(tool)
    return tool


# Usages -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Usage:
    agent_id: str
    agent_name: str
    in_draft: bool
    published_version_ids: list[str]


_USAGE_SQL = text("""
    SELECT a.id, a.name,
           a.draft_config @> jsonb_build_object('tool_ids', jsonb_build_array(CAST(:tool_id AS text)))
             AS in_draft,
           CASE WHEN v.config @> jsonb_build_object('tools',
                  jsonb_build_array(jsonb_build_object('tool_id', CAST(:tool_id AS text))))
                THEN v.id END AS published_id
      FROM agents a
      LEFT JOIN agent_versions v ON v.id = a.pinned_version_id
     WHERE a.deleted_at IS NULL
       AND (a.draft_config @> jsonb_build_object('tool_ids', jsonb_build_array(CAST(:tool_id AS text)))
            OR v.config @> jsonb_build_object('tools',
                 jsonb_build_array(jsonb_build_object('tool_id', CAST(:tool_id AS text)))))
     ORDER BY a.name, a.id
""")


async def usages(session: AsyncSession, tool_id: str) -> list[Usage]:
    rows = (await session.execute(_USAGE_SQL, {"tool_id": tool_id})).all()
    return [
        Usage(
            agent_id=r[0], agent_name=r[1], in_draft=bool(r[2]), published_version_ids=[r[3]] if r[3] else []
        )
        for r in rows
    ]


async def usage_counts(session: AsyncSession, tool_ids: Sequence[str]) -> dict[str, int]:
    if not tool_ids:
        return {}
    rows = (
        await session.execute(
            text("""
            SELECT t.id, count(a.id)
              FROM unnest(CAST(:ids AS text[])) AS t(id)
              LEFT JOIN agents a ON a.deleted_at IS NULL AND (
                   a.draft_config @> jsonb_build_object('tool_ids', jsonb_build_array(t.id))
                OR EXISTS (SELECT 1 FROM agent_versions v WHERE v.id = a.pinned_version_id
                           AND v.config @> jsonb_build_object('tools',
                               jsonb_build_array(jsonb_build_object('tool_id', t.id)))))
             GROUP BY t.id
            """),
            {"ids": list(tool_ids)},
        )
    ).all()
    return {str(r[0]): int(r[1]) for r in rows}


async def delete_tool(session: AsyncSession, actor: ToolActor, tool_id: str, *, force: bool) -> list[str]:
    tool = await get_tool(session, tool_id)
    drafts = [(u.agent_id, u.agent_name) for u in await usages(session, tool_id) if u.in_draft]
    if drafts and not force:
        raise tool_in_use(drafts)
    for agent_id, _ in drafts:
        agent = await agents.get_agent(session, agent_id)
        remaining = [t for t in agent.draft_config.get("tool_ids") or [] if t != tool_id]
        await agents.update_draft(session, actor.agent_actor(), agent_id, patch={"tool_ids": remaining})
    await _delete_all_secrets(session, tool)
    await session.delete(tool)
    await session.flush()
    return [a for a, _ in drafts]


# Agent attach sets ----------------------------------------------------------------------------


async def tools_by_id(session: AsyncSession, tool_ids: Sequence[str]) -> dict[str, Tool]:
    valid = [t for t in tool_ids if is_valid_id(t, "tool")]
    if not valid:
        return {}
    rows = (await session.execute(select(Tool).where(Tool.id.in_(valid)))).scalars()
    return {t.id: t for t in rows}


def set_issues(tool_ids: Sequence[str], found: Mapping[str, Tool]) -> tuple[list[Issue], list[str]]:
    """Missing references and duplicate names in an attach set."""
    missing = [
        issue(f"/tool_ids/{i}", "missing_reference", "This tool no longer exists.")
        for i, t in enumerate(tool_ids)
        if t not in found
    ]
    names = [found[t].name for t in tool_ids if t in found]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    return missing, duplicates


async def agent_tools(session: AsyncSession, agent_id: str) -> list[Tool]:
    agent = await agents.get_agent(session, agent_id)
    ids = list(agent.draft_config.get("tool_ids") or [])
    found = await tools_by_id(session, ids)
    return [found[t] for t in ids if t in found]


async def set_agent_tools(
    session: AsyncSession, actor: ToolActor, agent_id: str, tool_ids: list[str]
) -> list[Tool]:
    await agents.get_agent(session, agent_id)
    if len(tool_ids) > MAX_TOOLS_PER_AGENT:
        raise validation_failed(
            [issue("/tool_ids", "too_many", f"An agent can use at most {MAX_TOOLS_PER_AGENT} tools.")]
        )
    found = await tools_by_id(session, tool_ids)
    missing, duplicates = set_issues(tool_ids, found)
    if missing:
        raise validation_failed(missing)
    if duplicates:
        raise name_conflict(duplicates)
    await agents.update_draft(session, actor.agent_actor(), agent_id, patch={"tool_ids": list(tool_ids)})
    return [found[t] for t in tool_ids]


# Snapshots and secrets for calls ---------------------------------------------------------------


def to_spec(tool: Tool) -> ToolSpec:
    return ToolSpec(
        tool_id=tool.id,
        type=tool.type,
        name=tool.name,
        description=tool.description,
        config=snapshot_config(tool.config),
        mock_response=tool.mock_response,
    )


async def resolve_for_snapshot(session: AsyncSession, tool_ids: Sequence[str]) -> list[ToolSpec]:
    found = await tools_by_id(session, tool_ids)
    return [to_spec(found[t]) for t in tool_ids if t in found]


def secret_refs(config: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for spec in config.get("tools") or []:
        for header in (spec.get("config") or {}).get("headers") or []:
            if header.get("secret") and header.get("secret_ref"):
                refs.append(str(header["secret_ref"]))
    return refs


async def secrets_for_config(
    session: AsyncSession, wrapper: KeyWrapper, workspace_id: str, config: Mapping[str, Any]
) -> dict[str, str]:
    """Plaintext for every secret_ref in a version snapshot; deleted secrets are left out."""
    out: dict[str, str] = {}
    for ref in secret_refs(config):
        value = await get_secret(session, wrapper, workspace_id, ref)
        if value is not None:
            out[ref] = value
    return out


# Mock coverage (US5) ---------------------------------------------------------------------------

FlowMockHook = Callable[[AsyncSession, str], Awaitable[list[dict[str, str]]]]
_flow_mock_hook: FlowMockHook | None = None


def register_flow_mock_hook(fn: FlowMockHook | None) -> None:
    """004: ``fn(session, agent_id)`` returns ``[{node_id, name}]`` webhook nodes lacking a mock."""
    global _flow_mock_hook
    _flow_mock_hook = fn


async def mock_coverage(session: AsyncSession, agent_id: str) -> dict[str, Any]:
    tools = await agent_tools(session, agent_id)
    missing: list[dict[str, Any]] = [
        {"source": "tool", "tool_id": t.id, "name": t.name, "tool_type": t.type}
        for t in tools
        if t.type == "http" and not (t.mock_response or "").strip()
    ]
    if _flow_mock_hook is not None:
        for node in await _flow_mock_hook(session, agent_id):
            missing.append({"source": "flow_node", "node_id": node["node_id"], "name": node["name"]})
    return {"ready": not missing, "missing": missing}


__all__ = [
    "ToolActor",
    "agent_tools",
    "create_tool",
    "delete_tool",
    "duplicate_tool",
    "get_tool",
    "key_wrapper",
    "list_tools",
    "mock_coverage",
    "register_flow_mock_hook",
    "resolve_for_snapshot",
    "secrets_for_config",
    "set_agent_tools",
    "update_tool",
    "usage_counts",
    "usages",
]
