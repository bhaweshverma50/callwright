/**
 * Mock flows (spec 004) for mock-mode development and component tests: every flow agent gets a
 * small demo flow kept in memory; saves bump the revision, validation reports nothing, publish
 * and the assistant answer with fixed shapes. Creating a flow agent needs the real API.
 */
import { http } from "msw";
import type { ConfigByNode, Flow, FlowGraph, NodeDefaults, NodeType } from "../api/flows";
import { json, problem, problemDetail, url } from "./http";

const LABELS: Record<NodeType, string> = {
  start: "Start",
  agent: "Agent",
  task: "Collect details",
  condition: "Route",
  say: "Say",
  extract_variable: "Extract",
  webhook: "API call",
  transfer: "Transfer",
  end: "End",
};

const OVERRIDES = () => ({ llm: null, tts: null, stt: null, language: null });

const CONFIGS: { [K in NodeType]: () => ConfigByNode[K] } = {
  start: () => ({ start_speaker: "agent", greeting_type: "static", greeting: "Hi, thanks for calling. How can I help?" }),
  agent: () => ({
    instructions: "",
    begin_message: null,
    context_strategy: "inherit",
    overrides: OVERRIDES(),
    tool_ids: [],
    kb_search_enabled: true,
  }),
  task: () => ({
    instructions: "",
    begin_message: null,
    fields: [
      { name: "name", type: "string", description: "The caller's full name", required: true },
      { name: "email", type: "string", description: "The caller's email address", required: true },
    ],
    max_rounds: 5,
    context_strategy: "inherit",
    overrides: OVERRIDES(),
    tool_ids: [],
    kb_search_enabled: true,
  }),
  condition: () => ({
    kind: "classify",
    instructions: "",
    categories: [
      { name: "Sales", description: "The caller wants to buy something or asks about prices" },
      { name: "Support", description: "The caller needs help with something they already have" },
    ],
  }),
  say: () => ({ message: "", allow_interruptions: true }),
  extract_variable: () => ({ instructions: "", fields: [] }),
  webhook: () => ({
    request: {
      method: "POST",
      url: "",
      headers: [{ name: "Content-Type", value: "application/json", secret: false }],
      body_template: null,
      timeout_ms: 8000,
      response_mappings: [],
      speak_during_execution: true,
      execution_message: "One moment while I check that.",
    },
    mock_response: null,
  }),
  transfer: () => ({
    transfer: {
      routing_type: "static",
      number: "",
      allowed_numbers: [],
      transfer_type: "cold",
      warm_transfer: null,
      hold_message: "Please hold while I connect you.",
      ring_timeout_s: 30,
    },
  }),
  // Empty: the agent says a short goodbye in its own words that fits the call.
  end: () => ({ message: "", reason: "call_completed" }),
};

/** What a new node of each type starts with, as the real API serves it (GET /flows/node-defaults). */
export const mockNodeDefaults = Object.fromEntries(
  (Object.keys(LABELS) as NodeType[]).map((type) => [type, { label: LABELS[type], config: CONFIGS[type]() }]),
) as NodeDefaults;

const flows = new Map<string, Flow>();

export function resetMockFlows() {
  flows.clear();
}
const VALID = { errors: 0, warnings: 0, issues: [] };

function demo(agentId: string): Flow {
  const graph: FlowGraph = {
    nodes: [
      {
        id: "n_start000",
        type: "start",
        label: "Start",
        position: { x: 32, y: 120 },
        config: { start_speaker: "agent", greeting_type: "static", greeting: "Hi, thanks for calling. How can I help?" },
      },
      {
        id: "n_agent000",
        type: "agent",
        label: "Reminder",
        position: { x: 376, y: 120 },
        config: {
          instructions: "Remind the caller of their appointment and offer to rebook.",
          begin_message: null,
          context_strategy: "inherit",
          overrides: { llm: null, tts: null, stt: null, language: null },
          tool_ids: [],
          kb_search_enabled: true,
        },
      },
      { id: "n_end00000", type: "end", label: "End", position: { x: 720, y: 120 }, config: { message: "", reason: "call_completed" } },
    ],
    edges: [
      { id: "e_start000", source: "n_start000", target: "n_agent000", trigger: "always", sort_order: 0 },
      {
        id: "e_done0000",
        source: "n_agent000",
        target: "n_end00000",
        trigger: "llm_condition",
        label: "Caller is done",
        condition: "The caller has nothing else",
        sort_order: 0,
      },
    ],
    viewport: { x: 0, y: 0, zoom: 1 },
  };
  const now = new Date().toISOString();
  return {
    id: `flw_${agentId.slice(4)}`,
    agent_id: agentId,
    name: "Recall reminders",
    graph,
    revision: 1,
    last_validation: VALID,
    agent_draft_revision: 1,
    created_at: now,
    updated_at: now,
  };
}

const byFlowId = (id: string) => [...flows.values()].find((f) => f.id === id);

export const flowHandlers = [
  http.get(url("/flows/node-defaults"), () =>
    json({ node_types: Object.entries(mockNodeDefaults).map(([type, d]) => ({ type, label: d.label, config: d.config })) }),
  ),
  http.post(url("/flows"), () => problem(422, "validation_failed", "Not available in mock mode", "Create flow agents against the API.")),
  http.get(url("/agents/:id/flow"), ({ params }) => {
    const id = String(params.id);
    if (!flows.has(id)) flows.set(id, demo(id));
    const flow = flows.get(id)!;
    return json(flow, 200, { ETag: `"${flow.revision}"` });
  }),
  http.put(url("/flows/:id"), async ({ params, request }) => {
    const flow = byFlowId(String(params.id));
    if (!flow) return problemDetail(404, "not_found", "No flow with that ID.");
    const body = (await request.json()) as { name: string; graph: FlowGraph };
    const next = { ...flow, name: body.name, graph: body.graph, revision: flow.revision + 1, updated_at: new Date().toISOString() };
    flows.set(flow.agent_id, next);
    return json(next, 200, { ETag: `"${next.revision}"` });
  }),
  http.post(url("/flows/:id/validate"), () => json(VALID)),
  http.post(url("/flows/:id/compile"), () => json({ ok: true, issues: [], compiled: null })),
  http.post(url("/flows/:id/publish"), () =>
    json({ agent_version_id: "agv_01ARZ3NDEKTSV4RRFFQ69G5FAV", version_number: 2, graph_hash: "0".repeat(64), warnings: 0 }, 201),
  ),
  http.post(url("/flows/:id/assistant"), ({ params }) => {
    const flow = byFlowId(String(params.id));
    return json({
      message: "Tell me which step to add or change.",
      flow_name: null,
      operations: [],
      proposed_graph: flow?.graph,
      issues: [],
      base_revision: flow?.revision ?? 1,
      usage: { input_tokens: 0, output_tokens: 0, cost_usd: "0.000000" },
    });
  }),
];
