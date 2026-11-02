"""Text simulation test support (008): a fake internal API on ``httpx.MockTransport``, scripted
models per role and agent configs. Everything is in process; no keys, no network."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from tests.flow_support import compiled_config
from tests.harness.fakes import contract_errors
from tests.harness.runner import deep_merge, load_agent_config
from worker.adapters.registry import AdapterRegistry, VendorSpec
from worker.textsim.api_client import TextsimApiClient
from worker.textsim.llm import Role, Script, ScriptReply, ScriptRequest, make_script_llm
from worker.textsim.runner import RunnerDeps

BASE = "http://api.test/v1/internal"
TOKEN = "svc-test"


async def no_sleep(_: float) -> None:
    return None


@dataclass
class FakeInternalApi:
    """The API's internal endpoints for the text runner, with contract checks on events."""

    case_specs: dict[tuple[str, str], Any] = field(default_factory=dict)
    sim_specs: dict[str, Any] = field(default_factory=dict)
    case_results: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    sim_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    kb_requests: list[dict[str, Any]] = field(default_factory=list)
    kb_results: list[dict[str, Any]] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    close_events_after: int | None = None  # 409 on events once this many posts were accepted
    requests: list[httpx.Request] = field(default_factory=list)
    posts: int = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401)
        path = request.url.path.removeprefix("/v1/internal")
        if m := re.fullmatch(r"/test-runs/([^/]+)/cases/([^/]+)/spec", path):
            spec = self.case_specs.get((m[1], m[2]))
            return _spec_response(spec)
        if m := re.fullmatch(r"/test-runs/([^/]+)/cases/([^/]+)/result", path):
            self.case_results[(m[1], m[2])] = json.loads(request.content)
            return httpx.Response(204)
        if m := re.fullmatch(r"/simulation-runs/([^/]+)/spec", path):
            return _spec_response(self.sim_specs.get(m[1]))
        if m := re.fullmatch(r"/simulation-runs/([^/]+)/result", path):
            self.sim_results[m[1]] = json.loads(request.content)
            return httpx.Response(204)
        if m := re.fullmatch(r"/calls/([^/]+)/events", path):
            if self.close_events_after is not None and self.posts >= self.close_events_after:
                return httpx.Response(409, json={"detail": "call is terminal"})
            self.posts += 1
            batch = json.loads(request.content)["events"]
            for event in batch:
                self.violations += [f"{m[1]}: {e}" for e in contract_errors(event)]
            self.events.setdefault(m[1], []).extend(batch)
            return httpx.Response(200, json={"accepted": len(batch), "duplicates": 0})
        if path == "/knowledge/search":
            self.kb_requests.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "results": self.kb_results,
                    "embedding_ms": 1,
                    "query_ms": 1,
                    "embedding_cache_hit": False,
                },
            )
        return httpx.Response(404, json={"detail": f"no route {path}"})

    def http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    def client(self) -> TextsimApiClient:
        return TextsimApiClient(BASE, TOKEN, http=self.http(), max_attempts=2, sleep=no_sleep)

    # views -------------------------------------------------------------------------------

    def call_events(self, call_id: str, type_: str | None = None) -> list[dict[str, Any]]:
        return [e for e in self.events.get(call_id, []) if type_ is None or e["type"] == type_]

    def items(self, call_id: str, item_type: str | None = None) -> list[dict[str, Any]]:
        out = [e["item"] for e in self.call_events(call_id, "transcript_item")]
        return [i for i in out if item_type is None or i.get("type") == item_type]

    def messages(self, call_id: str) -> list[tuple[str, str]]:
        return [(i["role"], i["text"]) for i in self.items(call_id, "message")]


def _spec_response(spec: Any) -> httpx.Response:
    if spec is None:
        return httpx.Response(404, json={"detail": "not found"})
    if isinstance(spec, int):
        return httpx.Response(spec, json={"detail": "gone"})
    return httpx.Response(200, json=spec)


# --------------------------------------------------------------------------------------------
# Scripted models


def tool_names(request: ScriptRequest) -> set[str]:
    return set(request.tools)


@dataclass
class Rule:
    """When the caller's last line contains ``match``: say ``reply`` or call ``tool``."""

    match: str
    reply: str | None = None
    tool: str | None = None
    args: Mapping[str, Any] = field(default_factory=dict)


def agent_script(
    rules: Sequence[Rule] = (),
    *,
    greeting: str = "Hello, how can I help?",
    default: str = "Sure, I can help with that.",
    after_tool: Callable[[ScriptRequest], str] | None = None,
    classify: Mapping[str, str] | None = None,
) -> Script:
    """Rule-driven agent. ``classify`` answers a flow's forced ``choose_category`` call: the
    first caller-text fragment found picks its category."""

    def script(request: ScriptRequest) -> ScriptReply:
        if request.forced and request.tools:
            name = next(iter(request.tools))
            args: dict[str, Any] = {}
            if name == "choose_category":
                heard = " ".join(t for r, t in request.messages() if r != "system").lower()
                found = [c for frag, c in (classify or {}).items() if frag.lower() in heard]
                args = {"category": found[0]} if found else {}
            return ScriptReply(tool_calls=((name, args),))
        if request.after_tool_output:
            return ScriptReply(after_tool(request) if after_tool else "Done.")
        said = request.last("user")
        if said is None:
            return ScriptReply(greeting)
        for rule in rules:
            if rule.match.lower() in said.lower():
                if rule.tool and rule.tool in request.tools:
                    return ScriptReply(tool_calls=((rule.tool, dict(rule.args)),))
                if rule.reply:
                    return ScriptReply(rule.reply)
        return ScriptReply(default)

    return script


def last_tool_output(request: ScriptRequest) -> str:
    for item in reversed(request.items):
        if getattr(item, "type", "") == "function_call_output":
            return str(item.output)
    return ""


@dataclass
class Models:
    """A ``ModelFactory`` giving each role its own script; keeps every model it built."""

    agent: Script = field(default_factory=agent_script)
    caller: Script | None = None
    synth: Script | None = None
    built: list[tuple[Role, VendorSpec, Any]] = field(default_factory=list)

    def __call__(
        self, spec: VendorSpec, role: Role, context: Mapping[str, Any] | None = None
    ) -> Any:
        script = {"agent": self.agent, "caller": self.caller, "synth": self.synth}[role]
        if script is None:
            raise AssertionError(f"no script for role {role}")
        model = make_script_llm(script, provider=spec.provider, model=spec.model or "")
        self.built.append((role, spec, model))
        return model

    def of(self, role: Role) -> list[Any]:
        return [m for r, _, m in self.built if r == role]


def deps(api: FakeInternalApi, models: Any) -> RunnerDeps:
    return RunnerDeps(
        models=models,
        registry=AdapterRegistry(),
        internal_api_url=BASE,
        service_token=TOKEN,
        kb_http=api.http(),
        settle_timeout_s=5.0,
        turn_timeout_s=10.0,
    )


# --------------------------------------------------------------------------------------------
# Configs and specs


def http_tool(name: str, *, mock: str | None = None, mappings: Any = None) -> dict[str, Any]:
    return {
        "tool_id": f"tool_{name}",
        "type": "http",
        "name": name,
        "description": f"Look up {name}",
        "mock_response": mock,
        "config": {
            "method": "GET",
            "url": f"https://api.example.com/{name}",
            "headers": [],
            "timeout_ms": 2000,
            "response_mappings": mappings or [],
            "speak_during_execution": False,
            "parameters": {
                "type": "object",
                "properties": {"ref": {"type": "string"}},
                "required": [],
            },
        },
    }


def agent_config(**overrides: Any) -> dict[str, Any]:
    return deep_merge(load_agent_config(), overrides)


def flow(name: str) -> dict[str, Any]:
    return compiled_config(name)


def case_spec(config: Mapping[str, Any], prompt: str, **extra: Any) -> dict[str, Any]:
    return {
        "workspace_id": "ws_1",
        "agent_id": "agt_1",
        "agent_type": config.get("type", "single_prompt"),
        "config_snapshot": dict(config),
        "user_prompt": prompt,
        "dynamic_variables": {},
        **extra,
    }


def sim_spec(
    config: Mapping[str, Any],
    *,
    mode: str = "replay",
    srun: str = "srun_1",
    call_id: str = "call_sim_1",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "workspace_id": "ws_1",
        "simulation_run_id": srun,
        "output_call_id": call_id,
        "agent_id": "agt_1",
        "agent_type": config.get("type", "single_prompt"),
        "channel": "web",
        "mode": mode,
        "config_snapshot": dict(config),
        "settings": {"max_caller_turns": 20, "missing_mock_policy": "synthesize"},
        "dynamic_variables": {},
        **extra,
    }
