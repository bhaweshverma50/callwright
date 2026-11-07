/**
 * The two assistants outside the agent editor: the analytics "Ask" panel (spec 006) and the voice
 * copilot's command interpreter with its streaming transcription credential.
 */
import { useQuery } from "@tanstack/react-query";
import { api, postForm, unwrap } from "./client";
import type { components } from "./schema";
import type { BodyOf } from "./types";

type S = components["schemas"];

export type StreamCredential = S["StreamCredential"];
export type AnalyticsChatRequest = BodyOf<"/analytics/chat", "post">;
export type InterpretRequest = BodyOf<"/voice-commands/interpret", "post">;

export const assistantKeys = {
  analyticsCatalog: ["analytics", "catalog"] as const,
};

/** Suggested questions and what the analytics assistant can answer. */
export function useAnalyticsCatalog(enabled: boolean) {
  return useQuery({
    queryKey: assistantKeys.analyticsCatalog,
    queryFn: () => unwrap(api.GET("/analytics/catalog")),
    enabled,
    staleTime: 10 * 60_000,
  });
}

/** One answered question (paid: the key is fixed per question so a retry never charges twice). */
export function askAnalytics(body: AnalyticsChatRequest, key: string) {
  return unwrap(api.POST("/analytics/chat", { params: { header: { "Idempotency-Key": key } }, body }));
}

/** A short-lived listen-only credential for browser-direct transcription (FR-020: on first use only). */
export function fetchStreamCredential() {
  return unwrap(api.POST("/voice-commands/stream-token"));
}

export function interpretCommand(body: InterpretRequest) {
  return unwrap(api.POST("/voice-commands/interpret", { body }));
}

/** Transcribes a recorded command when the streaming credential was not available. */
export function transcribeCommand(audio: Blob) {
  const form = new FormData();
  form.append("audio", audio, "command.webm");
  return postForm("/voice-commands/transcribe", form);
}
