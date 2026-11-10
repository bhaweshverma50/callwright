/**
 * Issues and auto-fix (spec 009): detection per agent, the issue list and detail, fix revisions,
 * validation attempts (control and treatment batches from 008), apply and dismiss. Detection and
 * running validations poll every 2 s until they finish.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, fetchAll, unwrap } from "./client";
import type { components } from "./schema";
import type { BodyOf, QueryOf, ResponseOf } from "./types";
import { operationExtensions, schemaLimits } from "../lib/contract.gen";

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
export type DismissRequest = BodyOf<"/issues/{issue_id}/dismiss", "post">;
export type DismissReason = DismissRequest["reason"];
type IssueQuery = QueryOf<"/issues", "get">;
export type IssueScope = NonNullable<IssueQuery["scope"]>;
export type StatusFilter = NonNullable<IssueQuery["status"]>;
export type WindowDays = NonNullable<IssueQuery["window_days"]>;
export type ValidationMode = NonNullable<ValidationRequest["mode"]>;
export type ApplyRequest = BodyOf<"/issues/{issue_id}/apply", "post">;
export type ApplyResult = ResponseOf<"/issues/{issue_id}/apply", "post">;

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

const VALIDATION = schemaLimits.ValidationRequest;
const range = (c: { minimum: number; maximum: number; default: number }) => ({ min: c.minimum, max: c.maximum, default: c.default });
/** Threshold ranges the API accepts (FR-015). */
export const THRESHOLDS = {
  min_improvement_pp: range(VALIDATION.min_improvement_pp),
  max_regression_pp: range(VALIDATION.max_regression_pp),
  min_sample: range(VALIDATION.min_sample),
};
/** Above this share of failed simulations a validation is inconclusive. */
export const MAX_FAILED_RUN_SHARE = operationExtensions["POST /issues/{issue_id}/validate"]["x-max-failed-run-share"];

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
  estimate: (id: string, mode: ValidationMode) => ["issues", "issue", id, "estimate", mode] as const,
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
      ),
    placeholderData: keepPreviousData,
  });
}

/** Every other issue of an agent (dismiss as duplicate). */
export function useAgentIssues(agentId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: issueKeys.agentIssues(agentId ?? ""),
    queryFn: () =>
      fetchAll((page) =>
        unwrap(api.GET("/issues", { params: { query: { agent_id: agentId!, status: "all", scope: "real_and_simulated", ...page } } })),
      ),
    enabled: Boolean(agentId) && enabled,
    staleTime: 30_000,
  });
}

export function useLatestDetection(agentId: string | null) {
  return useQuery({
    queryKey: issueKeys.detection(agentId ?? ""),
    queryFn: () => unwrap(api.GET("/issues/detection", { params: { query: { agent_id: agentId! } } })),
    enabled: Boolean(agentId),
    refetchInterval: (q) => (q.state.data?.status === "running" ? ISSUE_POLL_MS : false),
  });
}

export function useIssue(id: string | undefined) {
  return useQuery({
    queryKey: issueKeys.issue(id ?? ""),
    queryFn: () => unwrap(api.GET("/issues/{issue_id}", { params: { path: { issue_id: id! } } })),
    enabled: Boolean(id),
    retry: false,
    refetchInterval: (q) => (q.state.data?.status === "validating" ? ISSUE_POLL_MS : false),
  });
}

export function useIssueSamples(id: string | undefined, page: number) {
  return useQuery({
    queryKey: issueKeys.samples(id ?? "", page),
    queryFn: () =>
      unwrap(api.GET("/issues/{issue_id}/samples", { params: { path: { issue_id: id! }, query: { page, page_size: ISSUE_PAGE_SIZE } } })),
    enabled: Boolean(id),
    placeholderData: keepPreviousData,
  });
}

export function useIssueFixes(id: string | undefined) {
  return useQuery({
    queryKey: issueKeys.fixes(id ?? ""),
    queryFn: async () => (await unwrap(api.GET("/issues/{issue_id}/fixes", { params: { path: { issue_id: id! } } }))).items,
    enabled: Boolean(id),
  });
}

export function useIssueValidations(id: string | undefined, poll: boolean) {
  return useQuery({
    queryKey: issueKeys.validations(id ?? ""),
    queryFn: async () => (await unwrap(api.GET("/issues/{issue_id}/validations", { params: { path: { issue_id: id! } } }))).items,
    enabled: Boolean(id),
    refetchInterval: poll ? ISSUE_POLL_MS : false,
  });
}

const header = (key: string) => ({ "Idempotency-Key": key });

export function detectIssues(body: { agent_id: string; window_days: WindowDays; include_simulated: boolean }, key: string) {
  return unwrap(api.POST("/issues/detect", { params: { header: header(key) }, body }));
}

export function draftFixWithAi(issueId: string, body: { kind?: FixKind; guidance?: string | null }, key: string) {
  return unwrap(
    api.POST("/issues/{issue_id}/fixes", {
      params: { path: { issue_id: issueId }, header: header(key) },
      body: { mode: "ai", ...body },
    }),
  );
}

export function saveManualFix(issueId: string, kind: FixKind, payload: FixPayload) {
  return unwrap(api.POST("/issues/{issue_id}/fixes", { params: { path: { issue_id: issueId } }, body: { mode: "manual", kind, payload } }));
}

export type ValidationSettings = Pick<ValidationRequest, "mode" | "min_improvement_pp" | "max_regression_pp" | "min_sample">;

/** A dry run answers with the estimate (200); a real run with the started attempt (202). */
export async function estimateValidation(issueId: string, mode: ValidationMode, key: string): Promise<ValidationEstimate> {
  const body = await unwrap(
    api.POST("/issues/{issue_id}/validate", {
      params: { path: { issue_id: issueId }, header: header(key) },
      body: { dry_run: true, mode },
    }),
  );
  if (!("affected_calls" in body)) throw new Error("A dry run answered with a validation attempt.");
  return body;
}

export async function validateFix(issueId: string, settings: ValidationSettings, key: string): Promise<ValidationAttempt> {
  const body = await unwrap(
    api.POST("/issues/{issue_id}/validate", {
      params: { path: { issue_id: issueId }, header: header(key) },
      body: { dry_run: false, ...settings },
    }),
  );
  if ("affected_calls" in body) throw new Error("A validation answered with an estimate.");
  return body;
}

export function draftAndValidate(issueId: string, body: ValidationSettings & { kind?: FixKind; guidance?: string | null }, key: string) {
  return unwrap(
    api.POST("/issues/{issue_id}/draft-and-validate", {
      params: { path: { issue_id: issueId }, header: header(key) },
      body: { dry_run: false, ...body },
    }),
  );
}

export function cancelValidation(issueId: string) {
  return unwrap(api.POST("/issues/{issue_id}/validation/cancel", { params: { path: { issue_id: issueId } } }));
}

export function applyFix(issueId: string, body: ApplyRequest) {
  return unwrap(api.POST("/issues/{issue_id}/apply", { params: { path: { issue_id: issueId } }, body }));
}

export function dismissIssue(issueId: string, body: DismissRequest) {
  return unwrap(api.POST("/issues/{issue_id}/dismiss", { params: { path: { issue_id: issueId } }, body }));
}
