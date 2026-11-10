/**
 * Types and calls for spec 004 (flow agents, contracts/flows.yaml), typed from schema.d.ts. The
 * contract lists a node's config as anyOf every node config (a draft may hold an incomplete one);
 * the builder works on nodes whose config is the one their type names (`FlowNode<T>`).
 */
import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import { isApiError, problemAs } from "./errors";
import type { components } from "./schema";
import type { BodyOf } from "./types";

type S = components["schemas"];

export type NodeType = S["NodeType"];
export type Trigger = S["Trigger"];
export type ValidationIssue = S["ValidationIssue"];
export type FlowValidationResult = S["FlowValidationResult"];
export type AssistantResponse = S["AssistantResponse"];
export type CompileResult = S["CompileResult"];

export type Overrides = S["Overrides"];
export type StartConfig = S["StartConfig"];
export type ConversationalConfig = S["AgentConfigNode"];
export type ContextStrategy = ConversationalConfig["context_strategy"];
export type TaskConfig = S["TaskConfig"];
export type TaskField = S["TaskField"];
export type ConditionConfig = S["ConditionConfig"];
export type Category = NonNullable<ConditionConfig["categories"]>[number];
export type SayConfig = S["SayConfig"];
export type ExtractConfig = S["ExtractConfig"];
export type ExtractField = ExtractConfig["fields"][number];
export type WebhookConfig = S["WebhookConfig"];
export type TransferNodeConfig = S["TransferConfig"];
export type EndConfig = S["EndConfig"];

export interface ConfigByNode {
  start: StartConfig;
  agent: ConversationalConfig;
  task: TaskConfig;
  condition: ConditionConfig;
  say: SayConfig;
  extract_variable: ExtractConfig;
  webhook: WebhookConfig;
  transfer: TransferNodeConfig;
  end: EndConfig;
}

/** A node whose config is the one its type names. */
export type FlowNode<T extends NodeType = NodeType> = { [K in T]: Omit<S["Node"], "type" | "config"> & { type: K; config: ConfigByNode[K] } }[T];

export type FlowEdge = S["Edge"];
export type FlowRule = NonNullable<FlowEdge["rule"]>;
export type RuleOperator = FlowRule["operator"];
export type FlowGraph = Omit<S["FlowGraph"], "nodes"> & { nodes: FlowNode[] };
export type Flow = Omit<S["Flow"], "graph"> & { graph: FlowGraph };
export type AgentSettingsChange = S["AgentSettingsChange"];
export type ChatTurn = BodyOf<"/flows/{flow_id}/assistant", "post">["messages"][number];

/** The one place a contract node becomes a typed node: its type names its config. */
const typedNode = (n: S["Node"]) => n as FlowNode;
const typedGraph = (g: S["FlowGraph"]): FlowGraph => ({ ...g, nodes: g.nodes.map(typedNode) });
const typedFlow = (f: S["Flow"]): Flow => ({ ...f, graph: typedGraph(f.graph) });

export const flowKeys = {
  nodeDefaults: ["flows", "node-defaults"] as const,
  byAgent: (agentId: string) => ["flows", "agent", agentId] as const,
  validate: (flowId: string) => ["flows", "validate", flowId] as const,
};

/** What a new node of each type starts with: its label and full config, as the API serves them. */
export type NodeDefaults = { [K in NodeType]: { label: string; config: ConfigByNode[K] } };

export function useNodeDefaults() {
  return useQuery({
    queryKey: flowKeys.nodeDefaults,
    queryFn: async () => {
      const { node_types } = await unwrap(api.GET("/flows/node-defaults"));
      return Object.fromEntries(node_types.map((n) => [n.type, { label: n.label, config: n.config }])) as NodeDefaults;
    },
    staleTime: Infinity,
  });
}

export function useFlowByAgent(agentId: string | undefined) {
  return useQuery({
    queryKey: flowKeys.byAgent(agentId ?? ""),
    queryFn: () => fetchFlowByAgent(agentId!),
    enabled: Boolean(agentId),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

export async function fetchFlowByAgent(agentId: string): Promise<Flow> {
  return typedFlow(await unwrap(api.GET("/agents/{agent_id}/flow", { params: { path: { agent_id: agentId } } })));
}

export async function createFlowAgent(name: string, language: string) {
  const body = await unwrap(api.POST("/flows", { body: { name, language } }));
  return { ...body, flow: typedFlow(body.flow) };
}

/** The validation issues a failed publish carried (FlowErrorsProblem), or none. */
export function publishIssues(err: unknown): ValidationIssue[] {
  return (isApiError(err) && problemAs(err, "FlowErrorsProblem")?.issues) || [];
}

export async function saveFlow(flow: { id: string; revision: number }, name: string, graph: FlowGraph, agentSettings?: AgentSettingsChange) {
  const body = await unwrap(
    api.PUT("/flows/{flow_id}", {
      params: { path: { flow_id: flow.id }, header: { "If-Match": `"${flow.revision}"` } },
      body: { name, graph, ...(agentSettings ? { agent_settings: agentSettings } : {}) },
    }),
  );
  return typedFlow(body);
}

export async function validateFlow(flowId: string, graph: FlowGraph, signal?: AbortSignal) {
  return unwrap(api.POST("/flows/{flow_id}/validate", { params: { path: { flow_id: flowId } }, body: { graph }, signal }));
}

export async function compileFlow(flowId: string) {
  return unwrap(api.POST("/flows/{flow_id}/compile", { params: { path: { flow_id: flowId } } }));
}

export async function publishFlow(flowId: string, expectedRevision: number, releaseNotes: string) {
  return unwrap(
    api.POST("/flows/{flow_id}/publish", {
      params: { path: { flow_id: flowId } },
      body: { expected_revision: expectedRevision, ...(releaseNotes.trim() ? { release_notes: releaseNotes.trim() } : {}) },
    }),
  );
}

export async function askAssistant(flowId: string, messages: ChatTurn[], baseRevision: number, graph: FlowGraph | null, signal?: AbortSignal) {
  const out = await unwrap(
    api.POST("/flows/{flow_id}/assistant", {
      params: { path: { flow_id: flowId } },
      body: { messages, base_revision: baseRevision, ...(graph ? { graph } : {}) },
      signal,
    }),
  );
  return { ...out, proposed_graph: typedGraph(out.proposed_graph) };
}
