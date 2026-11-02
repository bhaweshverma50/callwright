"""Quickstart fixtures for 009 (T058): completed live calls of one published agent with
intent fulfillment verdicts, written as the database owner.

The ``price_fabrication`` scenario gives ``--failing`` calls where the agent quotes a cleaning
price that is not in its price list (one recurring failure), ``--other`` calls failing for an
unrelated reason, and passing calls for the rest, all on the agent's published version and with
transcripts the simulator can replay. Intent fulfillment is switched on for the agent. Run it
again after an apply with ``--failing 0 --other 0`` to add post-apply calls on the new version.

    uv run python -m app.dev.seed_issues --dsn postgresql://callwright:callwright@localhost:55432/db \
        --workspace ws_... --agent agt_... --calls 30 --failing 8 --other 2
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import UTC, datetime, timedelta

import psycopg

from app.core.ids import new_id
from app.evaluators.registry import builtin_id

CHECK = "intent_fulfillment"
PRICE_LINES = [
    ("agent", "Thanks for calling Bright Smiles. How can I help?"),
    ("user", "How much is a cleaning, and can I book one for Tuesday?"),
    ("agent", "A cleaning is 80 dollars. I have Tuesday at 10. Shall I book it?"),
    ("user", "Is that the price for new patients too?"),
    ("agent", "Yes, 80 dollars for everyone. Booked for Tuesday at 10."),
    ("user", "Thanks, bye."),
]
OK_LINES = [
    ("agent", "Thanks for calling Bright Smiles. How can I help?"),
    ("user", "I'd like to book a cleaning on Tuesday."),
    ("agent", "Tuesday at 10 works. Booked for you. Anything else?"),
    ("user", "No, thanks."),
]
PRICE_REASON = (
    "The caller asked for the price of a cleaning and the agent quoted 80 dollars, a price that is "
    "not in its price list."
)
OTHER_REASON = "The caller asked about parking and the agent described a garage that does not exist."


def _items(lines: list[tuple[str, str]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    turn = 0
    for role, text in lines:
        item: dict[str, object] = {"type": "message", "role": role, "text": text}
        if role == "agent":
            item["turn_index"] = turn
            turn += 1
        out.append(item)
    return out


def seed(
    conn: psycopg.Connection, workspace_id: str, agent_id: str, *, calls: int, failing: int, other: int
) -> dict[str, object]:
    row = conn.execute(
        "select pinned_version_id from agents where id = %s and workspace_id = %s", (agent_id, workspace_id)
    ).fetchone()
    if row is None or row[0] is None:
        raise SystemExit("The agent does not exist in this workspace or is not published.")
    version_id = row[0]
    evaluator = builtin_id(CHECK)
    conn.execute(
        "insert into agent_eval_settings (agent_id, evaluator_id, workspace_id, enabled, overrides, "
        "is_headline) values (%s, %s, %s, true, '{}'::jsonb, false) on conflict (agent_id, evaluator_id) "
        "do update set enabled = true",
        (agent_id, evaluator, workspace_id),
    )
    now = datetime.now(UTC)
    created = {"failing": 0, "other": 0, "passing": 0}
    for i in range(calls):
        if i < failing:
            kind, lines, verdict, reason = "failing", PRICE_LINES, "fail", PRICE_REASON
        elif i < failing + other:
            kind, lines, verdict, reason = "other", OK_LINES, "fail", OTHER_REASON
        else:
            kind, lines, verdict, reason = "passing", OK_LINES, "pass", "The caller booked the cleaning."
        ended = now - timedelta(seconds=5 * i + 1)
        call_id = new_id("call")
        conn.execute(
            "insert into calls (id, workspace_id, agent_id, agent_version_id, origin, channel, direction, "
            "status, created_at, connected_at, ended_at, completed_at, billable_seconds, sentiment, "
            "pipeline_status, transcript, dynamic_variables, disconnect_reason) values (%s, %s, %s, %s, "
            "'live', 'web', 'inbound', 'completed', %s, %s, %s, %s, 60, 'neutral', 'done', %s::jsonb, "
            "'{}'::jsonb, 'user_hangup')",
            (
                call_id,
                workspace_id,
                agent_id,
                version_id,
                ended - timedelta(seconds=63),
                ended - timedelta(seconds=60),
                ended,
                ended,
                json.dumps({"items": _items(lines)}),
            ),
        )
        group = f"erg_seed{uuid.uuid4().hex[:16]}"
        conn.execute(
            "insert into evaluator_run_groups (run_group_id, workspace_id, call_id, trigger, "
            "idempotency_key, status) values (%s, %s, %s, 'pipeline', %s, 'done')",
            (group, workspace_id, call_id, group),
        )
        conn.execute(
            "insert into evaluator_runs (id, workspace_id, call_id, agent_id, evaluator_id, "
            "evaluator_version, run_group_id, trigger, settings_hash, status, verdict, score, rationale, "
            "completed_at) values "
            "(%s, %s, %s, %s, %s, 1, %s, 'pipeline', 'seed', 'completed', %s, %s, %s, %s)",
            (
                new_id("evr"),
                workspace_id,
                call_id,
                agent_id,
                evaluator,
                group,
                verdict,
                1.0 if verdict == "pass" else 0.0,
                reason,
                ended,
            ),
        )
        created[kind] += 1
    return {"agent_id": agent_id, "agent_version_id": version_id, **created}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True, help="owner DSN (postgresql://...)")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--agent", required=True, help="a published single-prompt agent")
    parser.add_argument("--calls", type=int, default=30)
    parser.add_argument("--failing", type=int, default=8)
    parser.add_argument("--other", type=int, default=2)
    args = parser.parse_args()
    with psycopg.connect(args.dsn, autocommit=True) as conn:
        out = seed(conn, args.workspace, args.agent, calls=args.calls, failing=args.failing, other=args.other)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
