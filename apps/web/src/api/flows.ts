/**
 * Types and calls for spec 004 (flow agents, contracts/flows.yaml). The generated node config is
 * a loose union, so each node type gets a precise local config type here.
 */
import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import { ApiError, toProblem } from "./errors";
import type { components } from "./schema";
import type { HttpRequestConfig, TransferConfig } from "./tools";

type S = components["schemas"];

export type NodeType = S["NodeType"];
export type Trigger = S["Trigger"];
export type ValidationIssue = S["ValidationIssue"];
export type FlowValidationResult = S["FlowValidationResult"];
export type FlowTransition = S["FlowTransition"];
export type AssistantResponse = S["AssistantResponse"];
export type FlowOperation = S["Operation"];
export type CompileResult = S["CompileResult"];

export type ContextStrategy = "inherit" | "summarize" | "reset";
export interface Overrides {
  llm: { provider: string; model: string; temperature?: number | null } | null;
  tts: { provider: string; model?: string | null; voice_id: string; speed?: number | null; volume?: number | null } | null;
  stt: { provider: string; model?: string | null } | null;
  language: string | null;
}
export interface TaskField {
  name: string;
  type: "string" | "number" | "boolean" | "enum";
  description: string;
  required: boolean;
  enum_values?: string[];
}
export interface ExtractField {
  name: string;
  type: "string" | "number" | "boolean";
  description: string;
}
export interface Category {
  name: string;
  description: string;
}

export interface StartConfig {
  start_speaker: "agent" | "user";
  greeting_type: "static" | "generated";
  greeting: string;
}
export interface ConversationalConfig {
  instructions: string;
  begin_message: string | null;
  context_strategy: ContextStrategy;
  overrides: Overrides;
  tool_ids: string[];
  kb_search_enabled: boolean;
}
export interface TaskConfig extends ConversationalConfig {
  fields: TaskField[];
  max_rounds: number;
}
export interface ConditionConfig {
  kind: "classify" | "rule";
  instructions: string;
  categories: Category[];
}
export interface SayConfig {
  message: string;
  allow_interruptions: boolean;
}
export interface ExtractConfig {
  instructions: string;
  fields: ExtractField[];
}
export interface WebhookConfig {
  request: HttpRequestConfig;
  mock_response: string | null;
}
export interface TransferNodeConfig {
  transfer: TransferConfig;
}
export interface EndConfig {
  message: string;
  reason: string;
}

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

export interface FlowNode<T extends NodeType = NodeType> {
  id: string;
  type: T;
  label: string;
  position: { x: number; y: number };
  config: ConfigByNode[T];
}

export type RuleOperator = "equals" | "not_equals" | "contains" | "matches" | "exists" | "gt" | "lt";
export interface FlowRule {
  variable: string;
  operator: RuleOperator;
  value?: string | null;
}
export interface FlowEdge {
  id: string;
  source: string;
  target: string;
  trigger: Trigger;
  label?: string | null;
  condition?: string | null;
  function_name?: string | null;
  category?: string | null;
  rule?: FlowRule | null;
  sort_order: number;
}
export interface FlowGraph {
  nodes: FlowNode[];
  edges: FlowEdge[];
  viewport: { x: number; y: number; zoom: number };
}
export interface Flow {
  id: string;
  agent_id: string;
  name: string;
  graph: FlowGraph;
  revision: number;
  last_validation: FlowValidationResult;
  last_published_version_id?: string | null;
  agent_draft_revision?: number;
  created_at: string;
  updated_at: string;
}

export const flowKeys = {
  byAgent: (agentId: string) => ["flows", "agent", agentId] as const,
  validate: (flowId: string) => ["flows", "validate", flowId] as const,
};

export function useFlowByAgent(agentId: string | undefined) {
  return useQuery({
    queryKey: flowKeys.byAgent(agentId ?? ""),
    queryFn: async () => (await unwrap(api.GET("/agents/{agent_id}/flow", { params: { path: { agent_id: agentId! } } }))) as unknown as Flow,
    enabled: Boolean(agentId),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

export async function fetchFlowByAgent(agentId: string): Promise<Flow> {
  return (await unwrap(api.GET("/agents/{agent_id}/flow", { params: { path: { agent_id: agentId } } }))) as unknown as Flow;
}

export async function createFlowAgent(name: string, language: string) {
  const body = await unwrap(api.POST("/flows", { body: { name, language } }));
  return body as unknown as { agent_id: string; flow: Flow; warnings?: string[] };
}

/** A failed call with the full problem body kept (issues, current revision). */
export class FlowProblem extends ApiError {
  readonly body: Record<string, unknown>;
  constructor(status: number, body: unknown) {
    super(status, toProblem(status, body));
    this.body = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
  }
}

async function keep<T>(call: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await call;
  if (response.ok) return data as T;
  throw new FlowProblem(response.status, error);
}

export interface AgentSettingsChange {
  expected_draft_revision: number;
  changes: Record<string, unknown>;
}

export async function saveFlow(flow: { id: string; revision: number }, name: string, graph: FlowGraph, agentSettings?: AgentSettingsChange) {
  const body = await keep(
    api.PUT("/flows/{flow_id}", {
      params: { path: { flow_id: flow.id }, header: { "If-Match": `"${flow.revision}"` } },
      body: { name, graph: graph as never, ...(agentSettings ? { agent_settings: agentSettings as never } : {}) },
    }),
  );
  return body as unknown as Flow;
}

export async function validateFlow(flowId: string, graph: FlowGraph, signal?: AbortSignal) {
  return unwrap(api.POST("/flows/{flow_id}/validate", { params: { path: { flow_id: flowId } }, body: { graph: graph as never }, signal }));
}

export async function compileFlow(flowId: string) {
  return (await unwrap(api.POST("/flows/{flow_id}/compile", { params: { path: { flow_id: flowId } } }))) as CompileResult;
}

export async function publishFlow(flowId: string, expectedRevision: number, releaseNotes: string) {
  return keep(
    api.POST("/flows/{flow_id}/publish", {
      params: { path: { flow_id: flowId } },
      body: { expected_revision: expectedRevision, ...(releaseNotes.trim() ? { release_notes: releaseNotes.trim() } : {}) },
    }),
  );
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export async function askAssistant(flowId: string, messages: ChatTurn[], baseRevision: number, graph: FlowGraph | null, signal?: AbortSignal) {
  return keep(
    api.POST("/flows/{flow_id}/assistant", {
      params: { path: { flow_id: flowId } },
      body: { messages, base_revision: baseRevision, ...(graph ? { graph: graph as never } : {}) },
      signal,
    }),
  ) as Promise<AssistantResponse>;
}
