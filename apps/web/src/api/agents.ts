/**
 * Types and TanStack Query hooks for spec 002 (agents, versions, templates, catalogs, prompt
 * assistant), typed from the generated contract (schema.d.ts).
 */
import { keepPreviousData, useQuery, type QueryClient } from "@tanstack/react-query";
import { api, fetchAll, postForm, unwrap } from "./client";
import type { components } from "./schema";
import type { BodyOf, QueryOf, ResponseOf } from "./types";

type S = components["schemas"];

export type AgentType = S["AgentType"];
export type AgentConfig = S["AgentConfig"];
export type RecordingMode = AgentConfig["advanced"]["recording"];
export type DynamicVariable = S["DynamicVariable"];
export type PronunciationEntry = S["PronunciationEntry"];
export type ModelRef = S["ModelRef"];
export type BackgroundAudioSource = S["BackgroundAudioSource"];
export type ConfigIssue = S["ConfigIssue"];
export type ConfigValidationResult = S["ConfigValidationResult"];
export type VersionRef = S["VersionRef"];
export type AgentSummary = S["AgentSummary"];
export type AgentDetail = S["AgentDetail"];
export type SaveResult = S["SaveResult"];
export type AgentStatus = NonNullable<QueryOf<"/agents", "get">["status"]>;
export type AgentSort = NonNullable<QueryOf<"/agents", "get">["sort"]>;
export type AgentPage = ResponseOf<"/agents", "get">;

export type VersionSource = S["VersionSource"];
export type VersionSummary = S["VersionSummary"];
export type VersionDetail = S["VersionDetail"];
export type VersionChange = S["Change"];
export type VersionPage = ResponseOf<"/agents/{agent_id}/versions", "get">;

export type TemplateCategory = S["TemplateCategory"];
export type TemplateSummary = S["TemplateSummary"];
export type TemplateDetail = S["TemplateDetail"];
export type TemplateConfig = S["TemplateConfig"];

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
export type AmbientAudioFile = S["AmbientAudioFile"];

export type PromptAiRequest = BodyOf<"/prompt-ai/generate", "post">;
export type PromptAiResponse = ResponseOf<"/prompt-ai/generate", "post">;
export type PromptProposal = NonNullable<PromptAiResponse["proposal"]>;

export type VoiceFilters = Pick<QueryOf<"/voices/{provider}/voices", "get">, "search" | "gender" | "language" | "model">;

export const agentKeys = {
  all: ["agents"] as const,
  lists: ["agents", "list"] as const,
  list: (search: string, type: AgentType | null, page: number, status: AgentStatus | null = null, sort: AgentSort = "updated") =>
    ["agents", "list", { search, type, page, status, sort }] as const,
  /** Every agent (pickers and filters); agentChanged and agentDeleted refresh it with the lists. */
  every: ["agents", "every"] as const,
  validate: (type: AgentType, id: string | null, configKey: string) => ["agents", "validate", type, id, configKey] as const,
  detail: (id: string) => ["agents", "detail", id] as const,
  defaults: (language: string) => ["agents", "defaults", language] as const,
  versions: (id: string) => ["agents", "versions", id] as const,
  version: (id: string, vid: string) => ["agents", "versions", id, vid] as const,
  diff: (id: string, vid: string, against: string) => ["agents", "diff", id, vid, against] as const,
  llms: ["llms", "catalog"] as const,
  voices: ["voices", "catalog"] as const,
  providerVoices: (provider: string, f: VoiceFilters) => ["voices", "list", provider, f] as const,
  browseVoices: (provider: string, f: VoiceFilters) => ["voices", "browse", provider, f] as const,
  ambient: ["voices", "ambient"] as const,
  templates: (category: TemplateCategory | null, search: string) => ["templates", "list", { category, search }] as const,
  templateCategories: ["templates", "categories"] as const,
  template: (id: string) => ["templates", "detail", id] as const,
};

export const PAGE_SIZE = 24;

export function useAgents(
  search: string,
  type: AgentType | null,
  page: number,
  { status = null, sort = "updated", enabled = true }: { status?: AgentStatus | null; sort?: AgentSort; enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: agentKeys.list(search, type, page, status, sort),
    queryFn: () =>
      unwrap(
        api.GET("/agents", {
          params: { query: { page, page_size: PAGE_SIZE, sort, ...(search && { search }), ...(type && { type }), ...(status && { status }) } },
        }),
      ),
    placeholderData: keepPreviousData,
    enabled,
  });
}

/** Every agent in the workspace, for pickers and filters (all pages). */
export function useAllAgents(enabled = true) {
  return useQuery({
    queryKey: agentKeys.every,
    queryFn: () => fetchAll((query) => unwrap(api.GET("/agents", { params: { query } }))),
    enabled,
    staleTime: 60_000,
  });
}

export function useAgent(id: string | undefined) {
  return useQuery({
    queryKey: agentKeys.detail(id ?? ""),
    queryFn: () => unwrap(api.GET("/agents/{agent_id}", { params: { path: { agent_id: id! } } })),
    enabled: !!id,
    staleTime: 0,
    refetchOnWindowFocus: false,
  });
}

export function useAgentDefaults(language: string, enabled = true) {
  return useQuery({
    queryKey: agentKeys.defaults(language),
    queryFn: () => unwrap(api.GET("/agents/defaults", { params: { query: { type: "single_prompt", language } } })),
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
  );
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
    queryFn: () => unwrap(api.GET("/templates/categories")),
    staleTime: 5 * 60_000,
  });
}

export function useTemplate(id: string | null) {
  return useQuery({
    queryKey: agentKeys.template(id ?? ""),
    queryFn: () => unwrap(api.GET("/templates/{template_id}", { params: { path: { template_id: id! } } })),
    enabled: !!id,
    staleTime: 5 * 60_000,
  });
}

export function useAgentVersions(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: agentKeys.versions(id ?? ""),
    queryFn: async () => ({
      items: await fetchAll((query) => unwrap(api.GET("/agents/{agent_id}/versions", { params: { path: { agent_id: id! }, query } }))),
    }),
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
      ),
    enabled: !!vid && !!against,
  });
}

export function useVersionDetail(id: string, vid: string | null) {
  return useQuery({
    queryKey: agentKeys.version(id, vid ?? ""),
    queryFn: () => unwrap(api.GET("/agents/{agent_id}/versions/{version_id}", { params: { path: { agent_id: id, version_id: vid! } } })),
    enabled: !!vid,
    staleTime: Infinity,
  });
}

/** `If-Match` value for a draft revision (the ETag the server sends is the quoted revision). */
export const etag = (revision: number) => `"${revision}"`;

/** An agent was created, saved, restored or (un)published: cache what came back and refresh lists. */
export function agentChanged(qc: QueryClient, agent: AgentDetail | string) {
  const id = typeof agent === "string" ? agent : agent.id;
  if (typeof agent === "string") void qc.invalidateQueries({ queryKey: agentKeys.detail(id) });
  else qc.setQueryData(agentKeys.detail(id), agent);
  void qc.invalidateQueries({ queryKey: agentKeys.versions(id) });
  void qc.invalidateQueries({ queryKey: agentKeys.lists });
  void qc.invalidateQueries({ queryKey: agentKeys.every });
}

/** An agent was deleted: drop it from every cached list page at once, then refresh the lists. */
export function agentDeleted(qc: QueryClient, id: string) {
  qc.setQueriesData<AgentPage>({ queryKey: agentKeys.lists }, (old) =>
    old ? { ...old, items: old.items.filter((x) => x.id !== id), total: Math.max(0, old.total - 1) } : old,
  );
  qc.removeQueries({ queryKey: agentKeys.detail(id) });
  void qc.invalidateQueries({ queryKey: agentKeys.lists });
  void qc.invalidateQueries({ queryKey: agentKeys.every });
}

/** Creates a single-prompt agent from a template and caches it. */
export async function createAgentFromTemplate(qc: QueryClient, t: TemplateDetail, key: string): Promise<AgentDetail> {
  const agent = await unwrap(
    api.POST("/agents", {
      params: { header: { "Idempotency-Key": key } },
      body: { name: t.config.agent_name ?? t.name, type: "single_prompt", template_id: t.id, language: t.config.language },
    }),
  );
  agentChanged(qc, agent);
  return agent;
}

/** First save of a new agent (FR-038: one key per editor session, so a retry creates one agent). */
export function createAgent(body: BodyOf<"/agents", "post">, key: string) {
  return unwrap(api.POST("/agents", { params: { header: { "Idempotency-Key": key } }, body }));
}

/** Saves the draft against the revision it was loaded at (412 RevisionConflictProblem when stale). */
export function saveAgentDraft(agentId: string, revision: number, body: BodyOf<"/agents/{agent_id}/draft", "put">) {
  return unwrap(api.PUT("/agents/{agent_id}/draft", { params: { path: { agent_id: agentId }, header: { "If-Match": etag(revision) } }, body }));
}

/** Checks a config with the same rules as save (FR-040). */
export function validateAgentConfig(type: AgentType, config: AgentConfig, agentId: string | null) {
  return unwrap(api.POST("/agents/validate", { body: { type, config, ...(agentId && { agent_id: agentId }) } }));
}

/** Deletes an agent. A 409 `agent_in_use` lists the channels it is attached to. */
export async function deleteAgent(agentId: string) {
  await unwrap(api.DELETE("/agents/{agent_id}", { params: { path: { agent_id: agentId } } }));
}

export function duplicateAgent(agentId: string, key: string, body: BodyOf<"/agents/{agent_id}/duplicate", "post">) {
  return unwrap(api.POST("/agents/{agent_id}/duplicate", { params: { path: { agent_id: agentId }, header: { "Idempotency-Key": key } }, body }));
}

export async function publishVersion(agentId: string, versionId: string) {
  await unwrap(api.PUT("/agents/{agent_id}/published-version", { params: { path: { agent_id: agentId } }, body: { version_id: versionId } }));
}

export async function unpublishAgent(agentId: string) {
  await unwrap(api.DELETE("/agents/{agent_id}/published-version", { params: { path: { agent_id: agentId } } }));
}

/** Copies an old version into a new draft version (optionally publishing it). */
export function restoreVersion(agentId: string, versionId: string, revision: number, publish: boolean) {
  return unwrap(
    api.POST("/agents/{agent_id}/versions/{version_id}/restore", {
      params: { path: { agent_id: agentId, version_id: versionId }, header: { "If-Match": etag(revision) } },
      body: { publish },
    }),
  );
}

/** One prompt assistant turn (paid: a fresh key per turn). */
export function generatePrompt(body: PromptAiRequest, key: string) {
  return unwrap(api.POST("/prompt-ai/generate", { params: { header: { "Idempotency-Key": key } }, body }));
}

export async function deleteAmbientAudio(key: string) {
  await unwrap(api.DELETE("/voices/ambient-audio", { params: { query: { key } } }));
}

/**
 * The most recently updated agent for the guided tour, preferring a single-prompt agent (the tour's
 * agent steps edit a prompt); null when the workspace has none.
 */
export async function newestAgentId(): Promise<string | null> {
  const newest = (type?: AgentType) =>
    unwrap(api.GET("/agents", { params: { query: { page: 1, page_size: 1, sort: "updated", ...(type && { type }) } } }));
  return (await newest("single_prompt")).items[0]?.id ?? (await newest()).items[0]?.id ?? null;
}

/** The first template in the gallery, with its full config. */
export async function firstTemplate(): Promise<TemplateDetail | null> {
  const first = (await unwrap(api.GET("/templates"))).items[0];
  return first ? unwrap(api.GET("/templates/{template_id}", { params: { path: { template_id: first.id } } })) : null;
}

export function uploadAmbientAudio(file: File) {
  const form = new FormData();
  form.append("file", file);
  return postForm("/voices/ambient-audio", form);
}
