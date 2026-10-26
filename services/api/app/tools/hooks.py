"""005's registrations in 002's hook registries (T025): the ``tool_ids`` validator and the
``tools`` snapshot resolver, so every recorded version (save, publish, test snapshot) embeds the
resolved tool definitions (research R2). Imported by ``app.tools.router``."""

from __future__ import annotations

from typing import Any

from app.agents import hooks
from app.tools import service


async def validate_tool_ids(ctx: hooks.HookContext) -> hooks.HookIssues:
    ids = [t for t in ctx.value or [] if isinstance(t, str)]
    if ctx.session is None or not ids:
        return hooks.HookIssues()
    found = await service.tools_by_id(ctx.session, ids)
    missing, duplicates = service.set_issues(ids, found)
    blockers = [
        {**m, "message": f"Tool {ids[int(m['pointer'].rsplit('/', 1)[1])]} no longer exists."}
        for m in missing
    ]
    blockers += [
        {
            "pointer": "/tool_ids",
            "code": "tool_name_conflict",
            "message": f"Two attached tools are named {name}.",
        }
        for name in duplicates
    ]
    return hooks.HookIssues(publish_blockers=blockers)


async def resolve_tools(ctx: hooks.HookContext) -> list[dict[str, Any]] | None:
    ids = [t for t in ctx.config.get("tool_ids") or [] if isinstance(t, str)]
    if ctx.session is None or not ids:
        return None
    specs = [spec.model_dump(mode="json") for spec in await service.resolve_for_snapshot(ctx.session, ids)]
    return specs or None


def register() -> None:
    hooks.register_validator("tool_ids", validate_tool_ids)
    hooks.register_snapshot_resolver("tools", resolve_tools)


register()
