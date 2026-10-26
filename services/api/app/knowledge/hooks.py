"""005's registrations in 002's hook registries (T077): the ``kb_ids`` validator and the
``knowledge`` snapshot resolver (``[{kb_id, name, description}]`` captured at save and publish,
used by the worker to word ``kb_search``). Imported by ``app.knowledge.router``."""

from __future__ import annotations

from typing import Any

from app.agents import hooks
from app.knowledge import service


async def validate_kb_ids(ctx: hooks.HookContext) -> hooks.HookIssues:
    ids = [k for k in ctx.value or [] if isinstance(k, str)]
    if ctx.session is None or not ids:
        return hooks.HookIssues()
    found = await service.kbs_by_id(ctx.session, ids)
    issues = hooks.HookIssues()
    for i, kb_id in enumerate(ids):
        if kb_id not in found:
            issues.publish_blockers.append(
                {
                    "pointer": f"/kb_ids/{i}",
                    "code": "missing_reference",
                    "message": f"Knowledge base {kb_id} no longer exists.",
                }
            )
    counts = await service.counts_for(ctx.session, [k for k in ids if k in found])
    for kb_id, c in counts.items():
        if c.ready_count == 0:
            issues.warnings.append(
                {
                    "pointer": "/kb_ids",
                    "code": "knowledge_base_not_ready",
                    "message": f"{found[kb_id].name} has no processed documents yet.",
                }
            )
    return issues


async def resolve_knowledge(ctx: hooks.HookContext) -> list[dict[str, Any]] | None:
    ids = [k for k in ctx.config.get("kb_ids") or [] if isinstance(k, str)]
    if ctx.session is None or not ids:
        return None
    described = list(await service.describe_for_snapshot(ctx.session, ids))
    return described or None


def register() -> None:
    hooks.register_validator("kb_ids", validate_kb_ids)
    hooks.register_snapshot_resolver("knowledge", resolve_knowledge)


register()
