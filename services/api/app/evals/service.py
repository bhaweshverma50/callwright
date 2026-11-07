"""Per-agent evaluator settings (007 T036, T039; FR-008, FR-034, FR-038, FR-039).

No row means: on when the evaluator is on by default, no overrides, not headline. Every write is
a full replacement of ``{enabled, overrides, is_headline}``; there is no partial update, so two
tabs saving the same check leave the last save whole.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.core.errors import ProblemError, field_error, not_found, validation_failed
from app.evals.models import AgentEvalSetting
from app.evaluators import service as catalog
from app.evaluators.models import EvaluatorRow
from app.evaluators.settings import effective, served_schema, validate_overrides
from app.llms.client import billable_cost, token_cost

MAX_HEADLINE = 4
HEADLINE_LIMIT_MESSAGE = "Up to 4 headline checks per agent"
# Rough size of one judge request (a few minutes of transcript and the reply) for the cost hint.
EST_INPUT_TOKENS = 3_000
EST_OUTPUT_TOKENS = 250


@dataclass
class Resolved:
    """One evaluator as it applies to one agent."""

    row: EvaluatorRow
    setting: AgentEvalSetting | None
    schema: dict[str, Any]
    values: dict[str, Any]
    adjusted: list[str]

    @property
    def enabled(self) -> bool:
        return self.setting.enabled if self.setting is not None else self.row.enabled_by_default


async def require_agent(session: AsyncSession, agent_id: str) -> Agent:
    agent = await session.get(Agent, agent_id)
    if agent is None or agent.deleted_at is not None:
        raise not_found("agent")
    return agent


def agent_type_of(agent: Agent) -> str:
    return "flow" if agent.type == "flow" else "single_prompt"


async def resolve_all(session: AsyncSession, agent: Agent, judge_models: Sequence[str]) -> list[Resolved]:
    rows = await catalog.list_evaluators(session, agent_type=agent_type_of(agent))
    settings = {
        s.evaluator_id: s
        for s in (
            await session.execute(select(AgentEvalSetting).where(AgentEvalSetting.agent_id == agent.id))
        ).scalars()
    }
    out = []
    for row in rows:
        schema = served_schema(row.settings_schema or {"fields": []}, judge_models)
        setting = settings.get(row.id)
        values, adjusted = effective(schema, setting.overrides if setting else None)
        out.append(Resolved(row, setting, schema, values, adjusted))
    return out


def est_cost(row: EvaluatorRow, values: Mapping[str, Any], judge_models: Sequence[str]) -> float | None:
    if row.cost_class != "llm_judge":
        return None
    model = str(values.get("judge_model") or judge_models[0])
    raw = token_cost(model.partition("/")[2] or model, EST_INPUT_TOKENS, EST_OUTPUT_TOKENS)
    return float(billable_cost(raw).quantize(Decimal("0.000001")))


def setting_view(r: Resolved, judge_models: Sequence[str]) -> dict[str, Any]:
    s = r.setting
    overrides = dict(s.overrides or {}) if s else {}
    return {
        "evaluator_id": r.row.id,
        "name": r.row.name,
        "display_name": r.row.display_name,
        "description": r.row.description,
        "kind": r.row.kind,
        "scope": r.row.scope,
        "cost_class": r.row.cost_class,
        "output_kind": r.row.output_kind,
        "enabled": r.enabled,
        "enabled_by_default": r.row.enabled_by_default,
        "is_overridden": bool(overrides),
        "adjusted_fields": r.adjusted,
        "is_headline": bool(s and s.is_headline),
        "headline_position": s.headline_position if s and s.is_headline else None,
        "overrides": overrides,
        "effective_settings": r.values,
        "settings_schema": r.schema,
        "current_version": r.row.current_version,
        "est_cost_per_call_usd": est_cost(r.row, r.values, judge_models),
    }


async def list_settings(
    session: AsyncSession, agent_id: str, judge_models: Sequence[str]
) -> list[dict[str, Any]]:
    agent = await require_agent(session, agent_id)
    return [setting_view(r, judge_models) for r in await resolve_all(session, agent, judge_models)]


async def put_setting(
    session: AsyncSession,
    *,
    workspace_id: str,
    user_id: str,
    agent_id: str,
    evaluator_id: str,
    body: Mapping[str, Any],
    judge_models: Sequence[str],
) -> dict[str, Any]:
    agent = await require_agent(session, agent_id)
    row = await session.get(EvaluatorRow, evaluator_id)
    if row is None or row.deleted_at is not None:
        raise not_found("evaluator")
    if agent_type_of(agent) not in row.agent_types:
        raise validation_failed(
            [field_error("/evaluator_id", "invalid_format", "This check does not apply to this agent type")]
        )
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        raise validation_failed([field_error("/enabled", "required", "Choose on or off")])
    headline = body.get("is_headline", False)
    if not isinstance(headline, bool):
        raise validation_failed([field_error("/is_headline", "invalid_format", "Choose yes or no")])
    schema = served_schema(row.settings_schema or {"fields": []}, judge_models)
    overrides = body.get("overrides") or {}
    errors = validate_overrides(schema, overrides)
    if errors:
        raise validation_failed(errors)
    # Overrides equal to the defaults are not stored, so a later default change still applies.
    defaults = {f["key"]: f.get("default") for f in schema.get("fields") or []}
    overrides = {k: v for k, v in dict(overrides).items() if defaults.get(k) != v}
    rows = {
        s.evaluator_id: s
        for s in (
            await session.execute(
                select(AgentEvalSetting).where(AgentEvalSetting.agent_id == agent_id).with_for_update()
            )
        ).scalars()
    }
    current = rows.get(evaluator_id)
    position = current.headline_position if current is not None and current.is_headline else None
    if headline and position is None:
        taken = {s.headline_position for s in rows.values() if s.is_headline}
        free = [p for p in range(1, MAX_HEADLINE + 1) if p not in taken]
        if not free:
            raise ProblemError(409, "headline_limit", "Headline limit", HEADLINE_LIMIT_MESSAGE)
        position = free[0]
    now = datetime.now(UTC)
    if current is None:
        current = AgentEvalSetting(agent_id=agent_id, evaluator_id=evaluator_id, workspace_id=workspace_id)
        session.add(current)
    current.enabled = enabled
    current.overrides = overrides
    current.is_headline = headline
    current.headline_position = position if headline else None
    current.updated_by = user_id
    current.updated_at = now
    await session.flush()
    values, adjusted = effective(schema, overrides)
    return setting_view(Resolved(row, current, schema, values, adjusted), judge_models)
