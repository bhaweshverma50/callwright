/** Caller language (spec 012): types from the contract and TanStack Query hooks. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import type { components } from "./schema";

type S = components["schemas"];

export type LanguageRef = S["LanguageRef"];
export type CallerPreference = S["CallerPreference"];
export type CallLanguage = S["CallLanguage"];
export type CallLanguageSwitch = S["CallLanguageSwitch"];

export const callerLanguageKeys = {
  all: ["caller-language"] as const,
  forCall: (callId: string) => ["caller-language", "call", callId] as const,
};

/** The languages of one call (the call drawer card): agent, start, switches and the saved one. */
export function useCallLanguage(callId: string | null) {
  return useQuery({
    queryKey: callerLanguageKeys.forCall(callId ?? ""),
    queryFn: () => unwrap(api.GET("/calls/{call_id}/language", { params: { path: { call_id: callId! } } })),
    enabled: Boolean(callId),
  });
}

/** Forgets a caller's saved language: their next call starts in the agent's language again. */
export function useForgetCallerPreference() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/caller-preferences/{preference_id}", { params: { path: { preference_id: id } } })),
    onSettled: () => qc.invalidateQueries({ queryKey: callerLanguageKeys.all }),
  });
}
