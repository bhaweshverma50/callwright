/**
 * Types and TanStack Query hooks for the tool library (spec 005, contracts/tools.yaml), typed from
 * schema.d.ts. A tool's config is the one its type names (`ConfigByType`).
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, fetchAll, unwrap } from "./client";
import type { components } from "./schema";
import type { BodyOf, ResponseOf } from "./types";
import { schemaLimits } from "../lib/contract.gen";

type S = components["schemas"];

export type ToolType = S["ToolType"];
export type HeaderSpec = S["HeaderSpec"];
export type ResponseMapping = S["ResponseMapping"];
export type TestRunResult = S["TestRunResult"];

export type EndCallConfig = S["EndCallConfig"];
export type TransferConfig = S["TransferSpec"];
export type WarmTransfer = NonNullable<TransferConfig["warm_transfer"]>;
export type PressDigitConfig = S["PressDigitConfig"];
export type HttpRequestConfig = S["HttpRequestSpec"];
export type HttpMethod = HttpRequestConfig["method"];
export type HttpToolConfig = S["HttpToolConfig"];
export type ToolConfig = S["Tool"]["config"];
export interface ConfigByType {
  end_call: EndCallConfig;
  transfer_call: TransferConfig;
  press_digit: PressDigitConfig;
  http: HttpToolConfig;
}

export type Tool = S["Tool"];
export type ToolDraft = S["ToolCreate"];
export type ToolPreset = S["ToolPreset"];
export type ToolPage = ResponseOf<"/tools", "get">;
export type ToolUsage = ResponseOf<"/tools/{tool_id}/usages", "get">["items"][number];
export type TestRunRequest = BodyOf<"/tools/test-run", "post">;

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
      ),
    placeholderData: keepPreviousData,
  });
}

/** Every tool in the workspace that the draft references, in draft order (missing ones dropped). */
export function useToolsByIds(ids: string[]) {
  return useQuery({
    queryKey: toolKeys.byIds(ids),
    queryFn: async () => {
      const found = new Map((await fetchAll((query) => unwrap(api.GET("/tools", { params: { query } })))).map((t) => [t.id, t]));
      return ids.map((id) => found.get(id)).filter((t): t is Tool => Boolean(t));
    },
    placeholderData: keepPreviousData,
  });
}

export function useToolPresets() {
  return useQuery({
    queryKey: toolKeys.presets,
    queryFn: async () => (await unwrap(api.GET("/tools/presets"))).items,
    staleTime: Infinity,
  });
}

export function useToolUsages(id: string | null) {
  return useQuery({
    queryKey: toolKeys.usages(id ?? ""),
    queryFn: async () => (await unwrap(api.GET("/tools/{tool_id}/usages", { params: { path: { tool_id: id! } } }))).items,
    enabled: Boolean(id),
  });
}

export function createTool(body: ToolDraft): Promise<Tool> {
  return unwrap(api.POST("/tools", { body }));
}

export function updateTool(id: string, body: Partial<ToolDraft>): Promise<Tool> {
  const { type: _type, ...rest } = body;
  return unwrap(api.PATCH("/tools/{tool_id}", { params: { path: { tool_id: id } }, body: rest }));
}

export function duplicateTool(id: string): Promise<Tool> {
  return unwrap(api.POST("/tools/{tool_id}/duplicate", { params: { path: { tool_id: id } } }));
}

export async function deleteTool(id: string, force: boolean) {
  return unwrap(api.DELETE("/tools/{tool_id}", { params: { path: { tool_id: id }, query: { force } } }));
}

export function testRunTool(body: TestRunRequest): Promise<TestRunResult> {
  return unwrap(api.POST("/tools/test-run", { body }));
}
