"""What the flows module registers with other features (plan "Dependencies").

* 002 ``flow`` snapshot resolver: every version recorded for a flow agent (saves of flow-wide
  settings, draft test calls) carries the current draft flow compiled, so a test call runs
  exactly what is on the canvas (research R16). Publish passes its own compiled block, kept as is.
* 002 ``flow`` validator: a version whose flow did not compile cannot be published.
* 002 duplicate hook: duplicating a flow agent copies its flow.
* 005 mock coverage hook: webhook nodes without a canned response.
* 003: flow agents may take calls now that the worker runs flows.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.agents import hooks as agent_hooks
from app.agents.models import Agent
from app.core.ids import new_id
from app.flows import assistant_fake, service
from app.flows.models import Flow
from app.llms.adapters.fake import PURPOSE_REPLIES
from app.tools import service as tools


async def resolve_flow(ctx: agent_hooks.HookContext) -> Any:
    if ctx.agent_type != "flow" or ctx.session is None or ctx.agent_id is None:
        return None
    if isinstance(ctx.value, Mapping) and ctx.value.get("compiled"):
        return dict(ctx.value)
    return await service.compile_draft(ctx.session, ctx.agent_id, ctx.config)


def validate_flow(ctx: agent_hooks.HookContext) -> agent_hooks.HookIssues:
    issues = agent_hooks.HookIssues()
    value = ctx.value
    if (
        ctx.agent_type == "flow"
        and isinstance(value, Mapping)
        and "compiled" in value
        and value["compiled"] is None
    ):
        issues.publish_blockers.append(
            {
                "pointer": "/flow",
                "code": "flow_has_errors",
                "message": "The flow has errors. Fix them in the flow builder.",
            }
        )
    return issues


async def duplicate_flow(ctx: agent_hooks.DuplicateContext) -> None:
    source = await service.flow_for_agent(ctx.session, ctx.source_agent_id)
    if source is None:
        return
    agent = await ctx.session.get(Agent, ctx.new_agent_id)
    now = datetime.now(UTC)
    copy_ = Flow(
        id=new_id("flw"),
        workspace_id=ctx.workspace_id,
        agent_id=ctx.new_agent_id,
        name=agent.name if agent is not None else source.name,
        graph=copy.deepcopy(source.graph),
        revision=1,
        last_validation=copy.deepcopy(source.last_validation),
        created_at=now,
        updated_at=now,
    )
    ctx.session.add(copy_)
    await ctx.session.flush()


def register() -> None:
    agent_hooks.register_snapshot_resolver("flow", resolve_flow)
    agent_hooks.register_validator("flow", validate_flow)
    agent_hooks.register_duplicate_hook(duplicate_flow)
    tools.register_flow_mock_hook(service.webhook_nodes_without_mock)
    tools.register_flow_usage_hook(service.tool_node_usages)
    PURPOSE_REPLIES["flow_assistant"] = assistant_fake.reply
