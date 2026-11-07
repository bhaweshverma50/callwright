/**
 * Calls on air now (`GET /v1/calls/live`): one shared query behind the dashboard's "Live now"
 * card, the sidebar's live badge and the pinned rows on Call History. Every reader shares the
 * query key, so the app makes one request per interval however many places show it.
 *
 * `useLiveCallSync` (mounted once in the shell) watches that list and refreshes what a call
 * changes when it starts, connects or ends: the call list, the open call, the dashboard, the
 * balance and usage. That keeps the rest of the app current without polling every page.
 */
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { session } from "./session";
import { callbackKeys } from "./callbacks";
import { callKeys } from "./calls";
import { api, unwrap } from "./client";
import { qk } from "./queries";
import type { components } from "./schema";

type S = components["schemas"];
export type LiveCall = S["LiveCall"];
export type LiveCallList = S["LiveCallList"];

export const liveKeys = { all: ["calls", "live"] as const };

/** While a call rings or is live: fast enough that ringing, answering and hanging up show at once. */
export const LIVE_POLL_MS = 3_000;
/** Nothing on air: a new call still shows up within this long on every page. */
export const LIVE_IDLE_MS = 15_000;
/** Pricing and analysis land a few seconds after a call ends; balance and dashboard refresh again then. */
export const SETTLE_REFRESH_MS = 20_000;

export function liveCallsInterval(data: Pick<LiveCallList, "count"> | undefined): number {
  return data && data.count > 0 ? LIVE_POLL_MS : LIVE_IDLE_MS;
}

/** Server clock minus this browser's clock, so ticking durations match the server's. */
let skewMs = 0;
export const serverNow = () => Date.now() + skewMs;
export function setClockSkew(serverTime: string, receivedAt = Date.now()) {
  const t = Date.parse(serverTime);
  if (!Number.isNaN(t)) skewMs = t - receivedAt;
}

export function useLiveCalls() {
  return useQuery({
    queryKey: liveKeys.all,
    queryFn: async () => {
      const body = (await unwrap(api.GET("/calls/live"))) as LiveCallList;
      setClockSkew(body.server_time);
      return body;
    },
    enabled: session.isSignedIn(),
    staleTime: 2_000,
    // Intervals pause while the tab is hidden (React Query's default), so idle tabs cost nothing.
    refetchInterval: (q) => liveCallsInterval(q.state.data),
  });
}

export interface LiveDiff {
  started: string[];
  connected: string[];
  ended: string[];
}

/** What changed between two polls of the live list. `prev` null is the first poll: nothing changed. */
export function diffLive(prev: Map<string, string> | null, next: Pick<LiveCall, "call_id" | "status">[]): LiveDiff {
  const out: LiveDiff = { started: [], connected: [], ended: [] };
  if (!prev) return out;
  const now = new Map(next.map((c) => [c.call_id, c.status]));
  for (const [id, status] of now) {
    const before = prev.get(id);
    if (before === undefined) out.started.push(id);
    else if (before !== status && status === "in_progress") out.connected.push(id);
  }
  for (const id of prev.keys()) if (!now.has(id)) out.ended.push(id);
  return out;
}

function refreshAfterEnd(qc: QueryClient) {
  void qc.invalidateQueries({ queryKey: callKeys.dashboard });
  void qc.invalidateQueries({ queryKey: qk.balance });
  void qc.invalidateQueries({ queryKey: qk.transactionsAll });
  void qc.invalidateQueries({ queryKey: ["usage"] });
}

/** Mounted once in the shell: turns live-list changes into targeted refreshes elsewhere. */
export function useLiveCallSync() {
  const qc = useQueryClient();
  const live = useLiveCalls();
  const prev = useRef<Map<string, string> | null>(null);
  const settle = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(settle.current), []);

  useEffect(() => {
    const items = live.data?.items;
    if (!items) return;
    const d = diffLive(prev.current, items);
    prev.current = new Map(items.map((c) => [c.call_id, c.status]));
    if (d.started.length) {
      void qc.invalidateQueries({ queryKey: ["calls", "list"] });
      void qc.invalidateQueries({ queryKey: callKeys.any });
    }
    for (const id of [...d.connected, ...d.ended]) {
      void qc.invalidateQueries({ queryKey: callKeys.detail(id) });
      void qc.invalidateQueries({ queryKey: callKeys.transcript(id) });
    }
    if (d.ended.length) {
      void qc.invalidateQueries({ queryKey: ["calls", "list"] });
      void qc.invalidateQueries({ queryKey: callbackKeys.all });
      refreshAfterEnd(qc);
      window.clearTimeout(settle.current);
      settle.current = window.setTimeout(() => refreshAfterEnd(qc), SETTLE_REFRESH_MS);
    }
  }, [live.data, qc]);

  return live;
}
