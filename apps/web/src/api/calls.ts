/** Calls read side and dashboard (spec 006): types from the contracts and TanStack Query hooks. */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import { isApiError } from "./errors";
import type { components } from "./schema";

type S = components["schemas"];

export type Channel = S["Channel"];
export type CallOrigin = S["Origin"];
export type CallStatus = S["CallStatus"];
export type DisconnectReason = S["DisconnectReason"];
export type Sentiment = S["Sentiment"];
export type EvalStatus = S["EvalStatus"];
export type CallListItem = S["CallListItem"];
export type CallPage = S["CallPage"];
export type CallDetail = S["CallListItem"] & {
  agent_version_id: string;
  agent_version_label?: string | null;
  ended_at?: string | null;
  latency: S["LatencySummary"];
  cost?: S["CostView"] | null;
  processing_state: "pending" | "done";
  /** The recording is still uploading after the call ended. */
  recording_pending?: boolean;
};
export type CostView = S["CostView"];
export type TranscriptItem = S["TranscriptMessage"] | S["TranscriptToolCall"] | S["TranscriptToolResult"];
export type TranscriptMessage = S["TranscriptMessage"];
export type TurnLatency = S["TurnLatency"];
export type LatencySummary = S["LatencySummary"];
export type FlowTransition = S["FlowTransition"];
export type RecordingLink = S["RecordingLink"];
export type CallComparison = Omit<S["CallComparison"], "left" | "right"> & { left: CallDetail; right: CallDetail };
export type DashboardStats = S["DashboardStats"];
export type DashboardQuality = S["DashboardQuality"];
export type AgentHealth = S["AgentHealth"];
export type DashboardPeriod = "all_time" | "last_7_days" | "last_30_days" | "last_90_days" | "custom";

export const callKeys = {
  all: ["calls"] as const,
  list: (query: string) => ["calls", "list", query] as const,
  detail: (id: string) => ["calls", "detail", id] as const,
  transcript: (id: string) => ["calls", "transcript", id] as const,
  latencies: (id: string) => ["calls", "latencies", id] as const,
  flow: (id: string) => ["calls", "flow", id] as const,
  recording: (id: string) => ["calls", "recording", id] as const,
  compare: (id: string, other: string) => ["calls", "compare", id, other] as const,
  any: ["calls", "any"] as const,
  agents: ["calls", "agent-options"] as const,
  dashboard: ["dashboard"] as const,
  stats: (query: string) => ["dashboard", "stats", query] as const,
  quality: (query: string) => ["dashboard", "quality", query] as const,
  health: (query: string) => ["dashboard", "health", query] as const,
};

/** Every list query is built with URLSearchParams so "+1555" arrives as %2B (FR-037). */
function queryObject(search: URLSearchParams): Record<string, string> {
  return Object.fromEntries(search.entries());
}

export function useCalls(search: URLSearchParams) {
  const key = search.toString();
  return useQuery({
    queryKey: callKeys.list(key),
    queryFn: () => unwrap(api.GET("/calls", { params: { query: queryObject(search) as never } })) as Promise<CallPage>,
    placeholderData: keepPreviousData,
  });
}

/** Whether the workspace has a call of these origins. The dashboard counts live calls only
 * (FR-022), so it shows the setup sequence until the first live call; test calls tick a step. */
export function useHasCalls(origin = "live") {
  return useQuery({
    queryKey: [...callKeys.any, origin],
    queryFn: async () => {
      const page = (await unwrap(api.GET("/calls", { params: { query: { page_size: 1, origin } } }))) as CallPage;
      return page.total > 0;
    },
    staleTime: 60_000,
  });
}

const POLL_PENDING_MS = 4_000;

export function useCall(id: string | null) {
  return useQuery({
    queryKey: callKeys.detail(id ?? ""),
    queryFn: () => unwrap(api.GET("/calls/{call_id}", { params: { path: { call_id: id! } } })) as Promise<CallDetail>,
    enabled: Boolean(id),
    // Post-call analysis lands without a reload (US2 scenario 7).
    refetchInterval: (q) =>
      q.state.data?.processing_state === "pending" || q.state.data?.recording_pending || q.state.data?.status === "in_progress"
        ? POLL_PENDING_MS
        : false,
  });
}

export function useTranscript(id: string | null, live = false) {
  return useQuery({
    queryKey: callKeys.transcript(id ?? ""),
    queryFn: () => unwrap(api.GET("/calls/{call_id}/transcript", { params: { path: { call_id: id! } } })),
    enabled: Boolean(id),
    refetchInterval: live ? POLL_PENDING_MS : false,
  });
}

export function useTurnLatencies(id: string | null) {
  return useQuery({
    queryKey: callKeys.latencies(id ?? ""),
    queryFn: () => unwrap(api.GET("/calls/{call_id}/turn-latencies", { params: { path: { call_id: id! } } })),
    enabled: Boolean(id),
  });
}

/** Flow path from 004. Until 004 serves it (or for single-prompt calls) the section is hidden. */
export function useFlowTransitions(id: string | null) {
  return useQuery({
    queryKey: callKeys.flow(id ?? ""),
    queryFn: async () => {
      try {
        const body = await unwrap(api.GET("/calls/{call_id}/flow-transitions", { params: { path: { call_id: id! } } }));
        return (body as { items?: FlowTransition[] }).items ?? [];
      } catch (e) {
        if (isApiError(e) && (e.status === 404 || e.status === 405)) return [];
        throw e;
      }
    },
    enabled: Boolean(id),
    retry: false,
    staleTime: 5 * 60_000,
  });
}

export async function fetchRecordingLink(id: string, disposition: "inline" | "attachment" = "inline"): Promise<RecordingLink> {
  return unwrap(api.GET("/calls/{call_id}/recording", { params: { path: { call_id: id }, query: { disposition } } }));
}

export function useCompare(id: string, other: { withCall?: string | null; sim?: string | null }) {
  const key = other.withCall ? `call:${other.withCall}` : `sim:${other.sim ?? ""}`;
  return useQuery({
    queryKey: callKeys.compare(id, key),
    queryFn: () =>
      unwrap(
        api.GET("/calls/{call_id}/compare", {
          params: {
            path: { call_id: id },
            query: other.withCall ? { with_call_id: other.withCall } : { with_simulation_run_id: other.sim ?? undefined },
          },
        }),
      ) as Promise<CallComparison>,
    enabled: Boolean(other.withCall || other.sim),
    retry: false,
  });
}

/** Agents for the filter menus (one page of up to 100, names included). */
export function useAgentOptions() {
  return useQuery({
    queryKey: callKeys.agents,
    queryFn: async () => {
      const page = await unwrap(api.GET("/agents", { params: { query: { page: 1, page_size: 100 } } }));
      return (page as { items: { id: string; name: string }[] }).items.map((a) => ({ id: a.id, name: a.name }));
    },
    staleTime: 60_000,
  });
}

/** CSV of the current list (FR-035); resolves to the file name it saved. */
export async function downloadCallsCsv(search: URLSearchParams, columns: string[]): Promise<string> {
  const query = new URLSearchParams(search);
  query.delete("page");
  query.delete("page_size");
  query.set("columns", columns.join(","));
  const { data, error, response } = await api.GET("/calls/export", { params: { query: queryObject(query) as never }, parseAs: "blob" });
  if (!response.ok) {
    await unwrap(Promise.resolve({ data, error, response }));
  }
  const name = /filename="?([^";]+)"?/.exec(response.headers.get("content-disposition") ?? "")?.[1] ?? "calls.csv";
  const url = URL.createObjectURL(data as Blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
  return name;
}

export function useDashboardStats(search: URLSearchParams) {
  const key = search.toString();
  return useQuery({
    queryKey: callKeys.stats(key),
    queryFn: () => unwrap(api.GET("/dashboard/stats", { params: { query: queryObject(search) as never } })) as Promise<DashboardStats>,
    placeholderData: keepPreviousData,
  });
}

export function useDashboardQuality(search: URLSearchParams) {
  const key = search.toString();
  return useQuery({
    queryKey: callKeys.quality(key),
    queryFn: () => unwrap(api.GET("/dashboard/quality", { params: { query: queryObject(search) as never } })) as Promise<DashboardQuality>,
    placeholderData: keepPreviousData,
  });
}

export function useAgentHealth(search: URLSearchParams) {
  const query = new URLSearchParams();
  for (const k of ["agent_ids", "tz"]) {
    const v = search.get(k);
    if (v) query.set(k, v);
  }
  const key = query.toString();
  return useQuery({
    queryKey: callKeys.health(key),
    queryFn: () => unwrap(api.GET("/dashboard/agent-health", { params: { query: queryObject(query) as never } })) as Promise<AgentHealth>,
    placeholderData: keepPreviousData,
  });
}
