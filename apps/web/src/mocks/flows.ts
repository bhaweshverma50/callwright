/**
 * Mock flows (spec 004) for mock-mode development and component tests: every flow agent gets a
 * small demo flow kept in memory; saves bump the revision, validation reports nothing, publish
 * and the assistant answer with fixed shapes. Creating a flow agent needs the real API.
 */
import { http, HttpResponse } from "msw";
import type { Flow, FlowGraph } from "../api/flows";
import { env } from "../lib/env";
import { defaultConfig } from "../routes/flows/model";

const url = (path: string) => `${env.apiBaseUrl}${path}`;
const flows = new Map<string, Flow>();
const VALID = { errors: 0, warnings: 0, issues: [] };

function demo(agentId: string): Flow {
  const graph: FlowGraph = {
    nodes: [
      { id: "n_start000", type: "start", label: "Start", position: { x: 32, y: 120 }, config: defaultConfig("start") },
      {
        id: "n_agent000",
        type: "agent",
        label: "Reminder",
        position: { x: 376, y: 120 },
        config: { ...defaultConfig("agent"), instructions: "Remind the caller of their appointment and offer to rebook." },
      },
      { id: "n_end00000", type: "end", label: "End", position: { x: 720, y: 120 }, config: defaultConfig("end") },
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
  http.post(url("/flows"), () =>
    HttpResponse.json(
      {
        type: "about:blank",
        title: "Not available in mock mode",
        status: 422,
        code: "validation_failed",
        detail: "Create flow agents against the API.",
      },
      { status: 422, headers: { "content-type": "application/problem+json" } },
    ),
  ),
  http.get(url("/agents/:id/flow"), ({ params }) => {
    const id = String(params.id);
    if (!flows.has(id)) flows.set(id, demo(id));
    const flow = flows.get(id)!;
    return HttpResponse.json(flow, { headers: { ETag: `"${flow.revision}"` } });
  }),
  http.put(url("/flows/:id"), async ({ params, request }) => {
    const flow = byFlowId(String(params.id));
    if (!flow) return HttpResponse.json({ title: "Not found", status: 404, code: "not_found" }, { status: 404 });
    const body = (await request.json()) as { name: string; graph: FlowGraph };
    const next = { ...flow, name: body.name, graph: body.graph, revision: flow.revision + 1, updated_at: new Date().toISOString() };
    flows.set(flow.agent_id, next);
    return HttpResponse.json(next, { headers: { ETag: `"${next.revision}"` } });
  }),
  http.post(url("/flows/:id/validate"), () => HttpResponse.json(VALID)),
  http.post(url("/flows/:id/compile"), () => HttpResponse.json({ ok: true, issues: [], compiled: null })),
  http.post(url("/flows/:id/publish"), () =>
    HttpResponse.json(
      { agent_version_id: "agv_01ARZ3NDEKTSV4RRFFQ69G5FAV", version_number: 2, graph_hash: "0".repeat(64), warnings: 0 },
      { status: 201 },
    ),
  ),
  http.post(url("/flows/:id/assistant"), ({ params }) => {
    const flow = byFlowId(String(params.id));
    return HttpResponse.json({
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
