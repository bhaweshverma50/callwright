/**
 * Types and TanStack Query hooks for the tool library (spec 005, contracts/tools.yaml). The
 * generated config union is loose, so each tool type gets a precise local config type here.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import type { components } from "./schema";
import { schemaLimits } from "../lib/contract.gen";

type S = components["schemas"];

export type ToolType = S["ToolType"];
export type HeaderSpec = S["HeaderSpec"];
export type ResponseMapping = S["ResponseMapping"];
export type TestRunResult = S["TestRunResult"];

export interface EndCallConfig {
  message?: string | null;
}
export interface WarmTransfer {
  handoff_type: "private" | "public";
  briefing_message_type: "static" | "prompt";
  briefing_message: string;
}
export interface TransferConfig {
  routing_type: "static" | "dynamic";
  number?: string;
  routing_instructions?: string;
  allowed_numbers: string[];
  transfer_type: "cold" | "warm";
  warm_transfer?: WarmTransfer | null;
  hold_message: string;
  ring_timeout_s: number;
}
export interface PressDigitConfig {
  delay_ms: number;
  cooldown_ms: number;
}
export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
export interface HttpRequestConfig {
  method: HttpMethod;
  url: string;
  headers: HeaderSpec[];
  body_template: unknown;
  timeout_ms: number;
  response_mappings: ResponseMapping[];
  speak_during_execution: boolean;
  execution_message: string;
}
export interface HttpToolConfig extends HttpRequestConfig {
  parameters: Record<string, unknown>;
}

export type ToolConfig = EndCallConfig | TransferConfig | PressDigitConfig | HttpToolConfig;
export interface ConfigByType {
  end_call: EndCallConfig;
  transfer_call: TransferConfig;
  press_digit: PressDigitConfig;
  http: HttpToolConfig;
}

export interface Tool {
  id: string;
  type: ToolType;
  name: string;
  description: string;
  config: ToolConfig;
  mock_response: string | null;
  usage_count: number;
  created_at: string;
  updated_at: string;
}
export interface ToolDraft {
  type: ToolType;
  name: string;
  description: string;
  config: ToolConfig;
  mock_response?: string | null;
}
export interface ToolPreset {
  preset_id: string;
  type: ToolType;
  title: string;
  summary: string;
  tool: ToolDraft;
}
export interface ToolPage {
  items: Tool[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}
export interface ToolUsage {
  agent_id: string;
  agent_name: string;
  in_draft: boolean;
  published_version_ids: string[];
}

export const MAX_TOOLS_PER_AGENT = schemaLimits.AgentConfig.tool_ids.maxItems;

export const toolKeys = {
  all: ["tools"] as const,
  list: (search: string, type: ToolType | null, page: number) => ["tools", "list", search, type, page] as const,
  detail: (id: string) => ["tools", "detail", id] as const,
  byIds: (ids: string[]) => ["tools", "by-ids", ...ids] as const,
  presets: ["tools", "presets"] as const,
  usages: (id: string) => ["tools", "usages", id] as const,
};

export function useTools(search: string, type: ToolType | null = null, page = 1, pageSize = 50) {
  return useQuery({
    queryKey: toolKeys.list(search, type, page),
    queryFn: () =>
      unwrap(
        api.GET("/tools", {
          params: { query: { search: search || undefined, type: type ?? undefined, page, page_size: pageSize } },
        }),
      ) as Promise<ToolPage>,
    placeholderData: keepPreviousData,
  });
}

/** Every tool in the workspace that the draft references, in draft order (missing ones dropped). */
export function useToolsByIds(ids: string[]) {
  return useQuery({
    queryKey: toolKeys.byIds(ids),
    queryFn: async () => {
      const found = new Map<string, Tool>();
      // The library is small (agents use at most 25 tools); page through it once.
      for (let page = 1; page < 50; page++) {
        const res = (await unwrap(api.GET("/tools", { params: { query: { page, page_size: 100 } } }))) as ToolPage;
        for (const t of res.items) found.set(t.id, t);
        if (page >= res.total_pages) break;
      }
      return ids.map((id) => found.get(id)).filter((t): t is Tool => Boolean(t));
    },
    placeholderData: keepPreviousData,
  });
}

export function useToolPresets() {
  return useQuery({
    queryKey: toolKeys.presets,
    queryFn: async () => ((await unwrap(api.GET("/tools/presets"))) as { items: ToolPreset[] }).items,
    staleTime: Infinity,
  });
}

export function useToolUsages(id: string | null) {
  return useQuery({
    queryKey: toolKeys.usages(id ?? ""),
    queryFn: async () => ((await unwrap(api.GET("/tools/{tool_id}/usages", { params: { path: { tool_id: id! } } }))) as { items: ToolUsage[] }).items,
    enabled: Boolean(id),
  });
}

export async function createTool(body: ToolDraft): Promise<Tool> {
  return (await unwrap(api.POST("/tools", { body: body as never }))) as Tool;
}

export async function updateTool(id: string, body: Partial<ToolDraft>): Promise<Tool> {
  const { type: _type, ...rest } = body;
  return (await unwrap(api.PATCH("/tools/{tool_id}", { params: { path: { tool_id: id } }, body: rest as never }))) as Tool;
}

export async function duplicateTool(id: string): Promise<Tool> {
  return (await unwrap(api.POST("/tools/{tool_id}/duplicate", { params: { path: { tool_id: id } } }))) as Tool;
}

export async function deleteTool(id: string, force: boolean) {
  return unwrap(api.DELETE("/tools/{tool_id}", { params: { path: { tool_id: id }, query: { force } } }));
}

export async function testRunTool(body: {
  tool_id?: string;
  tool?: ToolDraft;
  arguments: Record<string, unknown>;
  dynamic_variables: Record<string, string>;
}): Promise<TestRunResult> {
  return unwrap(api.POST("/tools/test-run", { body: body as never }));
}

export const TOOL_TYPE_LABELS: Record<ToolType, string> = {
  end_call: "End call",
  transfer_call: "Transfer call",
  press_digit: "Press digits",
  http: "HTTP request",
};

export function isHttp(tool: { type: ToolType }): tool is { type: "http" } & typeof tool {
  return tool.type === "http";
}
