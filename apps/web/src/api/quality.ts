/**
 * Quality and evaluations (spec 007): analysis variables, call analysis, the evaluator catalog,
 * per-agent check settings, evaluator runs, labels, the review queue and calibration. Types come
 * from specs/007-quality-evals/contracts; hooks are TanStack Query.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import { isApiError } from "./errors";
import type { components } from "./schema";

type S = components["schemas"];

export type VariableType = S["VariableType"];
export type AnalysisVariable = S["AnalysisVariable"];
export type AnalysisVariableInput = S["AnalysisVariableInput"];
export type CallAnalysis = S["CallAnalysis"];
export type AnalysisValue = NonNullable<CallAnalysis["values"]>[number];
export type Evaluator = S["Evaluator"];
export type SettingsField = S["SettingsField"];
export type AgentEvalSetting = S["AgentEvalSetting"];
export type EvaluatorRun = S["EvaluatorRun"];
export type ResultItem = S["ResultItem"];
export type CallEvaluations = S["CallEvaluations"];
export type Verdict = S["Verdict"];
export type Annotation = S["Annotation"];
export type CalibrationRow = S["CalibrationRow"];
export type QueueItem = S["QueueItem"];
export type PhraseCheckConfig = S["PhraseCheckConfig"];
export type JudgeQuestionConfig = S["JudgeQuestionConfig"];
export type CustomConfig = S["CustomConfig"];
export type CustomEvaluatorInput = S["CustomEvaluatorInput"];
export type CustomType = CustomEvaluatorInput["evaluator_type"];
export type ReviewStrategy = "random" | "failed" | "disagreement";
export type VersionScope = "current" | "all";
export interface JudgeModel {
  model_id: string;
  display_name: string;
  is_default: boolean;
}
export interface TrialResult {
  verdict: Verdict;
  score?: number | null;
  rationale: string;
  evidence?: { turn_indices?: number[]; quote?: string | null };
  charged_usd?: number | null;
}
export interface CalibrationSummary {
  annotated_calls: number;
  annotated_and_evaluated_calls: number;
  conflicting_label_calls: number;
  min_sample_for_signal: number;
}
export interface ReviewSummary {
  random: number;
  failed: number;
  disagreement: number;
}

export const qualityKeys = {
  all: ["quality"] as const,
  variables: (agentId: string) => ["quality", "variables", agentId] as const,
  analysis: (callId: string) => ["quality", "analysis", callId] as const,
  evaluators: (kind: string, agentType: string) => ["quality", "evaluators", kind, agentType] as const,
  evaluatorsAll: ["quality", "evaluators"] as const,
  judgeModels: ["quality", "judge-models"] as const,
  settings: (agentId: string) => ["quality", "eval-settings", agentId] as const,
  evaluations: (callId: string) => ["quality", "evaluations", callId] as const,
  annotations: (callId: string) => ["quality", "annotations", callId] as const,
  review: ["quality", "review"] as const,
  queue: (strategy: string, agentId: string) => ["quality", "review", "queue", strategy, agentId] as const,
  reviewSummary: (agentId: string) => ["quality", "review", "summary", agentId] as const,
  calibration: ["quality", "calibration"] as const,
  calibrationRows: (agentId: string, lookback: number, scope: string) => ["quality", "calibration", "rows", agentId, lookback, scope] as const,
  calibrationSummary: (agentId: string, lookback: number) => ["quality", "calibration", "summary", agentId, lookback] as const,
};

export const newIdempotencyKey = () => crypto.randomUUID();

/** Field message for a settings key from a 422, whether the server names it by JSON pointer
 * ("/overrides/sample_rate_pct") or by dotted field ("overrides.sample_rate_pct"). */
export function settingErrors(err: unknown): Record<string, string> {
  if (!isApiError(err)) return {};
  const out: Record<string, string> = {};
  for (const fe of (err.problem.errors ?? []) as { pointer?: string; field?: string; message: string }[]) {
    const raw = fe.field ?? fe.pointer ?? "";
    const key = raw.split(/[/.]/).filter(Boolean).pop() ?? "";
    out[key] ??= fe.message;
  }
  return out;
}

// Analysis variables (US1) -------------------------------------------------------------------

export function useAnalysisVariables(agentId: string | null) {
  return useQuery({
    queryKey: qualityKeys.variables(agentId ?? ""),
    queryFn: async () =>
      (await unwrap(api.GET("/agents/{agent_id}/analysis-variables", { params: { path: { agent_id: agentId! } } }))).items as AnalysisVariable[],
    enabled: Boolean(agentId),
  });
}

export function createVariable(agentId: string, body: AnalysisVariableInput) {
  return unwrap(api.POST("/agents/{agent_id}/analysis-variables", { params: { path: { agent_id: agentId } }, body }));
}

export function updateVariable(id: string, body: Partial<AnalysisVariableInput>) {
  return unwrap(api.PATCH("/analysis-variables/{variable_id}", { params: { path: { variable_id: id } }, body }));
}

export function deleteVariable(id: string) {
  return unwrap(api.DELETE("/analysis-variables/{variable_id}", { params: { path: { variable_id: id } } }));
}

export function reorderVariables(agentId: string, ids: string[]) {
  return unwrap(api.PUT("/agents/{agent_id}/analysis-variables/order", { params: { path: { agent_id: agentId } }, body: { variable_ids: ids } }));
}

export function useCallAnalysis(callId: string | null) {
  return useQuery({
    queryKey: qualityKeys.analysis(callId ?? ""),
    queryFn: () => unwrap(api.GET("/calls/{call_id}/analysis", { params: { path: { call_id: callId! } } })) as Promise<CallAnalysis>,
    enabled: Boolean(callId),
    retry: false,
    refetchInterval: (q) => (q.state.data?.status === "pending" || q.state.data?.status === "running" ? 3_000 : false),
  });
}

export function rerunAnalysis(callId: string) {
  return unwrap(
    api.POST("/calls/{call_id}/analysis/rerun", {
      params: { path: { call_id: callId }, header: { "Idempotency-Key": newIdempotencyKey() } },
    }),
  ) as Promise<CallAnalysis>;
}

// Catalog and settings (US2, US5) --------------------------------------------------------------

export function useEvaluators(opts: { kind?: "builtin" | "custom"; agentType?: "single_prompt" | "flow" } = {}) {
  return useQuery({
    queryKey: qualityKeys.evaluators(opts.kind ?? "", opts.agentType ?? ""),
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/evaluators", {
            params: { query: { ...(opts.kind && { kind: opts.kind }), ...(opts.agentType && { agent_type: opts.agentType }) } },
          }),
        )
      ).items as Evaluator[],
    staleTime: 30_000,
  });
}

export function useJudgeModels() {
  return useQuery({
    queryKey: qualityKeys.judgeModels,
    queryFn: async () => (await unwrap(api.GET("/evaluators/judge-models"))).items as JudgeModel[],
    staleTime: 5 * 60_000,
  });
}

export function useEvalSettings(agentId: string | null) {
  return useQuery({
    queryKey: qualityKeys.settings(agentId ?? ""),
    queryFn: async () =>
      (await unwrap(api.GET("/agents/{agent_id}/eval-settings", { params: { path: { agent_id: agentId! } } }))).items as AgentEvalSetting[],
    enabled: Boolean(agentId),
  });
}

export interface EvalSettingBody {
  enabled: boolean;
  overrides: Record<string, unknown>;
  is_headline: boolean;
}

export function putEvalSetting(agentId: string, evaluatorId: string, body: EvalSettingBody) {
  return unwrap(
    api.PUT("/agents/{agent_id}/eval-settings/{evaluator_id}", { params: { path: { agent_id: agentId, evaluator_id: evaluatorId } }, body }),
  ) as Promise<AgentEvalSetting>;
}

export function createCustomEvaluator(body: CustomEvaluatorInput) {
  return unwrap(api.POST("/evaluators", { body })) as Promise<Evaluator>;
}

export function updateCustomEvaluator(id: string, body: { display_name?: string; description?: string | null; config?: CustomConfig }) {
  return unwrap(api.PATCH("/evaluators/{evaluator_id}", { params: { path: { evaluator_id: id } }, body })) as Promise<Evaluator>;
}

export function deleteCustomEvaluator(id: string) {
  return unwrap(api.DELETE("/evaluators/{evaluator_id}", { params: { path: { evaluator_id: id } } }));
}

export function trialCustomEvaluator(body: { evaluator_type: CustomType; config: CustomConfig; call_id: string }, key: string) {
  return unwrap(api.POST("/evaluators/trial", { params: { header: { "Idempotency-Key": key } }, body })) as Promise<TrialResult>;
}

// Runs (US2) ----------------------------------------------------------------------------------

export const EVAL_POLL_MS = 3_000;

export function useCallEvaluations(callId: string | null) {
  return useQuery({
    queryKey: qualityKeys.evaluations(callId ?? ""),
    queryFn: () =>
      unwrap(
        api.GET("/calls/{call_id}/evaluations", { params: { path: { call_id: callId! }, query: { include_history: true } } }),
      ) as Promise<CallEvaluations>,
    enabled: Boolean(callId),
    retry: false,
    // Results fill in without a reload while any run is still going (US2 scenario 5).
    refetchInterval: (q) => (q.state.data?.eval_status === "running" ? EVAL_POLL_MS : false),
  });
}

export function rerunEvaluations(callId: string, key: string, evaluatorIds?: string[]) {
  return unwrap(
    api.POST("/calls/{call_id}/evaluations/rerun", {
      params: { path: { call_id: callId }, header: { "Idempotency-Key": key } },
      body: evaluatorIds ? { evaluator_ids: evaluatorIds } : {},
    }),
  );
}

// Labels (US3) --------------------------------------------------------------------------------

export function useAnnotations(callId: string | null) {
  return useQuery({
    queryKey: qualityKeys.annotations(callId ?? ""),
    queryFn: () =>
      unwrap(api.GET("/calls/{call_id}/annotations", { params: { path: { call_id: callId! } } })) as Promise<{
        mine: Annotation | null;
        items: Annotation[];
      }>,
    enabled: Boolean(callId),
  });
}

export function putMyAnnotation(callId: string, label: "good" | "bad", note: string | null) {
  return unwrap(api.PUT("/calls/{call_id}/annotations/me", { params: { path: { call_id: callId } }, body: { label, note } })) as Promise<Annotation>;
}

export function deleteMyAnnotation(callId: string) {
  return unwrap(api.DELETE("/calls/{call_id}/annotations/me", { params: { path: { call_id: callId } } }));
}

// Review queue (US6) --------------------------------------------------------------------------

export function useReviewQueue(strategy: ReviewStrategy, agentId: string | null) {
  return useQuery({
    queryKey: qualityKeys.queue(strategy, agentId ?? ""),
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/review/queue", { params: { query: { strategy, ...(agentId && { agent_id: agentId }) } } }),
        )
      ).items as QueueItem[],
    placeholderData: keepPreviousData,
  });
}

export function useReviewSummary(agentId: string | null) {
  return useQuery({
    queryKey: qualityKeys.reviewSummary(agentId ?? ""),
    queryFn: () =>
      unwrap(api.GET("/review/queue/summary", { params: { query: { ...(agentId && { agent_id: agentId }) } } })) as Promise<ReviewSummary>,
    placeholderData: keepPreviousData,
  });
}

// Calibration (US4) ---------------------------------------------------------------------------

export function useCalibrationRows(agentId: string | null, lookbackDays: number, scope: VersionScope) {
  return useQuery({
    queryKey: qualityKeys.calibrationRows(agentId ?? "", lookbackDays, scope),
    queryFn: () =>
      unwrap(
        api.GET("/calibration/evaluators", {
          params: { query: { lookback_days: lookbackDays, version_scope: scope, ...(agentId && { agent_id: agentId }) } },
        }),
      ) as Promise<{ min_sample_for_signal: number; items: CalibrationRow[] }>,
    placeholderData: keepPreviousData,
  });
}

export function useCalibrationSummary(agentId: string | null, lookbackDays: number) {
  return useQuery({
    queryKey: qualityKeys.calibrationSummary(agentId ?? "", lookbackDays),
    queryFn: () =>
      unwrap(
        api.GET("/calibration/summary", { params: { query: { lookback_days: lookbackDays, ...(agentId && { agent_id: agentId }) } } }),
      ) as Promise<CalibrationSummary>,
    placeholderData: keepPreviousData,
  });
}
