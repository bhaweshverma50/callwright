/** WhatsApp voice channels and caller routes (010 T055, contracts/whatsapp.yaml). */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "../../../api/client";
import type { components } from "../../../api/schema";

type S = components["schemas"];
export type WhatsAppChannel = S["WhatsAppChannel"];
export type WhatsAppChannelCreate = S["WhatsAppChannelCreate"];
export type WhatsAppChannelUpdate = S["WhatsAppChannelUpdate"];
export type CallerRoute = S["CallerRoute"];
export interface WhatsAppSettings {
  callback_url: string;
  default_graph_api_version: string;
  telephony_enabled: boolean;
}
interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export const waKeys = {
  all: ["channels", "whatsapp"] as const,
  list: ["channels", "whatsapp", "list"] as const,
  settings: ["channels", "whatsapp", "settings"] as const,
  routes: (id: string, q: string, page: number) => ["channels", "whatsapp", "routes", id, q, page] as const,
};

export function useWhatsAppChannels() {
  return useQuery({
    queryKey: waKeys.list,
    queryFn: () => unwrap(api.GET("/whatsapp/channels", { params: { query: { page: 1, page_size: 100 } } })) as Promise<Page<WhatsAppChannel>>,
    refetchInterval: (q) =>
      (q.state.data as Page<WhatsAppChannel> | undefined)?.items.some((c) => c.status === "setup_incomplete" || c.status === "draining")
        ? 5000
        : false,
  });
}

export function useWhatsAppSettings(enabled = true) {
  return useQuery({
    queryKey: waKeys.settings,
    queryFn: () => unwrap(api.GET("/whatsapp/settings")) as Promise<WhatsAppSettings>,
    staleTime: 5 * 60_000,
    enabled,
  });
}

function useInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: waKeys.all });
}

export function useCreateWhatsApp() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: WhatsAppChannelCreate) => unwrap(api.POST("/whatsapp/channels", { body })) as Promise<WhatsAppChannel>,
    onSuccess: () => void invalidate(),
  });
}

export function useUpdateWhatsApp(id: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: WhatsAppChannelUpdate) =>
      unwrap(api.PATCH("/whatsapp/channels/{channel_id}", { params: { path: { channel_id: id } }, body })) as Promise<WhatsAppChannel>,
    onSuccess: () => void invalidate(),
  });
}

export function useRetryWhatsApp(id: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: () =>
      unwrap(api.POST("/whatsapp/channels/{channel_id}/retry-setup", { params: { path: { channel_id: id } } })) as Promise<WhatsAppChannel>,
    onSuccess: () => void invalidate(),
  });
}

export function useDeleteWhatsApp(id: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (whenIdle: boolean) => {
      const res = await api.DELETE("/whatsapp/channels/{channel_id}", { params: { path: { channel_id: id }, query: { when_idle: whenIdle } } });
      if (!res.response.ok) await unwrap(Promise.resolve(res));
      return res.response.status === 202 ? ("draining" as const) : ("deleted" as const);
    },
    onSuccess: () => void invalidate(),
  });
}

export function useCallerRoutes(channelId: string, caller: string, page = 1) {
  return useQuery({
    queryKey: waKeys.routes(channelId, caller, page),
    queryFn: () =>
      unwrap(
        api.GET("/whatsapp/channels/{channel_id}/caller-routes", {
          params: { path: { channel_id: channelId }, query: { page, page_size: 50, ...(caller && { caller }) } },
        }),
      ) as Promise<Page<CallerRoute>>,
    placeholderData: keepPreviousData,
  });
}

export function useRouteMutations(channelId: string) {
  const invalidate = useInvalidate();
  const path = { channel_id: channelId };
  const create = useMutation({
    mutationFn: (body: { caller_number: string; agent_id: string }) =>
      unwrap(api.POST("/whatsapp/channels/{channel_id}/caller-routes", { params: { path }, body })) as Promise<CallerRoute>,
    onSuccess: () => void invalidate(),
  });
  const update = useMutation({
    mutationFn: ({ id, agent_id }: { id: string; agent_id: string }) =>
      unwrap(
        api.PATCH("/whatsapp/channels/{channel_id}/caller-routes/{route_id}", { params: { path: { ...path, route_id: id } }, body: { agent_id } }),
      ) as Promise<CallerRoute>,
    onSuccess: () => void invalidate(),
  });
  const remove = useMutation({
    mutationFn: async (id: string) => {
      const res = await api.DELETE("/whatsapp/channels/{channel_id}/caller-routes/{route_id}", { params: { path: { ...path, route_id: id } } });
      if (!res.response.ok) await unwrap(Promise.resolve(res));
    },
    onSuccess: () => void invalidate(),
  });
  return { create, update, remove };
}
