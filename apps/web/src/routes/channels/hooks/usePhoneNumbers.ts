/**
 * Phone numbers and SIP settings (010 T021, contracts/phone_numbers.yaml). Lists refetch while
 * a number is provisioning or draining so status changes appear without a reload.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "../../../api/client";
import type { AgentSummary } from "../../../api/agents";
import type { components } from "../../../api/schema";

type S = components["schemas"];
export type PhoneNumber = S["PhoneNumber"];
export type PhoneNumberImport = S["PhoneNumberImport"];
export type PhoneNumberUpdate = S["PhoneNumberUpdate"];
export type Transport = S["Transport"];
export interface SipSettings {
  origination_uri: string;
  direct_uri_template: string;
  transports: string[];
  telephony_enabled: boolean;
}
export interface NumberPage {
  items: PhoneNumber[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export const channelKeys = {
  all: ["channels"] as const,
  numbers: (page: number) => ["channels", "numbers", page] as const,
  number: (id: string) => ["channels", "number", id] as const,
  sip: ["channels", "sip-settings"] as const,
  agents: ["channels", "agents"] as const,
};

const settling = (n: PhoneNumber) => n.status === "provisioning" || n.status === "draining";

export function usePhoneNumbers(page = 1, pageSize = 50) {
  return useQuery({
    queryKey: channelKeys.numbers(page),
    queryFn: () => unwrap(api.GET("/phone-numbers", { params: { query: { page, page_size: pageSize } } })) as Promise<NumberPage>,
    placeholderData: keepPreviousData,
    refetchInterval: (q) => ((q.state.data as NumberPage | undefined)?.items.some(settling) ? 5000 : false),
  });
}

export function useSipSettings() {
  return useQuery({
    queryKey: channelKeys.sip,
    queryFn: () => unwrap(api.GET("/phone-numbers/sip-settings")) as Promise<SipSettings>,
    staleTime: 5 * 60_000,
  });
}

/** Every agent in the workspace (pickers list the published ones first). */
export function useAgentOptions(enabled = true) {
  return useQuery({
    queryKey: channelKeys.agents,
    queryFn: async () => {
      const out: AgentSummary[] = [];
      for (let page = 1; page < 30; page++) {
        const res = (await unwrap(api.GET("/agents", { params: { query: { page, page_size: 100 } } }))) as {
          items: AgentSummary[];
          total_pages: number;
        };
        out.push(...res.items);
        if (page >= res.total_pages) break;
      }
      return out;
    },
    enabled,
    staleTime: 60_000,
  });
}

function useInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: channelKeys.all });
}

export function useImportNumber() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: PhoneNumberImport) => unwrap(api.POST("/phone-numbers", { body })) as Promise<PhoneNumber>,
    onSuccess: () => void invalidate(),
  });
}

export function useUpdateNumber(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PhoneNumberUpdate) =>
      unwrap(api.PATCH("/phone-numbers/{number_id}", { params: { path: { number_id: id } }, body })) as Promise<PhoneNumber>,
    onSuccess: (n) => {
      qc.setQueryData(channelKeys.number(id), n);
      void qc.invalidateQueries({ queryKey: ["channels", "numbers"] });
    },
  });
}

export function useRetryNumber(id: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: () =>
      unwrap(api.POST("/phone-numbers/{number_id}/retry-provisioning", { params: { path: { number_id: id } } })) as Promise<PhoneNumber>,
    onSuccess: () => void invalidate(),
  });
}

export function useDeleteNumber(id: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (whenIdle: boolean) => {
      const res = await api.DELETE("/phone-numbers/{number_id}", { params: { path: { number_id: id }, query: { when_idle: whenIdle } } });
      if (!res.response.ok) await unwrap(Promise.resolve(res));
      return res.response.status === 202 ? ("draining" as const) : ("deleted" as const);
    },
    onSuccess: () => void invalidate(),
  });
}

export function useSendTestEvent() {
  return useMutation({
    mutationFn: (url: string) => unwrap(api.POST("/webhooks/test", { body: { url } })),
  });
}

export function agentName(agents: AgentSummary[] | undefined, id: string | null | undefined): string | null {
  if (!id) return null;
  return agents?.find((a) => a.id === id)?.name ?? "Unknown agent";
}
