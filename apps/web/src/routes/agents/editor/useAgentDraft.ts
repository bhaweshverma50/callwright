/**
 * Editor state for one agent (T039). Holds the draft config and name, validates every change
 * against the platform (`POST /agents/validate`, debounced) so inline errors use the same rules as
 * save (FR-040), shows a field's error once it has been left or a save was tried, and saves through
 * `POST /agents` (first save, with an Idempotency-Key) or `PUT /agents/{id}/draft` with If-Match.
 */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useRef, useState } from "react";
import { api } from "../../../api/client";
import { ApiError } from "../../../api/errors";
import { toProblem } from "../../../api/errors";
import {
  type AgentConfig,
  type AgentDetail,
  agentKeys,
  type AgentType,
  type ConfigIssue,
  type ConfigValidationResult,
  etag,
  idempotencyKey,
  type SaveResult,
} from "../../../api/agents";
import { useDebounced } from "../../../lib/useDebounced";

export interface DraftBase {
  id: string | null;
  name: string;
  config: AgentConfig;
  revision: number;
  detail: AgentDetail | null;
}

export type SaveOutcome =
  | { status: "saved"; detail: AgentDetail; created: boolean; versionNumber: number }
  | { status: "invalid"; issues: ConfigIssue[] }
  | { status: "conflict"; currentRevision: number | null }
  | { status: "error"; error: unknown };

const NAME_MAX = 80;

export function nameProblem(name: string): string | null {
  if (!name.trim()) return "Give the agent a name.";
  if (name.trim().length > NAME_MAX) return `Keep the name to ${NAME_MAX} characters or fewer.`;
  return null;
}

/** JSON with sorted keys, so two configs with the same content compare equal. */
export function stable(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(stable).join(",")}]`;
  if (v && typeof v === "object")
    return `{${Object.keys(v)
      .sort()
      .filter((k) => (v as Record<string, unknown>)[k] !== undefined)
      .map((k) => `${JSON.stringify(k)}:${stable((v as Record<string, unknown>)[k])}`)
      .join(",")}}`;
  return JSON.stringify(v ?? null);
}

async function validate(type: AgentType, config: AgentConfig, agentId: string | null): Promise<ConfigValidationResult> {
  const { data, error, response } = await api.POST("/agents/validate", {
    body: { type, config: config, ...(agentId && { agent_id: agentId }) },
  });
  if (!response.ok) throw new ApiError(response.status, toProblem(response.status, error));
  return data as ConfigValidationResult;
}

export function useAgentDraft(initial: DraftBase, type: AgentType) {
  const qc = useQueryClient();
  const [base, setBase] = useState(initial);
  const [name, setName] = useState(initial.name);
  const [config, setConfig] = useState<AgentConfig>(initial.config);
  const [touched, setTouched] = useState<Set<string>>(() => new Set());
  const [submitted, setSubmitted] = useState(false);
  const [local, setLocal] = useState<Record<string, string>>({});
  const createKey = useRef(idempotencyKey());

  const configKey = useMemo(() => stable(config), [config]);
  const debouncedKey = useDebounced(configKey, 250);
  const debouncedConfig = useMemo(() => JSON.parse(debouncedKey) as AgentConfig, [debouncedKey]);

  const validation = useQuery({
    queryKey: agentKeys.validate(type, base.id, debouncedKey),
    queryFn: () => validate(type, debouncedConfig, base.id),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
  const checking = validation.isFetching || debouncedKey !== configKey;

  const serverErrors = useMemo(() => {
    const m = new Map<string, string>();
    for (const e of validation.data?.errors ?? []) if (!m.has(e.pointer)) m.set(e.pointer, e.message);
    return m;
  }, [validation.data]);

  const nameError = nameProblem(name);
  const dirty = name !== base.name || configKey !== stable(base.config);

  /** Every known blocking problem: name, unparseable inputs, then the platform's errors. */
  const issues: ConfigIssue[] = useMemo(() => {
    const out: ConfigIssue[] = [];
    if (nameError) out.push({ pointer: "/name", code: "required", message: nameError });
    for (const [pointer, message] of Object.entries(local)) out.push({ pointer, code: "invalid_format", message });
    for (const [pointer, message] of serverErrors) if (!local[pointer]) out.push({ pointer, code: "invalid", message });
    return out;
  }, [nameError, local, serverErrors]);

  const errorFor = useCallback(
    (pointer: string): string | null => {
      if (!submitted && !touched.has(pointer)) return null;
      if (pointer === "/name") return nameError;
      return local[pointer] ?? serverErrors.get(pointer) ?? null;
    },
    [submitted, touched, nameError, local, serverErrors],
  );

  const touch = useCallback((pointer: string) => {
    setTouched((t) => (t.has(pointer) ? t : new Set(t).add(pointer)));
  }, []);

  const setLocalError = useCallback((pointer: string, message: string | null) => {
    setLocal((l) => {
      if ((l[pointer] ?? null) === message) return l;
      const next = { ...l };
      if (message) next[pointer] = message;
      else delete next[pointer];
      return next;
    });
  }, []);

  const update = useCallback((mutate: (draft: AgentConfig) => void) => {
    setConfig((c) => {
      const next = structuredClone(c);
      mutate(next);
      return next;
    });
  }, []);

  /** Replaces the editor with a saved agent (after save, restore or reload). */
  const resetTo = useCallback((detail: AgentDetail) => {
    const next: DraftBase = { id: detail.id, name: detail.name, config: detail.draft_config, revision: detail.draft_revision, detail };
    setBase(next);
    setName(detail.name);
    setConfig(detail.draft_config);
    setTouched(new Set());
    setSubmitted(false);
    setLocal({});
  }, []);

  const discard = useCallback(() => {
    setName(base.name);
    setConfig(base.config);
    setTouched(new Set());
    setSubmitted(false);
    setLocal({});
  }, [base]);

  const save = useCallback(
    async (note?: string): Promise<SaveOutcome> => {
      setSubmitted(true);
      let fresh: ConfigValidationResult;
      try {
        fresh = await validate(type, config, base.id);
      } catch (error) {
        return { status: "error", error };
      }
      const all: ConfigIssue[] = [];
      if (nameError) all.push({ pointer: "/name", code: "required", message: nameError });
      for (const [pointer, message] of Object.entries(local)) all.push({ pointer, code: "invalid_format", message });
      for (const e of fresh.errors) if (!local[e.pointer]) all.push(e);
      qc.setQueryData(agentKeys.validate(type, base.id, configKey), fresh);
      if (all.length) return { status: "invalid", issues: all };

      const cfg = fresh.normalized_config;
      let res: Awaited<ReturnType<typeof api.POST>> | Awaited<ReturnType<typeof api.PUT>>;
      try {
        res = base.id
          ? await api.PUT("/agents/{agent_id}/draft", {
              params: { path: { agent_id: base.id }, header: { "If-Match": etag(base.revision) } },
              body: { config: cfg, name: name.trim(), ...(note?.trim() && { note: note.trim() }) },
            })
          : await api.POST("/agents", {
              params: { header: { "Idempotency-Key": createKey.current } },
              body: { name: name.trim(), type, language: cfg.language, config: cfg },
            });
      } catch (error) {
        return { status: "error", error };
      }
      const { response, data, error } = res as { response: Response; data?: unknown; error?: unknown };
      if (response.status === 412) {
        const p = error as { current_revision?: number } | undefined;
        return { status: "conflict", currentRevision: p?.current_revision ?? null };
      }
      if (response.status === 422) {
        const problem = toProblem(422, error);
        return { status: "invalid", issues: (problem.errors ?? []).map((e) => ({ pointer: e.pointer, code: e.code, message: e.message })) };
      }
      if (!response.ok) return { status: "error", error: new ApiError(response.status, toProblem(response.status, error)) };

      const detail = base.id ? (data as SaveResult).agent : (data as AgentDetail);
      const created = base.id ? (data as SaveResult).created : true;
      const versionNumber = base.id ? (data as SaveResult).version.version_number : detail.draft_version.version_number;
      createKey.current = idempotencyKey();
      resetTo(detail);
      qc.setQueryData(agentKeys.detail(detail.id), detail);
      void qc.invalidateQueries({ queryKey: agentKeys.lists });
      void qc.invalidateQueries({ queryKey: agentKeys.versions(detail.id) });
      return { status: "saved", detail, created, versionNumber };
    },
    [type, config, base, name, nameError, local, qc, configKey, resetTo],
  );

  return {
    base,
    name,
    setName,
    config,
    update,
    dirty,
    checking,
    validation: validation.data,
    issues,
    errorFor,
    touch,
    submitted,
    setLocalError,
    save,
    discard,
    resetTo,
  };
}

export type AgentDraft = ReturnType<typeof useAgentDraft>;
