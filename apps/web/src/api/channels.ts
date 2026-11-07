/**
 * Channels (spec 010): phone numbers and SIP settings (contracts/phone_numbers.yaml), WhatsApp
 * voice channels and caller routes (contracts/whatsapp.yaml), outbound calls and their compliance
 * settings (contracts/outbound.yaml). Lists refetch while a number or channel is still settling so
 * status changes appear without a reload.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { callKeys } from "./calls";
import { api, fetchAll, postForm, unwrap } from "./client";
import type { components } from "./schema";
import type { ResponseOf } from "./types";

type S = components["schemas"];

/** A delete that waits for active calls answers 202 (draining) instead of 204. */
async function drainOrDelete(call: Promise<{ response: Response; error?: unknown; data?: unknown }>) {
  await unwrap(call);
  return (await call).response.status === 202 ? ("draining" as const) : ("deleted" as const);
}

export type PhoneNumber = S["PhoneNumber"];
export type PhoneNumberImport = S["PhoneNumberImport"];
export type PhoneNumberUpdate = S["PhoneNumberUpdate"];
export type Transport = S["Transport"];
export type SipSettings = ResponseOf<"/phone-numbers/sip-settings", "get">;
export type NumberPage = ResponseOf<"/phone-numbers", "get">;

export const channelKeys = {
  all: ["channels"] as const,
  numberLists: ["channels", "numbers"] as const,
  numbers: (page: number) => ["channels", "numbers", page] as const,
  number: (id: string) => ["channels", "number", id] as const,
  sip: ["channels", "sip-settings"] as const,
};

const settling = (n: PhoneNumber) => n.status === "provisioning" || n.status === "draining";

export function usePhoneNumbers(page = 1) {
  return useQuery({
    queryKey: channelKeys.numbers(page),
    queryFn: () => unwrap(api.GET("/phone-numbers", { params: { query: { page, page_size: 50 } } })),
    placeholderData: keepPreviousData,
    refetchInterval: (q) => (q.state.data?.items.some(settling) ? 5000 : false),
  });
}

export function useSipSettings() {
  return useQuery({
    queryKey: channelKeys.sip,
    queryFn: () => unwrap(api.GET("/phone-numbers/sip-settings")),
    staleTime: 5 * 60_000,
  });
}

function useInvalidateNumbers() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: channelKeys.all });
}

export function useImportNumber() {
  const invalidate = useInvalidateNumbers();
  return useMutation({
    mutationFn: (body: PhoneNumberImport) => unwrap(api.POST("/phone-numbers", { body })),
    onSuccess: () => void invalidate(),
  });
}

export function useUpdateNumber(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PhoneNumberUpdate) => unwrap(api.PATCH("/phone-numbers/{number_id}", { params: { path: { number_id: id } }, body })),
    onSuccess: (n) => {
      qc.setQueryData(channelKeys.number(id), n);
      void qc.invalidateQueries({ queryKey: channelKeys.numberLists });
    },
  });
}

export function useRetryNumber(id: string) {
  const invalidate = useInvalidateNumbers();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/phone-numbers/{number_id}/retry-provisioning", { params: { path: { number_id: id } } })),
    onSuccess: () => void invalidate(),
  });
}

export function useDeleteNumber(id: string) {
  const invalidate = useInvalidateNumbers();
  return useMutation({
    mutationFn: (whenIdle: boolean) =>
      drainOrDelete(api.DELETE("/phone-numbers/{number_id}", { params: { path: { number_id: id }, query: { when_idle: whenIdle } } })),
    onSuccess: () => void invalidate(),
  });
}

export function useSendTestEvent() {
  return useMutation({
    mutationFn: (url: string) => unwrap(api.POST("/webhooks/test", { body: { url } })),
  });
}

export type WhatsAppChannel = S["WhatsAppChannel"];
export type WhatsAppChannelCreate = S["WhatsAppChannelCreate"];
export type WhatsAppChannelUpdate = S["WhatsAppChannelUpdate"];
export type CallerRoute = S["CallerRoute"];
export type WhatsAppSettings = ResponseOf<"/whatsapp/settings", "get">;

export const waKeys = {
  all: ["channels", "whatsapp"] as const,
  list: ["channels", "whatsapp", "list"] as const,
  settings: ["channels", "whatsapp", "settings"] as const,
  routes: (id: string, q: string, page: number) => ["channels", "whatsapp", "routes", id, q, page] as const,
};

export function useWhatsAppChannels() {
  return useQuery({
    queryKey: waKeys.list,
    queryFn: async () => ({ items: await fetchAll((query) => unwrap(api.GET("/whatsapp/channels", { params: { query } }))) }),
    refetchInterval: (q) => (q.state.data?.items.some((c) => c.status === "setup_incomplete" || c.status === "draining") ? 5000 : false),
  });
}

export function useWhatsAppSettings(enabled = true) {
  return useQuery({
    queryKey: waKeys.settings,
    queryFn: () => unwrap(api.GET("/whatsapp/settings")),
    staleTime: 5 * 60_000,
    enabled,
  });
}

function useInvalidateWhatsApp() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: waKeys.all });
}

export function useCreateWhatsApp() {
  const invalidate = useInvalidateWhatsApp();
  return useMutation({
    mutationFn: (body: WhatsAppChannelCreate) => unwrap(api.POST("/whatsapp/channels", { body })),
    onSuccess: () => void invalidate(),
  });
}

export function useUpdateWhatsApp(id: string) {
  const invalidate = useInvalidateWhatsApp();
  return useMutation({
    mutationFn: (body: WhatsAppChannelUpdate) => unwrap(api.PATCH("/whatsapp/channels/{channel_id}", { params: { path: { channel_id: id } }, body })),
    onSuccess: () => void invalidate(),
  });
}

export function useRetryWhatsApp(id: string) {
  const invalidate = useInvalidateWhatsApp();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/whatsapp/channels/{channel_id}/retry-setup", { params: { path: { channel_id: id } } })),
    onSuccess: () => void invalidate(),
  });
}

export function useDeleteWhatsApp(id: string) {
  const invalidate = useInvalidateWhatsApp();
  return useMutation({
    mutationFn: (whenIdle: boolean) =>
      drainOrDelete(api.DELETE("/whatsapp/channels/{channel_id}", { params: { path: { channel_id: id }, query: { when_idle: whenIdle } } })),
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
      ),
    placeholderData: keepPreviousData,
  });
}

export function useRouteMutations(channelId: string) {
  const invalidate = useInvalidateWhatsApp();
  const path = { channel_id: channelId };
  const create = useMutation({
    mutationFn: (body: { caller_number: string; agent_id: string }) =>
      unwrap(api.POST("/whatsapp/channels/{channel_id}/caller-routes", { params: { path }, body })),
    onSuccess: () => void invalidate(),
  });
  const update = useMutation({
    mutationFn: ({ id, agent_id }: { id: string; agent_id: string }) =>
      unwrap(
        api.PATCH("/whatsapp/channels/{channel_id}/caller-routes/{route_id}", { params: { path: { ...path, route_id: id } }, body: { agent_id } }),
      ),
    onSuccess: () => void invalidate(),
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/whatsapp/channels/{channel_id}/caller-routes/{route_id}", { params: { path: { ...path, route_id: id } } })),
    onSuccess: () => void invalidate(),
  });
  return { create, update, remove };
}

export type DncEntry = S["DncEntry"];
export type DncImportResult = S["DncImportResult"];
export type CallingHours = S["CallingHours"];
export type WeeklyWindows = S["WeeklyWindows"];
export type DayWindow = WeeklyWindows["mon"];
export type PolicyDecision = S["PolicyDecision"];
export type OutboundCallRequest = S["OutboundCallRequest"];
export type OutboundCallAccepted = S["OutboundCallAccepted"];

export const complianceKeys = {
  all: ["channels", "compliance"] as const,
  dnc: (q: string, page: number) => ["channels", "compliance", "dnc", q, page] as const,
  hours: ["channels", "compliance", "hours"] as const,
  decisions: ["channels", "compliance", "decisions"] as const,
};

export function useDncEntries(number: string, page: number) {
  return useQuery({
    queryKey: complianceKeys.dnc(number, page),
    queryFn: () => unwrap(api.GET("/dnc-entries", { params: { query: { page, page_size: 20, ...(number && { number }) } } })),
    placeholderData: keepPreviousData,
  });
}

export function useCallingHours() {
  return useQuery({ queryKey: complianceKeys.hours, queryFn: () => unwrap(api.GET("/outbound-calling-hours")) });
}

export function useDecisions() {
  return useQuery({
    queryKey: complianceKeys.decisions,
    queryFn: () => unwrap(api.GET("/outbound-policy-decisions", { params: { query: { page: 1, page_size: 8 } } })),
  });
}

function useInvalidateCompliance() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: complianceKeys.all });
}

export function useDncMutations() {
  const invalidate = useInvalidateCompliance();
  const add = useMutation({
    mutationFn: (body: { number: string; default_region?: string; note?: string }) => unwrap(api.POST("/dnc-entries", { body })),
    onSuccess: () => void invalidate(),
  });
  const remove = useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/dnc-entries/{dnc_id}", { params: { path: { dnc_id: id } } })),
    onSuccess: () => void invalidate(),
  });
  return { add, remove };
}

export function useDncImport() {
  const invalidate = useInvalidateCompliance();
  return useMutation({
    mutationFn: async ({ file, region }: { file: File; region?: string }) => {
      const form = new FormData();
      form.append("file", file);
      if (region) form.append("default_region", region);
      return postForm("/dnc-entries/import", form);
    },
    onSuccess: () => void invalidate(),
  });
}

export function useSaveCallingHours() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (windows: WeeklyWindows) => unwrap(api.PUT("/outbound-calling-hours", { body: { windows } })),
    onSuccess: (data) => qc.setQueryData(complianceKeys.hours, data),
  });
}

export function usePlaceCall() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ body, key }: { body: OutboundCallRequest; key: string }) =>
      unwrap(api.POST("/outbound-calls", { body, params: { header: { "Idempotency-Key": key } } })),
    onSettled: () => void qc.invalidateQueries({ queryKey: complianceKeys.decisions }),
    // The placed call rings at once: the live badge, the dashboard card and Call History show it.
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: callKeys.live });
      void qc.invalidateQueries({ queryKey: callKeys.lists });
    },
  });
}
