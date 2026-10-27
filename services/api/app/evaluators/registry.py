"""Built-in evaluator registry and startup sync (007 T033, research R2, R3).

Built-ins are defined in code with a ``VERSION``. ``sync_builtins`` (admin role, at app and
worker start) upserts their global catalog rows under fixed ids and inserts an immutable version
row whenever the code's ``VERSION`` is new, pinning the prompt hash, rules and judge cutoff.
``instance_for`` returns the evaluator object for a catalog row and version definition.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text
from ulid import ULID

from app.core.config import Settings
from app.core.db import Database
from app.evaluators.base import Evaluator, SettingsField
from app.evaluators.builtins.anomaly_detection import AnomalyDetection
from app.evaluators.builtins.audio_silence import AudioSilence
from app.evaluators.builtins.factual_consistency import FactualConsistency
from app.evaluators.builtins.flow_completion import FlowCompletion
from app.evaluators.builtins.intent_fulfillment import IntentFulfillment
from app.evaluators.builtins.kb_relevance import KbRelevance
from app.evaluators.builtins.latency_slo import LatencySlo
from app.evaluators.builtins.node_dead_end import NodeDeadEnd
from app.evaluators.builtins.process_reward import ProcessReward
from app.evaluators.builtins.stuck_loop_detector import StuckLoopDetector
from app.evaluators.builtins.tool_call_correctness import ToolCallCorrectness
from app.evaluators.builtins.transition_correctness import TransitionCorrectness
from app.evaluators.custom.llm_judge_custom import LlmJudgeCustom
from app.evaluators.custom.phrase_check import PhraseCheck

BUILTIN_CLASSES: tuple[type[Evaluator], ...] = (
    AnomalyDetection,
    FactualConsistency,
    FlowCompletion,
    IntentFulfillment,
    KbRelevance,
    AudioSilence,
    NodeDeadEnd,
    ProcessReward,
    StuckLoopDetector,
    ToolCallCorrectness,
    TransitionCorrectness,
    LatencySlo,
)
BUILTINS: dict[str, Evaluator] = {cls.name: cls() for cls in BUILTIN_CLASSES}
CUSTOM_TYPES = ("phrase_check", "llm_judge_custom")


def builtin_id(name: str) -> str:
    """Fixed id of a built-in, the same in every database."""
    return f"evl_{ULID.from_bytes(hashlib.sha256(f'callwright:builtin:{name}'.encode()).digest()[:16])}"


def schema_json(fields: tuple[SettingsField, ...]) -> dict[str, Any]:
    return {"fields": [f.as_json() for f in fields]}


def definition(ev: Evaluator, settings: Settings) -> dict[str, Any]:
    return {
        "prompt_sha256": hashlib.sha256(ev.rules.encode()).hexdigest(),
        "rules": ev.rules,
        "cutoff": settings.eval_judge_pass_cutoff if ev.cost_class == "llm_judge" else None,
        "threshold_direction": ev.threshold_direction,
        "judge_model": settings.default_judge_model if ev.cost_class == "llm_judge" else None,
    }


async def sync_builtins(db: Database, settings: Settings) -> None:
    async with db.admin_transaction() as session:
        for ev in BUILTINS.values():
            evl = builtin_id(ev.name)
            await session.execute(
                text(
                    "insert into evaluators (id, workspace_id, kind, evaluator_type, name, display_name, "
                    "description, scope, cost_class, output_kind, agent_types, settings_schema, score_range, "
                    "current_version, enabled_by_default) values (:id, null, 'builtin', :name, :name, "
                    ":display, :description, :scope, :cost, :kind, :types, cast(:schema as jsonb), "
                    "cast(:range as jsonb), :version, :default_on) "
                    "on conflict (id) do update set display_name = excluded.display_name, "
                    "description = excluded.description, scope = excluded.scope, "
                    "cost_class = excluded.cost_class, output_kind = excluded.output_kind, "
                    "agent_types = excluded.agent_types, settings_schema = excluded.settings_schema, "
                    "score_range = excluded.score_range, "
                    "current_version = greatest(evaluators.current_version, excluded.current_version), "
                    "enabled_by_default = excluded.enabled_by_default, updated_at = now()"
                ),
                {
                    "id": evl,
                    "name": ev.name,
                    "display": ev.display_name,
                    "description": ev.description,
                    "scope": ev.scope,
                    "cost": ev.cost_class,
                    "kind": ev.output_kind,
                    "types": list(ev.agent_types),
                    "schema": json.dumps(schema_json(ev.settings_fields)),
                    "range": json.dumps({"min": ev.score_range[0], "max": ev.score_range[1]}),
                    "version": ev.VERSION,
                    "default_on": ev.enabled_by_default,
                },
            )
            spec = definition(ev, settings)
            await session.execute(
                text(
                    "insert into evaluator_versions (evaluator_id, version, workspace_id, definition, "
                    "judge_model) values (:id, :version, null, cast(:definition as jsonb), :judge) "
                    "on conflict do nothing"
                ),
                {
                    "id": evl,
                    "version": ev.VERSION,
                    "definition": json.dumps(spec),
                    "judge": spec["judge_model"],
                },
            )


def instance_for(evaluator_type: str, definition: Mapping[str, Any]) -> Evaluator:
    if evaluator_type == "phrase_check":
        return PhraseCheck(definition)
    if evaluator_type == "llm_judge_custom":
        return LlmJudgeCustom(definition)
    return BUILTINS[evaluator_type]


def main(argv: list[str]) -> int:
    """``python -m app.evaluators.registry sync``: upsert the built-in catalog (migrate role)."""
    import asyncio
    import sys

    from app.core.config import get_settings

    if argv != ["sync"]:
        print("usage: python -m app.evaluators.registry sync", file=sys.stderr)
        return 2

    async def run() -> None:
        settings = get_settings()
        db = Database(settings.database_url, settings.database_admin_url, pool_size=1)
        try:
            await sync_builtins(db, settings)
        finally:
            await db.dispose()

    asyncio.run(run())
    print(f"synced {len(BUILTINS)} built-in evaluators")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
