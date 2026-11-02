"""Golden built-in catalog (007 T075; FR-006, FR-033 to FR-036, data-model "Built-in catalog")."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.contract.conftest import check

# name: (display_name, scope, cost_class, output_kind, agent types, default on, settings)
GOLDEN = {
    "anomaly_detection": (
        "Anomaly detection",
        "call",
        "free",
        "anomaly",
        "all",
        False,
        {
            "threshold": ("number", 0, 1, 0.7),
            "window_days": ("int", 1, 365, 30),
            "min_sample_size": ("int", 5, 500, 30),
            "knn_k": ("int", 1, 50, 10),
            "backfill_per_run": ("int", 0, 20, 5),
        },
    ),
    "factual_consistency": (
        "Factual consistency",
        "call",
        "llm_judge",
        "class",
        "all",
        False,
        {"judge_model": ("select",)},
    ),
    "flow_completion": ("Flow completion", "call", "free", "class", "flow", True, {}),
    "intent_fulfillment": (
        "Intent fulfillment",
        "call",
        "llm_judge",
        "class",
        "all",
        True,
        {"judge_model": ("select",), "sample_rate_pct": ("int", 1, 100, 100)},
    ),
    "kb_relevance": (
        "Knowledge retrieval relevance",
        "call",
        "llm_judge",
        "class",
        "all",
        False,
        {"judge_model": ("select",)},
    ),
    "audio_silence": (
        "Long silences",
        "call",
        "free",
        "audio_quality",
        "all",
        True,
        {
            "max_acceptable_silence_ms": ("int", 500, 60000, 3000),
            "silence_threshold_db": ("number", -80, -10, -40),
            "min_silence_ms": ("int", 200, 10000, 1000),
        },
    ),
    "node_dead_end": ("Node dead ends", "call", "free", "class", "flow", True, {}),
    "process_reward": (
        "Per-turn progress",
        "turn",
        "llm_judge",
        "process_reward",
        "all",
        False,
        {"judge_model": ("select",)},
    ),
    "stuck_loop_detector": (
        "Stuck loops",
        "call",
        "free",
        "class",
        "flow",
        True,
        {"max_visits_per_node": ("int", 2, 10, 3)},
    ),
    "tool_call_correctness": (
        "Tool call correctness",
        "call",
        "llm_judge",
        "class",
        "all",
        False,
        {"judge_model": ("select",)},
    ),
    "transition_correctness": (
        "Transition correctness",
        "call",
        "llm_judge",
        "class",
        "flow",
        False,
        {"judge_model": ("select",)},
    ),
    "latency_slo": (
        "Turn latency",
        "turn",
        "free",
        "class",
        "all",
        True,
        {"threshold_ms": ("int", 100, 30000, 3000)},
    ),
}


async def test_flow_catalog_matches_golden(client: httpx.AsyncClient, account: Account, app: object) -> None:
    body = check(
        await client.get(
            "/v1/evaluators", params={"agent_type": "flow", "kind": "builtin"}, headers=account.headers
        )
    ).json()
    items = {e["name"]: e for e in body["items"]}
    assert set(items) == set(GOLDEN)
    assert [e["display_name"] for e in body["items"]] == sorted(e["display_name"] for e in body["items"])
    default_model = app.state.settings.default_judge_model  # type: ignore[attr-defined]
    for name, (display, scope, cost, kind, types, on, fields) in GOLDEN.items():
        e = items[name]
        assert (
            e["display_name"],
            e["scope"],
            e["cost_class"],
            e["output_kind"],
            e["enabled_by_default"],
        ) == (display, scope, cost, kind, on), name
        assert set(e["agent_types"]) == ({"flow"} if types == "flow" else {"single_prompt", "flow"})
        served = {f["key"]: f for f in e["settings_schema"]["fields"]}
        assert set(served) == set(fields), name
        for key, spec in fields.items():
            f = served[key]
            if spec[0] == "select":
                assert f["type"] == "select" and f["options_source"] == "judge_models"
                assert f["default"] == default_model and default_model in f["options"]
            else:
                assert (f["type"], f["min"], f["max"], f["default"]) == spec, (name, key)
        assert e["kind"] == "builtin" and e["current_version"] >= 1 and e["config"] is None


async def test_single_prompt_catalog_has_the_eight_non_flow_checks(
    client: httpx.AsyncClient, account: Account
) -> None:
    body = check(
        await client.get("/v1/evaluators", params={"agent_type": "single_prompt"}, headers=account.headers)
    ).json()
    names = {e["name"] for e in body["items"] if e["kind"] == "builtin"}
    assert names == {n for n, g in GOLDEN.items() if g[4] == "all"} and len(names) == 8


async def test_judge_models(client: httpx.AsyncClient, account: Account) -> None:
    items = check(await client.get("/v1/evaluators/judge-models", headers=account.headers)).json()["items"]
    assert sum(1 for m in items if m["is_default"]) == 1 and items[0]["is_default"]
