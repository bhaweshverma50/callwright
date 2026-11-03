/** Scheduled callbacks (spec 011): types from the contract and TanStack Query hooks. */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import type { components } from "./schema";

type S = components["schemas"];

export type Callback = S["Callback"];
export type CallbackStatus = S["CallbackStatus"];
export interface CallbackPage {
  items: Callback[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export const CALLBACK_PAGE_SIZE = 20;

export const callbackKeys = {
  all: ["callbacks"] as const,
  list: (status: CallbackStatus | null, page: number) => ["callbacks", "list", status ?? "all", page] as const,
  forCall: (callId: string) => ["callbacks", "call", callId] as const,
  scheduledCount: ["callbacks", "scheduled-count"] as const,
};

/** Callbacks that will still change on their own; lists showing one refresh while the tab is visible. */
const OPEN = new Set(["scheduled", "placing"]);
const POLL_OPEN_MS = 10_000;
const openIn = (items: { status: string }[] | undefined) => !!items?.some((c) => OPEN.has(c.status));

/** One page of callbacks. With `status=scheduled` the soonest comes first, otherwise the latest. */
export function useCallbacks(status: CallbackStatus | null, page: number) {
  return useQuery({
    queryKey: callbackKeys.list(status, page),
    queryFn: () =>
      unwrap(
        api.GET("/callbacks", { params: { query: { page, page_size: CALLBACK_PAGE_SIZE, ...(status && { status }) } } }),
      ) as Promise<CallbackPage>,
    placeholderData: keepPreviousData,
    refetchInterval: (q) => (openIn(q.state.data?.items) ? POLL_OPEN_MS : false),
  });
}

/** Callbacks booked on one call (the call drawer card). Usually none, at most a few. */
export function useCallCallbacks(callId: string | null) {
  return useQuery({
    queryKey: callbackKeys.forCall(callId ?? ""),
    queryFn: async () => {
      const page = (await unwrap(api.GET("/callbacks", { params: { query: { source_call_id: callId!, page_size: 10 } } }))) as CallbackPage;
      return page.items;
    },
    enabled: Boolean(callId),
    refetchInterval: (q) => (openIn(q.state.data) ? POLL_OPEN_MS : false),
  });
}

/** How many callbacks are still waiting to be placed, for the Callbacks tab count. */
export function useScheduledCallbackCount() {
  return useQuery({
    queryKey: callbackKeys.scheduledCount,
    queryFn: async () => {
      const page = (await unwrap(api.GET("/callbacks", { params: { query: { status: "scheduled", page_size: 1 } } }))) as CallbackPage;
      return page.total;
    },
    staleTime: 30_000,
    // Callbacks are placed by a cron; the tab count follows while any are waiting.
    refetchInterval: (q) => (q.state.data ? 30_000 : false),
  });
}

/** Cancels a scheduled callback. A 409 `callback_not_scheduled` means it is already being placed or done. */
export function useCancelCallback() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => unwrap(api.POST("/callbacks/{callback_id}/cancel", { params: { path: { callback_id: id } } })) as Promise<Callback>,
    onSettled: () => qc.invalidateQueries({ queryKey: callbackKeys.all }),
  });
}
