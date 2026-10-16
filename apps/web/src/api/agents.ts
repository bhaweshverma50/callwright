/**
 * Types and TanStack Query hooks for spec 002 (agents, versions, templates, catalogs, prompt
 * assistant). Everything is typed from the generated contract (schema.d.ts); the only local
 * addition is `advanced.recording` (002 T088), which the contract does not list yet.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import type { components, paths } from "./schema";

type S = components["schemas"];

export type AgentType = S["AgentType"];
export type RecordingMode = "inherit" | "on" | "off";
/** AgentConfig plus `advanced.recording` (T088: inherit | on | off, default inherit). */
export type AgentConfig = Omit<S["AgentConfig"], "advanced"> & {
  advanced: S["AgentConfig"]["advanced"] & { recording?: RecordingMode };
};
export type DynamicVariable = S["DynamicVariable"];
export type PronunciationEntry = S["PronunciationEntry"];
export type ModelRef = S["ModelRef"];
export type BackgroundAudioSource = S["BackgroundAudioSource"];
export type ConfigIssue = S["ConfigIssue"];
export type ConfigValidationResult = Omit<S["ConfigValidationResult"], "normalized_config"> & { normalized_config: AgentConfig };
export type VersionRef = S["VersionRef"];
export type AgentSummary = S["AgentSummary"];
export type AgentDetail = Omit<S["AgentDetail"], "draft_config"> & { draft_config: AgentConfig };
export type SaveResult = Omit<S["SaveResult"], "agent"> & { agent: AgentDetail };
export type AgentPage = S["PageMeta"] & { items: AgentSummary[] };

export type VersionSource = S["VersionSource"];
export type VersionSummary = S["VersionSummary"];
export type VersionDetail = Omit<S["VersionDetail"], "config"> & { config: AgentConfig };
export type VersionChange = S["Change"];
export type VersionDiff = { from: string; to: string; changes: VersionChange[] };
export type VersionPage = S["PageMeta"] & { items: VersionSummary[] };

export type TemplateCategory = S["TemplateCategory"];
export type TemplateSummary = S["TemplateSummary"];
export type TemplateDetail = Omit<S["TemplateDetail"], "config"> & { config: TemplateConfig };
export interface TemplateConfig {
  agent_name: string;
  language: string;
  llm: { provider: string; model: string };
  prompt: string;
  begin_message: string | null;
  start_speaker: "agent" | "user";
  stt: { provider: string; model?: string | null };
  tts: { provider: string; model: string };
  dynamic_variables: DynamicVariable[];
}
export type TemplateCategoryCount = { id: TemplateCategory; label: string; count: number };

export type LlmCatalog = S["LlmCatalog"];
export type LlmProvider = S["LlmProvider"];
export type LlmModel = S["LlmModel"];
export type TemperatureRule = S["TemperatureRule"];

export type VoiceCatalog = S["VoiceCatalog"];
export type Language = S["Language"];
export type SttProvider = S["SttProvider"];
export type SttModel = S["SttModel"];
export type TtsProvider = S["TtsProvider"];
export type TtsModel = S["TtsModel"];
export type NoiseCancellationOption = S["NoiseCancellationOption"];
export type ControlRange = S["ControlRange"];
export type Voice = S["Voice"];
export type VoicePage = { items: Voice[]; next_cursor: string | null };
export type AmbientAudioFile = S["AmbientAudioFile"];

export type PromptAiRequest = paths["/prompt-ai/generate"]["post"]["requestBody"]["content"]["application/json"];
export type PromptAiResponse = paths["/prompt-ai/generate"]["post"]["responses"]["200"]["content"]["application/json"];
export type PromptProposal = NonNullable<PromptAiResponse["proposal"]>;

export interface VoiceFilters {
  search?: string;
  gender?: "female" | "male" | "neutral";
  language?: string;
  model?: string;
}

export const agentKeys = {
  all: ["agents"] as const,
  list: (search: string, type: AgentType | null, page: number) => ["agents", "list", { search, type, page }] as const,
  detail: (id: string) => ["agents", "detail", id] as const,
  defaults: (language: string) => ["agents", "defaults", language] as const,
  versions: (id: string) => ["agents", "versions", id] as const,
  version: (id: string, vid: string) => ["agents", "versions", id, vid] as const,
  diff: (id: string, vid: string, against: string) => ["agents", "diff", id, vid, against] as const,
  llms: ["llms", "catalog"] as const,
  voices: ["voices", "catalog"] as const,
  providerVoices: (provider: string, f: VoiceFilters) => ["voices", "list", provider, f] as const,
  ambient: ["voices", "ambient"] as const,
  templates: (category: TemplateCategory | null, search: string) => ["templates", "list", { category, search }] as const,
  templateCategories: ["templates", "categories"] as const,
  template: (id: string) => ["templates", "detail", id] as const,
};

export const PAGE_SIZE = 24;

export function useAgents(search: string, type: AgentType | null, page: number) {
  return useQuery({
    queryKey: agentKeys.list(search, type, page),
    queryFn: () =>
      unwrap(
        api.GET("/agents", {
          params: { query: { page, page_size: PAGE_SIZE, ...(search && { search }), ...(type && { type }) } },
        }),
      ) as Promise<AgentPage>,
    placeholderData: keepPreviousData,
  });
}

export function useAgent(id: string | undefined) {
  return useQuery({
    queryKey: agentKeys.detail(id ?? ""),
    queryFn: () => unwrap(api.GET("/agents/{agent_id}", { params: { path: { agent_id: id! } } })) as Promise<AgentDetail>,
    enabled: !!id,
    staleTime: 0,
    refetchOnWindowFocus: false,
  });
}

export function useAgentDefaults(language: string, enabled = true) {
  return useQuery({
    queryKey: agentKeys.defaults(language),
    queryFn: () => unwrap(api.GET("/agents/defaults", { params: { query: { type: "single_prompt", language } } })) as Promise<AgentConfig>,
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useLlmCatalog() {
  return useQuery({
    queryKey: agentKeys.llms,
    queryFn: () => unwrap(api.GET("/llms/catalog", { params: { query: { include_withdrawn: true } } })),
    staleTime: 5 * 60_000,
  });
}

export function useVoiceCatalog() {
  return useQuery({
    queryKey: agentKeys.voices,
    queryFn: () => unwrap(api.GET("/voices/catalog")),
    staleTime: 5 * 60_000,
  });
}

export function fetchProviderVoices(provider: string, f: VoiceFilters, cursor?: string) {
  return unwrap(
    api.GET("/voices/{provider}/voices", {
      params: {
        path: { provider },
        query: {
          limit: 50,
          ...(f.search && { search: f.search }),
          ...(f.gender && { gender: f.gender }),
          ...(f.language && { language: f.language }),
          ...(f.model && { model: f.model }),
          ...(cursor && { cursor }),
        },
      },
    }),
  ) as Promise<VoicePage>;
}

export function useProviderVoices(provider: string, f: VoiceFilters, enabled = true) {
  return useQuery({
    queryKey: agentKeys.providerVoices(provider, f),
    queryFn: () => fetchProviderVoices(provider, f),
    enabled: enabled && !!provider,
    staleTime: 10 * 60_000,
    placeholderData: keepPreviousData,
    retry: false,
  });
}

export function useAmbientAudio(enabled = true) {
  return useQuery({
    queryKey: agentKeys.ambient,
    queryFn: () => unwrap(api.GET("/voices/ambient-audio")),
    enabled,
  });
}

export function useTemplates(category: TemplateCategory | null, search: string) {
  return useQuery({
    queryKey: agentKeys.templates(category, search),
    queryFn: () => unwrap(api.GET("/templates", { params: { query: { ...(category && { category }), ...(search && { search }) } } })),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

export function useTemplateCategories() {
  return useQuery({
    queryKey: agentKeys.templateCategories,
    queryFn: () => unwrap(api.GET("/templates/categories")) as Promise<{ items: TemplateCategoryCount[] }>,
    staleTime: 5 * 60_000,
  });
}

export function useTemplate(id: string | null) {
  return useQuery({
    queryKey: agentKeys.template(id ?? ""),
    queryFn: () => unwrap(api.GET("/templates/{template_id}", { params: { path: { template_id: id! } } })) as Promise<TemplateDetail>,
    enabled: !!id,
    staleTime: 5 * 60_000,
  });
}

export function useAgentVersions(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: agentKeys.versions(id ?? ""),
    queryFn: () =>
      unwrap(
        api.GET("/agents/{agent_id}/versions", { params: { path: { agent_id: id! }, query: { page: 1, page_size: 100 } } }),
      ) as Promise<VersionPage>,
    enabled: enabled && !!id,
  });
}

export function useVersionDiff(id: string, vid: string | null, against: string | null) {
  return useQuery({
    queryKey: agentKeys.diff(id, vid ?? "", against ?? ""),
    queryFn: () =>
      unwrap(
        api.GET("/agents/{agent_id}/versions/{version_id}/diff", {
          params: { path: { agent_id: id, version_id: vid! }, query: { against: against! } },
        }),
      ) as Promise<VersionDiff>,
    enabled: !!vid && !!against,
  });
}

export function useVersionDetail(id: string, vid: string | null) {
  return useQuery({
    queryKey: agentKeys.version(id, vid ?? ""),
    queryFn: () =>
      unwrap(api.GET("/agents/{agent_id}/versions/{version_id}", { params: { path: { agent_id: id, version_id: vid! } } })) as Promise<VersionDetail>,
    enabled: !!vid,
    staleTime: Infinity,
  });
}

/**
 * The contract types free-form config objects (`{type: object}` on create and validate) as an
 * empty record; this hands a typed AgentConfig (or a partial one) to those bodies.
 */
export const looseConfig = (c: unknown) => c as Record<string, never>;

/** `If-Match` value for a draft revision (the ETag the server sends is the quoted revision). */
export const etag = (revision: number) => `"${revision}"`;

/** A fresh key per user action, so a double click or a retried request creates one record (FR-038). */
export function idempotencyKey(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  }
}
