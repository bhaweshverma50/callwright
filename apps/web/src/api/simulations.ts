/**
 * Simulations (spec 008 US2 to US4): pre-flight, individual runs (srun_), batches (exp_), the
 * per-run comparison and the batch scorecard. Lists poll every 3 s only while something they show
 * is pending or running.
 */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { api, fetchAll, unwrap } from "./client";
import type { components } from "./schema";
import type { BodyOf, ResponseOf } from "./types";

type S = components["schemas"];

export type SimMode = S["SimMode"];
export type SimStatus = S["SimStatus"];
export type SimEndReason = S["SimEndReason"];
export type SimTarget = S["SimTarget"];
export type SimSettings = S["SimSettings"];
export type PersonaBrief = S["PersonaBrief"];
export type AnswerSource = S["SimTranscriptItem"]["answer_source"] & string;
export type AnswerSourceCounts = S["AnswerSourceCounts"];
export type InvalidCall = S["InvalidCall"];
export type SimulationRun = S["SimulationRun"];
export type Experiment = S["Experiment"];
export type SimTranscriptItem = S["SimTranscriptItem"];
export type ConversationSide = S["ConversationSide"];
export type VerdictDiff = S["VerdictDiff"];
export type Comparison = S["Comparison"];
export type PairCounts = S["PairCounts"];
export type ScorecardRow = S["ScorecardRow"];
export type Scorecard = S["Scorecard"];
export type TargetType = SimTarget["type"];
export type ExperimentSource = Experiment["source"];
export type PreflightRequest = BodyOf<"/simulations/preflight", "post">;
export type Preflight = ResponseOf<"/simulations/preflight", "post">;

export const SIM_POLL_MS = 3_000;
export const SIM_PAGE_SIZE = 20;
export const BATCH_MIN = 2;
export const BATCH_MAX = 100;

export const simKeys = {
  all: ["simulations"] as const,
  experiments: (agentId: string, page: number) => ["simulations", "experiments", { agentId, page }] as const,
  experimentsAll: ["simulations", "experiments"] as const,
  experiment: (id: string) => ["simulations", "experiment", id] as const,
  experimentRuns: (id: string, page: number) => ["simulations", "experiment", id, "runs", page] as const,
  scorecard: (id: string, baseline: string) => ["simulations", "experiment", id, "scorecard", baseline] as const,
  runs: (agentId: string, page: number) => ["simulations", "runs", { agentId, page }] as const,
  runsAll: ["simulations", "runs"] as const,
  run: (id: string) => ["simulations", "run", id] as const,
  comparison: (id: string) => ["simulations", "run", id, "comparison"] as const,
};

export const isSimActive = (s: SimStatus | undefined) => s === "pending" || s === "running";

export function useExperiments(agentId: string | null, page: number) {
  return useQuery({
    queryKey: simKeys.experiments(agentId ?? "", page),
    queryFn: () => unwrap(api.GET("/experiments", { params: { query: { page, page_size: SIM_PAGE_SIZE, ...(agentId && { agent_id: agentId }) } } })),
    placeholderData: keepPreviousData,
    refetchOnMount: "always",
    refetchInterval: (q) => (q.state.data?.items.some((e) => isSimActive(e.status)) ? SIM_POLL_MS : false),
  });
}

/** Individual runs outside a batch (the Simulations page "Individual" tab). */
export function useStandaloneRuns(agentId: string | null, page: number) {
  return useQuery({
    queryKey: simKeys.runs(agentId ?? "", page),
    queryFn: () =>
      unwrap(
        api.GET("/simulation-runs", {
          params: { query: { standalone: true, page, page_size: SIM_PAGE_SIZE, ...(agentId && { agent_id: agentId }) } },
        }),
      ),
    placeholderData: keepPreviousData,
    refetchOnMount: "always",
    refetchInterval: (q) => (q.state.data?.items.some((r) => isSimActive(r.status)) ? SIM_POLL_MS : false),
  });
}

export function useExperiment(id: string | undefined) {
  return useQuery({
    queryKey: simKeys.experiment(id ?? ""),
    queryFn: () => unwrap(api.GET("/experiments/{experiment_id}", { params: { path: { experiment_id: id! } } })),
    enabled: Boolean(id),
    retry: false,
    refetchInterval: (q) => (isSimActive(q.state.data?.status) ? SIM_POLL_MS : false),
  });
}

export function useExperimentRuns(id: string | undefined, page: number, poll: boolean) {
  return useQuery({
    queryKey: simKeys.experimentRuns(id ?? "", page),
    queryFn: () =>
      unwrap(api.GET("/experiments/{experiment_id}/runs", { params: { path: { experiment_id: id! }, query: { page, page_size: SIM_PAGE_SIZE } } })),
    enabled: Boolean(id),
    placeholderData: keepPreviousData,
    refetchInterval: (q) => (poll || q.state.data?.items.some((r) => isSimActive(r.status)) ? SIM_POLL_MS : false),
  });
}

export function useScorecard(id: string | undefined, baselineExperimentId: string | null, poll: boolean) {
  return useQuery({
    queryKey: simKeys.scorecard(id ?? "", baselineExperimentId ?? "original"),
    queryFn: () =>
      unwrap(
        api.GET("/experiments/{experiment_id}/scorecard", {
          params: {
            path: { experiment_id: id! },
            query: baselineExperimentId ? { baseline: "experiment", baseline_experiment_id: baselineExperimentId } : { baseline: "original" },
          },
        }),
      ),
    enabled: Boolean(id),
    retry: false,
    placeholderData: keepPreviousData,
    refetchInterval: poll ? SIM_POLL_MS : false,
  });
}

/** Other batches of the agent, for the scorecard baseline picker. */
export function useAgentExperiments(agentId: string | undefined) {
  return useQuery({
    queryKey: [...simKeys.experimentsAll, "baseline-options", agentId ?? ""],
    queryFn: () => fetchAll((page) => unwrap(api.GET("/experiments", { params: { query: { agent_id: agentId!, ...page } } }))),
    enabled: Boolean(agentId),
    staleTime: 30_000,
  });
}

export function cancelExperiment(id: string) {
  return unwrap(api.POST("/experiments/{experiment_id}/cancel", { params: { path: { experiment_id: id } } }));
}

export function useSimulationRun(id: string | undefined) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: simKeys.run(id ?? ""),
    queryFn: () => unwrap(api.GET("/simulation-runs/{simulation_run_id}", { params: { path: { simulation_run_id: id! } } })),
    enabled: Boolean(id),
    retry: false,
    refetchInterval: (q) => (isSimActive(q.state.data?.status) ? SIM_POLL_MS : false),
  });
  const status = query.data?.status;
  // Once a run ends, the lists that show it must not keep the cached "Running" row and cost.
  useEffect(() => {
    if (status && !isSimActive(status)) {
      void qc.invalidateQueries({ queryKey: simKeys.runsAll });
      void qc.invalidateQueries({ queryKey: simKeys.experimentsAll });
    }
  }, [status, qc]);
  return query;
}

/** The transcript and the simulated call's checks land a few seconds after the run completes. */
export function comparisonPending(c: Comparison | undefined): boolean {
  if (!c) return false;
  return c.simulated.transcript.length === 0 || c.verdicts.some((v) => v.simulated == null);
}
const COMPARISON_POLLS = 40;

export function useComparison(id: string | undefined, ready: boolean) {
  return useQuery({
    queryKey: simKeys.comparison(id ?? ""),
    queryFn: () => unwrap(api.GET("/simulation-runs/{simulation_run_id}/comparison", { params: { path: { simulation_run_id: id! } } })),
    enabled: Boolean(id) && ready,
    retry: false,
    refetchInterval: (q) => (comparisonPending(q.state.data) && q.state.dataUpdateCount < COMPARISON_POLLS ? SIM_POLL_MS : false),
  });
}

export function cancelSimulationRun(id: string) {
  return unwrap(api.POST("/simulation-runs/{simulation_run_id}/cancel", { params: { path: { simulation_run_id: id } } }));
}

export function preflight(body: PreflightRequest) {
  return unwrap(api.POST("/simulations/preflight", { body }));
}

export function startSimulationRun(
  body: {
    agent_id: string;
    mode: SimMode;
    base_call_id?: string;
    target?: SimTarget;
    persona_brief?: PersonaBrief;
    dynamic_variables?: Record<string, string>;
    settings?: SimSettings;
  },
  key: string,
) {
  return unwrap(api.POST("/simulation-runs", { params: { header: { "Idempotency-Key": key } }, body }));
}

export function startExperiment(
  body: { agent_id: string; name?: string; mode: SimMode; target?: SimTarget; settings?: SimSettings } & (
    { base_call_ids: string[]; dataset_id?: never } | { dataset_id: string; base_call_ids?: never }
  ),
  key: string,
) {
  return unwrap(api.POST("/experiments", { params: { header: { "Idempotency-Key": key } }, body }));
}
