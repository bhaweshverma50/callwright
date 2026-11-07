/**
 * Outbound calls and their compliance settings (010 T078, contracts/outbound.yaml): the
 * do-not-call list, calling hours and the log of blocked attempts.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, postForm, unwrap } from "../../../api/client";
import type { components } from "../../../api/schema";

type S = components["schemas"];
export type DncEntry = S["DncEntry"];
export type DncImportResult = S["DncImportResult"];
export type CallingHours = S["CallingHours"];
export type WeeklyWindows = S["WeeklyWindows"];
export type DayWindow = WeeklyWindows["mon"];
export type PolicyDecision = S["PolicyDecision"];
export type OutboundCallRequest = S["OutboundCallRequest"];
export type OutboundCallAccepted = S["OutboundCallAccepted"];
interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export type Day = (typeof DAYS)[number];
export const DAY_LABELS: Record<Day, string> = {
  mon: "Monday",
  tue: "Tuesday",
  wed: "Wednesday",
  thu: "Thursday",
  fri: "Friday",
  sat: "Saturday",
  sun: "Sunday",
};

export const complianceKeys = {
  all: ["channels", "compliance"] as const,
  dnc: (q: string, page: number) => ["channels", "compliance", "dnc", q, page] as const,
  hours: ["channels", "compliance", "hours"] as const,
  decisions: ["channels", "compliance", "decisions"] as const,
};

export function useDncEntries(number: string, page: number) {
  return useQuery({
    queryKey: complianceKeys.dnc(number, page),
    queryFn: () =>
      unwrap(api.GET("/dnc-entries", { params: { query: { page, page_size: 20, ...(number && { number }) } } })) as Promise<Page<DncEntry>>,
    placeholderData: keepPreviousData,
  });
}

export function useCallingHours() {
  return useQuery({ queryKey: complianceKeys.hours, queryFn: () => unwrap(api.GET("/outbound-calling-hours")) as Promise<CallingHours> });
}

export function useDecisions() {
  return useQuery({
    queryKey: complianceKeys.decisions,
    queryFn: () => unwrap(api.GET("/outbound-policy-decisions", { params: { query: { page: 1, page_size: 8 } } })) as Promise<Page<PolicyDecision>>,
  });
}

function useInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: complianceKeys.all });
}

export function useDncMutations() {
  const invalidate = useInvalidate();
  const add = useMutation({
    mutationFn: (body: { number: string; default_region?: string; note?: string }) => unwrap(api.POST("/dnc-entries", { body })) as Promise<DncEntry>,
    onSuccess: () => void invalidate(),
  });
  const remove = useMutation({
    mutationFn: async (id: string) => {
      const res = await api.DELETE("/dnc-entries/{dnc_id}", { params: { path: { dnc_id: id } } });
      if (!res.response.ok) await unwrap(Promise.resolve(res));
    },
    onSuccess: () => void invalidate(),
  });
  return { add, remove };
}

export function useDncImport() {
  const invalidate = useInvalidate();
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
    mutationFn: (windows: WeeklyWindows) => unwrap(api.PUT("/outbound-calling-hours", { body: { windows } })) as Promise<CallingHours>,
    onSuccess: (data) => qc.setQueryData(complianceKeys.hours, data),
  });
}

export function usePlaceCall() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ body, key }: { body: OutboundCallRequest; key: string }) =>
      unwrap(api.POST("/outbound-calls", { body, params: { header: { "Idempotency-Key": key } } })) as Promise<OutboundCallAccepted>,
    onSettled: () => void qc.invalidateQueries({ queryKey: complianceKeys.decisions }),
    // The placed call rings at once: the live badge, the dashboard card and Call History show it.
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["calls", "live"] });
      void qc.invalidateQueries({ queryKey: ["calls", "list"] });
    },
  });
}
