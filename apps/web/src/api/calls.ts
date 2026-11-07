/** Calls read side and dashboard (spec 006): types from the contracts and TanStack Query hooks. */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import type { components } from "./schema";
import type { QueryOf } from "./types";
import { scalarLimits } from "../lib/contract.gen";
import { saveBlob } from "../lib/download";

type S = components["schemas"];

export type Channel = S["Channel"];
export type CallOrigin = S["Origin"];
export type CallStatus = S["CallStatus"];
export type DisconnectReason = S["DisconnectReason"];
export type Sentiment = S["Sentiment"];
export type EvalStatus = S["EvalStatus"];
export type CallListItem = S["CallListItem"];
export type CallPage = S["CallPage"];
export type CallDetail = S["CallDetail"];
export type CostView = S["CostView"];
export type TranscriptItem = S["CallTranscriptItem"];
export type TranscriptMessage = S["TranscriptMessage"];
export type TurnLatency = S["TurnLatency"];
export type LatencySummary = S["LatencySummary"];
export type FlowTransition = S["FlowTransition"];
export type RecordingLink = S["RecordingLink"];
export type CallComparison = S["CallComparison"];
export type DashboardStats = S["DashboardStats"];
export type DashboardQuality = S["DashboardQuality"];
export type AgentHealth = S["AgentHealth"];
export type DashboardPeriod = NonNullable<QueryOf<"/dashboard/stats", "get">["period"]>;

export const callKeys = {
  all: ["calls"] as const,
  lists: ["calls", "list"] as const,
  list: (query: string) => ["calls", "list", query] as const,
  live: ["calls", "live"] as const,
  detail: (id: string) => ["calls", "detail", id] as const,
  transcript: (id: string) => ["calls", "transcript", id] as const,
  latencies: (id: string) => ["calls", "latencies", id] as const,
  flow: (id: string) => ["calls", "flow", id] as const,
  recording: (id: string) => ["calls", "recording", id] as const,
  compare: (id: string, other: string) => ["calls", "compare", id, other] as const,
  any: ["calls", "any"] as const,
  dashboard: ["dashboard"] as const,
  stats: (query: string) => ["dashboard", "stats", query] as const,
  quality: (query: string) => ["dashboard", "quality", query] as const,
  health: (query: string) => ["dashboard", "health", query] as const,
};

/** Every list query is built with URLSearchParams so "+1555" arrives as %2B (FR-037). */
const sendAsIs = (search: URLSearchParams) => () => search.toString();

export const POLL_PENDING_MS = 4_000;
/** A ringing or live call: ringing, answer and hang-up show within a few seconds. */
export const POLL_LIVE_MS = 3_000;
/** New calls (an incoming phone call) show up without a reload while the page is open. */
export const POLL_IDLE_MS = 15_000;
/** Dashboard figures move with every finished call and evaluation; a slow refresh keeps them honest. */
export const DASHBOARD_POLL_MS = 60_000;
/** Statuses that will still change on their own: ringing, live, or being processed after the call. */
const ACTIVE_STATUSES = new Set<CallStatus>(scalarLimits.CallStatus["x-still-changing"]);
/** Ringing or connected: what GET /calls/live lists. */
export const LIVE_STATUSES = new Set<CallStatus>(scalarLimits.CallStatus["x-on-air"]);
export const isOnAir = (status: CallStatus) => LIVE_STATUSES.has(status);

/** Call list: fast while any row is still changing, slow otherwise (only while the tab is visible). */
export function callsListInterval(items: Pick<CallListItem, "status">[] | undefined): number {
  return items?.some((c) => ACTIVE_STATUSES.has(c.status)) ? POLL_PENDING_MS : POLL_IDLE_MS;
}

/** Call detail: fastest while ringing or live, then while analysis or the recording finish; idle never. */
export function callDetailInterval(c: Pick<CallDetail, "status" | "processing_state" | "recording_pending"> | undefined): number | false {
  if (!c) return false;
  if (LIVE_STATUSES.has(c.status)) return POLL_LIVE_MS;
  return c.processing_state === "pending" || c.recording_pending ? POLL_PENDING_MS : false;
}

/** Transcript, turn latencies and flow path grow during a live call; afterwards they are fixed. */
export function liveDetailInterval(live: boolean): number | false {
  return live ? POLL_LIVE_MS : false;
}

export function useCalls(search: URLSearchParams) {
  const key = search.toString();
  return useQuery({
    queryKey: callKeys.list(key),
    queryFn: () => unwrap(api.GET("/calls", { querySerializer: sendAsIs(search) })),
    placeholderData: keepPreviousData,
    // Polls only while the tab is visible (React Query pauses intervals in the background).
    refetchInterval: (q) => callsListInterval(q.state.data?.items),
  });
}

/** Whether the workspace has a call of these origins. The dashboard counts live calls only
 * (FR-022), so it shows the setup sequence until the first live call; test calls tick a step. */
export function useHasCalls(origin = "live") {
  return useQuery({
    queryKey: [...callKeys.any, origin],
    queryFn: async () => {
      const page = await unwrap(api.GET("/calls", { params: { query: { page_size: 1, origin } } }));
      return page.total > 0;
    },
    staleTime: 60_000,
    // The setup sequence turns into the dashboard once the first call lands (the shell's live sync
    // also refreshes this the moment a call starts).
    refetchInterval: (q) => (q.state.data === false ? POLL_IDLE_MS * 2 : false),
  });
}

export function useCall(id: string | null) {
  return useQuery({
    queryKey: callKeys.detail(id ?? ""),
    queryFn: () => unwrap(api.GET("/calls/{call_id}", { params: { path: { call_id: id! } } })),
    enabled: Boolean(id),
    // Ringing, answering and hanging up show at once; post-call analysis lands without a reload.
    refetchInterval: (q) => callDetailInterval(q.state.data),
  });
}

/** `live`: the call is ringing or in progress, so new lines arrive every few seconds. */
export function useTranscript(id: string | null, live = false) {
  return useQuery({
    queryKey: callKeys.transcript(id ?? ""),
    queryFn: () => unwrap(api.GET("/calls/{call_id}/transcript", { params: { path: { call_id: id! } } })),
    enabled: Boolean(id),
    refetchInterval: liveDetailInterval(live),
  });
}

export function useTurnLatencies(id: string | null, live = false) {
  return useQuery({
    queryKey: callKeys.latencies(id ?? ""),
    queryFn: () => unwrap(api.GET("/calls/{call_id}/turn-latencies", { params: { path: { call_id: id! } } })),
    enabled: Boolean(id),
    refetchInterval: liveDetailInterval(live),
  });
}

/** Flow path from 004 (empty for single-prompt calls). */
export function useFlowTransitions(id: string | null, live = false) {
  return useQuery({
    queryKey: callKeys.flow(id ?? ""),
    queryFn: async () => (await unwrap(api.GET("/calls/{call_id}/flow-transitions", { params: { path: { call_id: id! } } }))).items,
    enabled: Boolean(id),
    staleTime: live ? 0 : 5 * 60_000,
    // A flow agent moves between nodes during the call; the path is fixed once it ends.
    refetchInterval: liveDetailInterval(live),
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
      ),
    enabled: Boolean(other.withCall || other.sim),
    retry: false,
  });
}

/** CSV of the current list (FR-035); resolves to the file name it saved. */
export async function downloadCallsCsv(search: URLSearchParams, columns: string[]): Promise<string> {
  const query = new URLSearchParams(search);
  query.delete("page");
  query.delete("page_size");
  query.set("columns", columns.join(","));
  const call = api.GET("/calls/export", { querySerializer: sendAsIs(query), parseAs: "blob" });
  const blob = await unwrap(call);
  const { response } = await call;
  const name = /filename="?([^";]+)"?/.exec(response.headers.get("content-disposition") ?? "")?.[1] ?? "calls.csv";
  saveBlob(name, blob);
  return name;
}

export function useDashboardStats(search: URLSearchParams) {
  const key = search.toString();
  return useQuery({
    queryKey: callKeys.stats(key),
    queryFn: () => unwrap(api.GET("/dashboard/stats", { querySerializer: sendAsIs(search) })),
    placeholderData: keepPreviousData,
    refetchInterval: DASHBOARD_POLL_MS,
  });
}

export function useDashboardQuality(search: URLSearchParams) {
  const key = search.toString();
  return useQuery({
    queryKey: callKeys.quality(key),
    queryFn: () => unwrap(api.GET("/dashboard/quality", { querySerializer: sendAsIs(search) })),
    placeholderData: keepPreviousData,
    refetchInterval: DASHBOARD_POLL_MS,
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
    queryFn: () => unwrap(api.GET("/dashboard/agent-health", { querySerializer: sendAsIs(query) })),
    placeholderData: keepPreviousData,
    refetchInterval: DASHBOARD_POLL_MS,
  });
}
