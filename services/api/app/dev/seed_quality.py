"""Quickstart fixtures for 007 (T012): agents, analysis variables, evaluator settings, runs and
labels written as the database owner into one existing workspace.

* "Booking desk" (single prompt) with ``appointment_booked`` and ``preferred_day`` variables and
  intent fulfillment switched on as a headline check; "Clinic flow" (flow agent).
* 10 labelled calls for intent fulfillment: 4 both pass, 2 both fail, 2 over-eager, 2 missed.
* 12 unlabelled calls for the review queue: 4 mixed verdicts, 3 all failed, 5 all passed.

Labels belong to the workspace owner. The built-in catalog is upserted first (idempotent).

    uv run python -m scripts.seed_007 --workspace ws_... \
        --dsn postgresql://callwright:callwright@localhost:55432/db
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from app.core.config import get_settings
from app.core.ids import new_id
from app.dev.seed_calls import AGENT_CONFIG
from app.evaluators.registry import BUILTINS, builtin_id, definition, schema_json

LINES = [
    ("agent", "Thanks for calling Bright Smiles. How can I help?"),
    ("user", "I'd like to book a cleaning appointment on Tuesday."),
    ("agent", "Tuesday at 10 works. Booked for you. Anything else?"),
]
CHECKS = ("latency_slo", "audio_silence", "intent_fulfillment", "tool_call_correctness", "kb_relevance")


@dataclass
class Seeded:
    workspace_id: str
    agents: dict[str, str] = field(default_factory=dict)
    labelled_calls: list[str] = field(default_factory=list)
    queue_calls: list[str] = field(default_factory=list)


def upsert_builtins(conn: psycopg.Connection[Any]) -> None:
    settings = get_settings()
    for ev in BUILTINS.values():
        evl = builtin_id(ev.name)
        conn.execute(
            "insert into evaluators (id, workspace_id, kind, evaluator_type, name, display_name, "
            "description, scope, cost_class, output_kind, agent_types, settings_schema, score_range, "
            "current_version, "
            "enabled_by_default) values (%s, null, 'builtin', %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, "
            "%s::jsonb, %s, %s) on conflict (id) do nothing",
            (
                evl,
                ev.name,
                ev.name,
                ev.display_name,
                ev.description,
                ev.scope,
                ev.cost_class,
                ev.output_kind,
                list(ev.agent_types),
                json.dumps(schema_json(ev.settings_fields)),
                json.dumps({"min": ev.score_range[0], "max": ev.score_range[1]}),
                ev.VERSION,
                ev.enabled_by_default,
            ),
        )
        spec = definition(ev, settings)
        conn.execute(
            "insert into evaluator_versions (evaluator_id, version, definition, judge_model) "
            "values (%s, %s, %s::jsonb, %s) on conflict do nothing",
            (evl, ev.VERSION, json.dumps(spec), spec["judge_model"]),
        )


def _agent(conn: psycopg.Connection[Any], ws: str, name: str, kind: str) -> tuple[str, str]:
    agent_id, version_id = new_id("agt"), new_id("agv")
    config = json.dumps({**AGENT_CONFIG, "type": kind, "prompt": "Book dental cleanings."}, sort_keys=True)
    with conn.transaction():
        conn.execute("SET CONSTRAINTS ALL DEFERRED")
        conn.execute(
            "insert into agent_versions (id, workspace_id, agent_id, version_number, schema_version, config, "
            "content_hash, source, summary) values (%s, %s, %s, 1, 1, %s::jsonb, %s, 'save', '{}'::jsonb)",
            (version_id, ws, agent_id, config, hashlib.sha256(config.encode()).hexdigest()),
        )
        conn.execute(
            "insert into agents (id, workspace_id, name, type, language, draft_config, draft_version_id) "
            "values (%s, %s, %s, %s, 'en-US', %s::jsonb, %s)",
            (agent_id, ws, name, kind, config, version_id),
        )
    return agent_id, version_id


def _call(conn: psycopg.Connection[Any], ws: str, agent: tuple[str, str], hours_ago: float) -> str:
    call_id = new_id("call")
    ended = datetime.now(UTC) - timedelta(hours=hours_ago)
    items = [
        {"type": "message", "role": r, "text": t, **({"turn_index": i} if r == "agent" else {})}
        for i, (r, t) in enumerate(LINES)
    ]
    conn.execute(
        "insert into calls (id, workspace_id, agent_id, agent_version_id, origin, channel, direction, "
        "status, created_at, connected_at, ended_at, completed_at, billable_seconds, sentiment, summary, "
        "pipeline_status, transcript) values (%s, %s, %s, %s, 'live', 'web', 'inbound', 'completed', "
        "%s, %s, %s, %s, 64, "
        "'positive', 'Caller booked a cleaning for Tuesday.', 'done', %s::jsonb)",
        (
            call_id,
            ws,
            agent[0],
            agent[1],
            ended - timedelta(seconds=67),
            ended - timedelta(seconds=64),
            ended,
            ended,
            json.dumps({"items": items}),
        ),
    )
    return call_id


def _run(
    conn: psycopg.Connection[Any], ws: str, call_id: str, agent_id: str, name: str, verdict: str
) -> None:
    group = f"erg_{new_id('evr')[4:]}"
    conn.execute(
        "insert into evaluator_run_groups (run_group_id, workspace_id, call_id, trigger, idempotency_key, "
        "status) values (%s, %s, %s, 'pipeline', %s, 'done')",
        (group, ws, call_id, f"seed:{group}"),
    )
    run_id = new_id("evr")
    score = 0.9 if verdict == "pass" else 0.2
    rationale = "Seeded: the goal was met." if verdict == "pass" else "Seeded: the goal was not met."
    conn.execute(
        "insert into evaluator_runs (id, workspace_id, call_id, agent_id, evaluator_id, evaluator_version, "
        "run_group_id, trigger, settings_hash, status, verdict, score, rationale, started_at, completed_at) "
        "values (%s, %s, %s, %s, %s, 1, %s, 'pipeline', 'seed', 'completed', %s, %s, %s, now(), now())",
        (run_id, ws, call_id, agent_id, builtin_id(name), group, verdict, score, rationale),
    )
    conn.execute(
        "insert into evaluator_result_items (workspace_id, run_id, position, verdict, score, rationale) "
        "values (%s, %s, 0, %s, %s, %s)",
        (ws, run_id, verdict, score, rationale),
    )


def seed(conn: psycopg.Connection[Any], workspace_id: str) -> Seeded:
    out = Seeded(workspace_id)
    upsert_builtins(conn)
    owner = conn.execute("select owner_user_id from workspaces where id = %s", (workspace_id,)).fetchone()
    if owner is None:
        raise SystemExit(f"no workspace {workspace_id}")
    booking = _agent(conn, workspace_id, "Booking desk", "single_prompt")
    flow = _agent(conn, workspace_id, "Clinic flow", "flow")
    out.agents = {"booking_desk": booking[0], "clinic_flow": flow[0]}
    now = datetime.now(UTC)
    for position, (name, kind, choices) in enumerate(
        [
            ("appointment_booked", "boolean", None),
            ("preferred_day", "choice", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]),
        ]
    ):
        conn.execute(
            "insert into analysis_variables (id, workspace_id, agent_id, name, type, description, choices, "
            "position, created_at, updated_at) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                new_id("var"),
                workspace_id,
                booking[0],
                name,
                kind,
                "True if a slot was confirmed" if kind == "boolean" else "The weekday the caller wants",
                choices,
                position,
                now,
                now,
            ),
        )
    conn.execute(
        "insert into agent_eval_settings (workspace_id, agent_id, evaluator_id, enabled, overrides, "
        "is_headline, headline_position, updated_at) values (%s, %s, %s, true, '{}'::jsonb, true, 1, now()) "
        "on conflict do nothing",
        (workspace_id, booking[0], builtin_id("intent_fulfillment")),
    )
    plan = [("pass", "good")] * 4 + [("fail", "bad")] * 2 + [("fail", "good")] * 2 + [("pass", "bad")] * 2
    for i, (verdict, label) in enumerate(plan):
        call = _call(conn, workspace_id, booking, 30 + i)
        _run(conn, workspace_id, call, booking[0], "intent_fulfillment", verdict)
        conn.execute(
            "insert into annotations (id, workspace_id, call_id, user_id, user_display_name, label) "
            "values (%s, %s, %s, %s, 'owner', %s)",
            (new_id("ann"), workspace_id, call, owner[0], label),
        )
        out.labelled_calls.append(call)
    mixes = [(3, 2), (2, 2), (1, 3), (4, 1)] + [(0, n) for n in (1, 2, 3)] + [(1, 0)] * 5
    for i, (passes, fails) in enumerate(mixes):
        call = _call(conn, workspace_id, booking, 1 + i)
        for n in range(passes + fails):
            _run(conn, workspace_id, call, booking[0], CHECKS[n], "pass" if n < passes else "fail")
        out.queue_calls.append(call)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True, help="owner DSN (postgresql://...)")
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    with psycopg.connect(args.dsn, autocommit=True) as conn:
        out = seed(conn, args.workspace)
    print(
        json.dumps(
            {
                "agents": out.agents,
                "labelled_calls": len(out.labelled_calls),
                "queue_calls": len(out.queue_calls),
            }
        )
    )


if __name__ == "__main__":
    main()
