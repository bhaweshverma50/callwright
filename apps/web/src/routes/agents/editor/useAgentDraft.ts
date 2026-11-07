/**
 * Editor state for one agent (T039). Holds the draft config and name, validates every change
 * against the platform (`POST /agents/validate`, debounced) so inline errors use the same rules as
 * save (FR-040), shows a field's error once it has been left or a save was tried, and saves through
 * `POST /agents` (first save, with an Idempotency-Key) or `PUT /agents/{id}/draft` with If-Match.
 */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useRef, useState } from "react";
import { isApiError, problemAs } from "../../../api/errors";
import {
  agentChanged,
  type AgentConfig,
  type AgentDetail,
  agentKeys,
  type AgentType,
  type ConfigIssue,
  type ConfigValidationResult,
  createAgent,
  saveAgentDraft,
  validateAgentConfig,
} from "../../../api/agents";
import { useDebounced } from "../../../lib/useDebounced";
import { idempotencyKey } from "../../../lib/idempotency";
import { stable } from "../../../lib/stable";

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
    queryFn: () => validateAgentConfig(type, debouncedConfig, base.id),
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
        fresh = await validateAgentConfig(type, config, base.id);
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
      let saved: { detail: AgentDetail; created: boolean; versionNumber: number };
      try {
        if (base.id) {
          const out = await saveAgentDraft(base.id, base.revision, { config: cfg, name: name.trim(), ...(note?.trim() && { note: note.trim() }) });
          saved = { detail: out.agent, created: out.created, versionNumber: out.version.version_number };
        } else {
          const detail = await createAgent({ name: name.trim(), type, language: cfg.language, config: cfg }, createKey.current);
          saved = { detail, created: true, versionNumber: detail.draft_version.version_number };
        }
      } catch (error) {
        if (isApiError(error) && error.status === 412)
          return { status: "conflict", currentRevision: problemAs(error, "RevisionConflictProblem")?.current_revision ?? null };
        if (isApiError(error) && error.status === 422)
          return { status: "invalid", issues: (error.problem.errors ?? []).map((e) => ({ pointer: e.pointer, code: e.code, message: e.message })) };
        return { status: "error", error };
      }
      const { detail, created, versionNumber } = saved;
      createKey.current = idempotencyKey();
      resetTo(detail);
      agentChanged(qc, detail);
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
