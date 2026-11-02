/**
 * Issues and auto-fix (spec 009): detection per agent, the issue list and detail, fix revisions,
 * validation attempts (control and treatment batches from 008), apply and dismiss. Detection and
 * running validations poll every 2 s until they finish.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import type { components } from "./schema";

type S = components["schemas"];

export type IssueStatus = S["IssueStatus"];
export type FixKind = S["FixKind"];
export type Detection = S["Detection"];
export type IssueSummary = S["IssueSummary"];
export type DetectedIssue = S["DetectedIssue"];
export type IssueSample = S["IssueSample"];
export type FixPayload = S["FixPayload"];
export type FixRevision = S["FixRevision"];
export type FixStatus = FixRevision["status"];
export type ValidationRequest = S["ValidationRequest"];
export type ValidationEstimate = S["ValidationEstimate"];
export type EvaluatorEvidence = S["EvaluatorEvidence"];
export type ValidationAttempt = S["ValidationAttempt"];
export type ValidationReason = NonNullable<ValidationAttempt["reasons"]>[number];
export type PostApply = S["PostApply"];
export type ApplyBlocker = NonNullable<DetectedIssue["apply_blockers"]>[number];
export type DismissReason = "not_a_problem" | "evaluator_wrong" | "wont_fix" | "duplicate" | "other";
export type IssueScope = "real" | "real_and_simulated";
export type StatusFilter = "all" | IssueStatus;
export type WindowDays = 7 | 14 | 30 | 90;

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface ApplyResult {
  issue: DetectedIssue;
  agent_version_id: string;
  published: boolean;
  release_notes?: string;
  tool_copies: { original_tool_id?: string; copy_tool_id?: string }[];
  draft_updated?: boolean;
}

export interface IssueFilters {
  agentId: string | null;
  status: StatusFilter;
  scope: IssueScope;
  windowDays: WindowDays;
  page: number;
}

export const ISSUE_PAGE_SIZE = 20;
export const ISSUE_POLL_MS = 2_000;
export const WINDOWS: WindowDays[] = [7, 14, 30, 90];
export const DEFAULT_WINDOW: WindowDays = 14;

/** Threshold ranges the API accepts (FR-015). */
export const THRESHOLDS = {
  min_improvement_pp: { min: 5, max: 50, default: 10 },
  max_regression_pp: { min: 0, max: 20, default: 5 },
  min_sample: { min: 3, max: 50, default: 5 },
} as const;

export const issueKeys = {
  all: ["issues"] as const,
  list: (f: IssueFilters) => ["issues", "list", f] as const,
  lists: ["issues", "list"] as const,
  detection: (agentId: string) => ["issues", "detection", agentId] as const,
  issue: (id: string) => ["issues", "issue", id] as const,
  samples: (id: string, page: number) => ["issues", "issue", id, "samples", page] as const,
  fixes: (id: string) => ["issues", "issue", id, "fixes"] as const,
  validations: (id: string) => ["issues", "issue", id, "validations"] as const,
  agentIssues: (agentId: string) => ["issues", "agent", agentId] as const,
};

export function useIssues(f: IssueFilters) {
  return useQuery({
    queryKey: issueKeys.list(f),
    queryFn: () =>
      unwrap(
        api.GET("/issues", {
          params: {
            query: {
              status: f.status,
              scope: f.scope,
              window_days: f.windowDays,
              page: f.page,
              page_size: ISSUE_PAGE_SIZE,
              ...(f.agentId && { agent_id: f.agentId }),
            },
          },
        }),
      ) as Promise<Paged<IssueSummary>>,
    placeholderData: keepPreviousData,
  });
}

/** Every other issue of an agent (dismiss as duplicate). */
export function useAgentIssues(agentId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: issueKeys.agentIssues(agentId ?? ""),
    queryFn: async () =>
      (
        (await unwrap(
          api.GET("/issues", { params: { query: { agent_id: agentId!, status: "all", scope: "real_and_simulated", page: 1, page_size: 100 } } }),
        )) as Paged<IssueSummary>
      ).items,
    enabled: Boolean(agentId) && enabled,
    staleTime: 30_000,
  });
}

export function useLatestDetection(agentId: string | null) {
  return useQuery({
    queryKey: issueKeys.detection(agentId ?? ""),
    queryFn: () => unwrap(api.GET("/issues/detection", { params: { query: { agent_id: agentId! } } })) as Promise<Detection | null>,
    enabled: Boolean(agentId),
    refetchInterval: (q) => (q.state.data?.status === "running" ? ISSUE_POLL_MS : false),
  });
}

export function useIssue(id: string | undefined) {
  return useQuery({
    queryKey: issueKeys.issue(id ?? ""),
    queryFn: () => unwrap(api.GET("/issues/{issue_id}", { params: { path: { issue_id: id! } } })) as Promise<DetectedIssue>,
    enabled: Boolean(id),
    retry: false,
    refetchInterval: (q) => (q.state.data?.status === "validating" ? ISSUE_POLL_MS : false),
  });
}

export function useIssueSamples(id: string | undefined, page: number) {
  return useQuery({
    queryKey: issueKeys.samples(id ?? "", page),
    queryFn: () =>
      unwrap(api.GET("/issues/{issue_id}/samples", { params: { path: { issue_id: id! }, query: { page, page_size: ISSUE_PAGE_SIZE } } })) as Promise<
        Paged<IssueSample>
      >,
    enabled: Boolean(id),
    placeholderData: keepPreviousData,
  });
}

export function useIssueFixes(id: string | undefined) {
  return useQuery({
    queryKey: issueKeys.fixes(id ?? ""),
    queryFn: async () =>
      ((await unwrap(api.GET("/issues/{issue_id}/fixes", { params: { path: { issue_id: id! } } }))) as { items: FixRevision[] }).items,
    enabled: Boolean(id),
  });
}

export function useIssueValidations(id: string | undefined, poll: boolean) {
  return useQuery({
    queryKey: issueKeys.validations(id ?? ""),
    queryFn: async () =>
      ((await unwrap(api.GET("/issues/{issue_id}/validations", { params: { path: { issue_id: id! } } }))) as { items: ValidationAttempt[] }).items,
    enabled: Boolean(id),
    refetchInterval: poll ? ISSUE_POLL_MS : false,
  });
}

const header = (key: string) => ({ "Idempotency-Key": key });

export function detectIssues(body: { agent_id: string; window_days: WindowDays; include_simulated: boolean }, key: string) {
  return unwrap(api.POST("/issues/detect", { params: { header: header(key) }, body })) as Promise<Detection>;
}

export function draftFixWithAi(issueId: string, body: { kind?: FixKind; guidance?: string | null }, key: string) {
  return unwrap(
    api.POST("/issues/{issue_id}/fixes", {
      params: { path: { issue_id: issueId }, header: header(key) },
      body: { mode: "ai", ...body },
    }),
  ) as Promise<FixRevision>;
}

export function saveManualFix(issueId: string, kind: FixKind, payload: FixPayload) {
  return unwrap(
    api.POST("/issues/{issue_id}/fixes", { params: { path: { issue_id: issueId } }, body: { mode: "manual", kind, payload } }),
  ) as Promise<FixRevision>;
}

export type ValidationSettings = Pick<ValidationRequest, "mode" | "min_improvement_pp" | "max_regression_pp" | "min_sample">;

export function estimateValidation(issueId: string, mode: ValidationRequest["mode"], key: string) {
  return unwrap(
    api.POST("/issues/{issue_id}/validate", {
      params: { path: { issue_id: issueId }, header: header(key) },
      body: { dry_run: true, mode } as ValidationRequest,
    }),
  ) as Promise<ValidationEstimate>;
}

export function validateFix(issueId: string, settings: ValidationSettings, key: string) {
  return unwrap(
    api.POST("/issues/{issue_id}/validate", {
      params: { path: { issue_id: issueId }, header: header(key) },
      body: { dry_run: false, ...settings } as ValidationRequest,
    }),
  ) as Promise<ValidationAttempt>;
}

export function draftAndValidate(issueId: string, body: ValidationSettings & { kind?: FixKind; guidance?: string | null }, key: string) {
  return unwrap(
    api.POST("/issues/{issue_id}/draft-and-validate", {
      params: { path: { issue_id: issueId }, header: header(key) },
      body: { dry_run: false, ...body } as ValidationRequest,
    }),
  ) as Promise<{ fix: FixRevision; validation: ValidationAttempt }>;
}

export function cancelValidation(issueId: string) {
  return unwrap(api.POST("/issues/{issue_id}/validation/cancel", { params: { path: { issue_id: issueId } } })) as Promise<DetectedIssue>;
}

export function applyFix(issueId: string, body: { fix_revision?: number; publish: boolean; release_notes_extra?: string | null }) {
  return unwrap(api.POST("/issues/{issue_id}/apply", { params: { path: { issue_id: issueId } }, body })) as Promise<ApplyResult>;
}

export function dismissIssue(issueId: string, body: { reason: DismissReason; note?: string | null; duplicate_of?: string }) {
  return unwrap(
    api.POST("/issues/{issue_id}/dismiss", {
      params: { path: { issue_id: issueId } },
      body: body as { reason: DismissReason; note?: string | null; duplicate_of?: string },
    }),
  ) as Promise<DetectedIssue>;
}
