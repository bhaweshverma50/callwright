# ruff: noqa: E501, S311
"""Deterministic call history for 006 (T008): tests, the quickstart and local visual checks.

Writes as the database owner (no RLS), into one existing workspace: three agents (one flow
agent) with a version each, 45 calls over the last 40 days across channels, statuses and
sentiments (42 live, 3 test), 2 simulation calls, turn latency events, tool calls (one failing),
an interruption, flow transitions, 001-shaped cost lines and the 271 s reference call from 001.

    uv run python -m app.dev.seed_calls --dsn postgresql://callwright:callwright@localhost:55432/db --workspace ws_...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import psycopg

from app.billing.service import breakdown_json
from app.calls.pipeline import latency_stats
from app.core.ids import new_id
from app.pricing import engine
from app.pricing.engine import Bundle, Catalog, Components, Rate, Selection, Usage

CATALOG = Catalog(
    version=1,
    effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    rates=(
        Rate("stt", "deepgram", None, "Deepgram", Decimal("0.0085")),
        Rate(
            "llm",
            "azure_openai",
            "gpt-5-mini",
            "GPT-5 Mini",
            Decimal("0.0015"),
            (Bundle("llm_input_tokens", 20000), Bundle("llm_output_tokens", 200)),
        ),
        Rate(
            "tts",
            "elevenlabs",
            "eleven_flash_v2_5",
            "Flash v2.5",
            Decimal("0.0450"),
            (Bundle("tts_chars", 750),),
        ),
        Rate("nc", "sanas", "vi", "Voice isolation", Decimal("0.0000")),
        Rate("platform", "callwright", None, "Platform", Decimal("0.0500")),
    ),
)
COMPONENTS = Components(
    stt=Selection("deepgram", None),
    llm=Selection("azure_openai", "gpt-5-mini"),
    tts=Selection("elevenlabs", "eleven_flash_v2_5"),
    nc=Selection("sanas", "vi"),
)
AGENT_CONFIG: dict[str, Any] = {
    "schema_version": 1,
    "type": "single_prompt",
    "language": "en-US",
    "llm": {"provider": "azure_openai", "model": "gpt-5-mini", "temperature": 1.0},
    "prompt": "You are a helpful agent.",
    "begin_message": "Hi, thanks for calling.",
    "start_speaker": "agent",
    "dynamic_variables": [],
    "stt": {"provider": "deepgram", "model": None},
    "tts": {"provider": "elevenlabs", "model": "eleven_flash_v2_5", "voice_id": "voice_1"},
    "noise_cancellation": {"provider": "sanas", "model": "vi"},
    "call_behavior": {"end_on_silence_s": 30, "max_duration_s": 600, "ring_duration_ms": 5000},
    "advanced": {"webhook_url": None, "webhook_timeout_ms": 3000, "recording": "inherit"},
    "tool_ids": [],
    "kb_ids": [],
}
AGENTS = (("Order desk", "single_prompt"), ("Clinic scheduler", "flow"), ("Billing helper", "single_prompt"))
SUMMARIES = (
    "Caller asked where their order was; the agent confirmed it shipped and gave the delivery date.",
    "Caller booked a follow-up appointment for next Tuesday at 10:00.",
    "Caller disputed a charge; the agent explained the invoice and offered a callback.",
    "Caller wanted to change the delivery address; the agent updated it after verifying the order.",
    "Caller hung up before stating the reason for the call.",
)
FLOW = ("greeting", "verify_identity", "find_slot", "confirm_booking", "wrap_up")


@dataclass
class SeedResult:
    workspace_id: str
    agent_ids: list[str] = field(default_factory=list)
    call_ids: list[str] = field(default_factory=list)
    simulation_call_ids: list[str] = field(default_factory=list)
    reference_call_id: str = ""


def _agent(conn: psycopg.Connection[Any], workspace_id: str, name: str, agent_type: str) -> tuple[str, str]:
    agent_id, version_id = new_id("agt"), new_id("agv")
    config = json.dumps({**AGENT_CONFIG, "type": agent_type}, sort_keys=True)
    summary = json.dumps(
        {"llm_model": "gpt-5-mini", "tts_provider": "elevenlabs", "tts_voice_id": "voice_1", "tool_count": 1}
    )
    with conn.transaction():
        conn.execute("SET CONSTRAINTS ALL DEFERRED")
        conn.execute(
            """insert into agent_versions (id, workspace_id, agent_id, version_number, schema_version, config,
                                           content_hash, source, summary)
               values (%s, %s, %s, 1, 1, %s::jsonb, %s, 'save', %s::jsonb)""",
            (
                version_id,
                workspace_id,
                agent_id,
                config,
                hashlib.sha256(config.encode()).hexdigest(),
                summary,
            ),
        )
        conn.execute(
            """insert into agents (id, workspace_id, name, type, language, draft_config, draft_version_id)
               values (%s, %s, %s, %s, 'en-US', %s::jsonb, %s)""",
            (agent_id, workspace_id, name, agent_type, config, version_id),
        )
    return agent_id, version_id


def _transcript(rng: random.Random, flow: bool, turns: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = [
        {
            "type": "message",
            "role": "agent",
            "text": "Hi, thanks for calling. How can I help today?",
            "started_ms": 420,
            "turn_index": 0,
        }
    ]
    at = 2400
    lines = (
        ("I'd like to check on my order.", "Sure. Could you read me the order number?"),
        ("It's A one two four nine.", "Thanks. Let me look that up for you."),
        ("Okay.", "Your order shipped yesterday and should arrive on Thursday."),
        ("Can I change the address?", "I can help with that. What is the new address?"),
        ("Forty two Elm Street.", "Done. Is there anything else I can help with?"),
        ("No, that's all.", "Thanks for calling. Have a good day."),
    )
    for i in range(1, turns):
        user, agent = lines[(i - 1) % len(lines)]
        items.append(
            {
                "type": "message",
                "role": "user",
                "text": user,
                "started_ms": at,
                "confidence": round(rng.uniform(0.82, 0.99), 2),
            }
        )
        at += 1800
        if i == 2:
            items.append(
                {
                    "type": "tool_call",
                    "name": "lookup_order",
                    "arguments": {"order_id": "A1249"},
                    "ref": f"t{i}",
                    "at_ms": at,
                }
            )
            items.append(
                {
                    "type": "tool_result",
                    "name": "lookup_order",
                    "output": '{"status": "shipped", "eta": "Thursday"}',
                    "is_error": False,
                    "ref": f"t{i}",
                    "duration_ms": 412,
                }
            )
        if i == 4:
            items.append(
                {
                    "type": "tool_call",
                    "name": "update_address",
                    "arguments": {"order_id": "A1249", "line1": "42 Elm Street"},
                    "ref": f"t{i}",
                    "at_ms": at,
                }
            )
            items.append(
                {
                    "type": "tool_result",
                    "name": "update_address",
                    "output": "Upstream timeout after 3000 ms",
                    "is_error": True,
                    "ref": f"t{i}",
                    "duration_ms": 3004,
                }
            )
        if flow and i <= len(FLOW) - 1:
            items.append(
                {
                    "type": "flow_transition",
                    "from_node_id": FLOW[i - 1],
                    "to_node_id": FLOW[i],
                    "label": "next",
                }
            )
        items.append(
            {
                "type": "message",
                "role": "agent",
                "text": agent,
                "started_ms": at + 600,
                "turn_index": i,
                "interrupted": i == 3,
            }
        )
        at += 4200
    return items


def seed(
    conn: psycopg.Connection[Any],
    workspace_id: str,
    *,
    calls: int = 45,
    now: datetime | None = None,
    seed: int = 6,
) -> SeedResult:
    """Insert the data set into ``workspace_id`` (owner connection). Returns the ids written."""
    rng = random.Random(seed)
    now = (now or datetime.now(UTC)).replace(microsecond=0)
    result = SeedResult(workspace_id)
    agents = [(*_agent(conn, workspace_id, name, kind), kind) for name, kind in AGENTS]
    result.agent_ids = [a for a, _, _ in agents]
    plan: list[tuple[str, int]] = [("live", i) for i in range(calls - 3)] + [("test", i) for i in range(3)]
    plan += [("simulation", i) for i in range(2)]
    for n, (origin, _) in enumerate(plan):
        agent_id, version_id, kind = agents[n % 3]
        reference = n == 0
        channel = ("web", "sip_inbound", "sip_outbound", "whatsapp")[n % 4] if origin == "live" else "web"
        roll = rng.random()
        status = "completed"
        reason: str | None = rng.choice(
            ("user_hangup", "user_hangup", "agent_hangup", "call_transfer", "inactivity")
        )
        if not reference and origin == "live":
            if roll < 0.07:
                status, reason = "failed", "error"
            elif roll < 0.12:
                status, reason = "no_answer", None
            elif roll < 0.15:
                status, reason = "busy", None
        if n == 5:
            status, reason = "in_progress", None
        if n == 6:
            status, reason = "processing", "user_hangup"
        created = now - timedelta(days=rng.uniform(0, 40) if n > 6 else n * 0.05, minutes=rng.randint(0, 59))
        connected = status not in ("failed", "no_answer", "busy")
        seconds = 271 if reference else (rng.randint(35, 420) if connected and status != "in_progress" else 0)
        connected_at = created + timedelta(seconds=3) if connected else None
        ended_at = (
            connected_at + timedelta(seconds=seconds) if connected_at and status != "in_progress" else None
        )
        call_id = new_id("call")
        turns = max(2, min(7, seconds // 40)) if seconds else 0
        items = _transcript(rng, kind == "flow", turns) if turns else []
        turn_rows = []
        for t in range(turns):
            stt = rng.randint(140, 320) if t else None
            llm = rng.randint(380, 900)
            tts = None if t == 2 else rng.randint(160, 340)
            e2e = (stt or 0) + llm + (tts or 0) + rng.randint(40, 120) if t != 2 else rng.randint(900, 1500)
            turn_rows.append(
                SimpleNamespace(
                    turn_index=t,
                    stt_final_ms=stt,
                    llm_ttft_ms=llm,
                    tts_ttfb_ms=tts,
                    e2e_ms=e2e,
                    eou_delay_ms=None,
                )
            )
        stats = latency_stats(turn_rows) if turn_rows else None  # type: ignore[arg-type]
        cost: dict[str, Any] | None = None
        total: Decimal | None = None
        if ended_at is not None and origin != "simulation":
            usage = (
                Usage(duration_ms=271_000, llm_input_tokens=102_348, llm_output_tokens=745, tts_chars=2_555)
                if reference
                else Usage(
                    duration_ms=seconds * 1000,
                    llm_input_tokens=int(seconds * rng.uniform(150, 420)),
                    llm_output_tokens=int(seconds * rng.uniform(1.2, 3.5)),
                    tts_chars=int(seconds * rng.uniform(6, 14)),
                )
            )
            quote = engine.price(COMPONENTS, usage, CATALOG)
            assert quote.call is not None
            cost = breakdown_json(quote.call, call_id)
            total = quote.call.total_usd
        done = status == "completed"
        sentiment = rng.choice(("positive", "positive", "neutral", "negative", "unknown")) if done else None
        recorded = connected and status != "in_progress" and n % 5 != 3
        caller = f"+1555{rng.randint(1000000, 9999999)}"
        ours = "+14155550100"
        from_number, to_number = {
            "web": (None, None),
            "sip_inbound": (caller, ours),
            "sip_outbound": (ours, caller),
            "whatsapp": (caller, ours),
        }[channel]
        if reference:
            from_number = "+15551234567"
        conn.execute(
            """insert into calls (id, workspace_id, agent_id, agent_version_id, origin, simulation_run_id, channel,
                 direction, from_number, to_number, is_test, status, disconnect_reason, created_at, connected_at,
                 ended_at, completed_at, billable_seconds, latency_stats, transcript, recording_status,
                 recording_key, pipeline_status, cost_total_usd, cost_breakdown, summary, sentiment, analysis)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb)""",
            (
                call_id,
                workspace_id,
                agent_id,
                version_id,
                origin,
                f"srun_{call_id[5:]}" if origin == "simulation" else None,
                channel,
                "outbound" if channel == "sip_outbound" else "inbound",
                from_number,
                to_number,
                origin == "test",
                status,
                reason,
                created,
                connected_at,
                ended_at,
                ended_at if done else None,
                seconds if ended_at else None,
                json.dumps(stats) if stats else None,
                json.dumps({"items": items}) if status not in ("in_progress",) and items else None,
                "available" if recorded and done else ("recording" if status == "processing" else "none"),
                f"recordings/{workspace_id}/{call_id}.ogg" if recorded and done else None,
                "done" if done else "not_started",
                total,
                json.dumps(cost) if cost else None,
                rng.choice(SUMMARIES) if done else None,
                sentiment,
                json.dumps(
                    {
                        "order_found": rng.random() > 0.3,
                        "resolution": rng.choice(("resolved", "callback", "escalated")),
                    }
                )
                if done
                else None,
            ),
        )
        seq = 0
        for t, row in enumerate(turn_rows):
            seq += 1
            conn.execute(
                """insert into call_events (workspace_id, call_id, seq, type, occurred_at, turn_index, stt_final_ms,
                     llm_ttft_ms, tts_ttfb_ms, e2e_ms) values (%s,%s,%s,'turn',%s,%s,%s,%s,%s,%s)""",
                (
                    workspace_id,
                    call_id,
                    seq,
                    (connected_at or created) + timedelta(seconds=6 * t),
                    t,
                    row.stt_final_ms,
                    row.llm_ttft_ms,
                    row.tts_ttfb_ms,
                    row.e2e_ms,
                ),
            )
        for item in items:
            if item["type"] == "flow_transition":
                seq += 1
                conn.execute(
                    """insert into call_events (workspace_id, call_id, seq, type, occurred_at, payload)
                       values (%s,%s,%s,'flow_transition',%s,%s::jsonb)""",
                    (
                        workspace_id,
                        call_id,
                        seq,
                        connected_at or created,
                        json.dumps({k: item[k] for k in ("from_node_id", "to_node_id", "label")}),
                    ),
                )
        if cost is not None:
            conn.execute(
                """insert into call_costs (call_id, workspace_id, catalog_version, duration_ms, billed_seconds,
                     duration_minutes, lines, total_usd, raw_cost_usd) values (%s,%s,1,%s,%s,%s,%s::jsonb,%s,%s)""",
                (
                    call_id,
                    workspace_id,
                    cost["duration_ms"],
                    cost["billed_seconds"],
                    cost["duration_minutes"],
                    json.dumps(cost["lines"]),
                    cost["total_usd"],
                    cost["total_usd"],
                ),
            )
        if origin == "simulation":
            result.simulation_call_ids.append(call_id)
        else:
            result.call_ids.append(call_id)
        if reference:
            result.reference_call_id = call_id
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True, help="owner DSN (postgresql://...)")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--calls", type=int, default=45)
    args = parser.parse_args()
    with psycopg.connect(args.dsn, autocommit=True) as conn:
        out = seed(conn, args.workspace, calls=args.calls)
    print(
        json.dumps(
            {"agents": out.agent_ids, "calls": len(out.call_ids), "reference_call": out.reference_call_id}
        )
    )


if __name__ == "__main__":
    main()
