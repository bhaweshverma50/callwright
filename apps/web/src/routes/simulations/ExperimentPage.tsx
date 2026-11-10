/**
 * Batch page `/simulations/:experimentId` (US3, T067): progress while runs finish, cancel, what a
 * variant changes, the scorecard by check and by flow node against the original calls or another
 * batch over the same calls, failed runs with their errors, and every run with a link to its
 * comparison. Polls every 3 s while the batch is queued or running.
 */
import { Flask } from "@phosphor-icons/react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, ChevronLeft, CircleStop, GitCompareArrows, ListChecks, Scale, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { isApiError } from "../../api/errors";
import {
  SIM_PAGE_SIZE,
  cancelExperiment,
  isSimActive,
  simKeys,
  useAgentExperiments,
  useExperiment,
  useExperimentRuns,
  useScorecard,
  type Experiment,
  type SimulationRun,
} from "../../api/simulations";
import {
  Button,
  type Column,
  ConfirmDialog,
  EmptyState,
  Figure,
  PageHeader,
  Pagination,
  Panel,
  PanelLoader,
  ProblemAlert,
  ProgressBar,
  Segmented,
  Select,
  Skeleton,
  Table,
  toast,
  TruncatedText,
} from "../../components";
import { RecordNotFound } from "../NotFound";
import { ScorecardTable } from "./ScorecardTable";
import { END_REASONS, MODE_LABELS, SimStatusBadge, targetPhrase } from "./shared";
import { costUsd, plural, shortId, timeAgo, whenLong } from "../../lib/format";
import { problemText } from "../../api/problems";
import { SIMULATIONS_PATH, callPath, datasetPath, simulationRunPath } from "../../lib/paths";

const RUN_COLUMNS: Column<SimulationRun>[] = [
  {
    key: "call",
    header: "Base call",
    cell: (r) =>
      r.base_call_id ? (
        <Link
          to={callPath(r.base_call_id)}
          title={r.base_call_id}
          className="block whitespace-nowrap rounded-inline font-mono text-[13px] text-fg-2 hover:text-fg hover:underline"
        >
          {shortId(r.base_call_id)}
        </Link>
      ) : (
        <span className="text-fg-3">Persona brief</span>
      ),
  },
  { key: "status", header: "Status", cell: (r) => <SimStatusBadge status={r.status} /> },
  {
    key: "end",
    header: "Ended because",
    hideOnNarrow: true,
    cell: (r) =>
      r.error_message ? (
        <TruncatedText className="max-w-[34ch] text-danger-text">{r.error_message}</TruncatedText>
      ) : (
        <span className="whitespace-nowrap text-fg-2">{r.end_reason ? END_REASONS[r.end_reason] : "n/a"}</span>
      ),
  },
  {
    key: "diverged",
    header: "Diverged",
    hideOnNarrow: true,
    cell: (r) => <span className="whitespace-nowrap text-fg-2">{r.diverged_at_turn != null ? `Turn ${r.diverged_at_turn}` : "No"}</span>,
  },
  { key: "cost", header: "Cost", numeric: true, hideOnNarrow: true, cell: (r) => costUsd(r.cost_usd) },
  {
    key: "open",
    header: <span className="sr-only">Comparison</span>,
    align: "right",
    cell: (r) =>
      r.status === "completed" ? (
        <Link
          to={simulationRunPath(r.simulation_run_id)}
          className="inline-flex items-center gap-1 whitespace-nowrap rounded-inline text-[13px] font-medium text-accent-text hover:underline"
          aria-label={`Compare ${r.base_call_id ?? "run"}`}
        >
          Compare <ArrowRight className="size-3.5" aria-hidden />
        </Link>
      ) : null,
  },
];

function VariantDiff({ exp }: { exp: Experiment }) {
  if (!exp.variant_diff?.length) return null;
  const text = (v: unknown) => (typeof v === "string" ? v : v === undefined ? "" : JSON.stringify(v, null, 2));
  return (
    <Panel
      title="What the variant changes"
      description={`Compared with the base version. Hash ${exp.config_hash.slice(0, 18)}`}
      icon={<GitCompareArrows aria-hidden />}
    >
      <ul className="flex flex-col gap-4">
        {exp.variant_diff.map((d, i) => (
          <li key={i} className="flex min-w-0 flex-col gap-2">
            <span className="break-all font-mono text-[12px] text-fg-3">{d.path}</span>
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
              {d.op !== "add" && (
                <div className="min-w-0 rounded-control border border-danger/25 bg-danger-soft/50 px-3 py-2">
                  <span className="text-[12px] font-medium text-danger-text">Before</span>
                  <p className="mt-0.5 whitespace-pre-wrap break-words text-[13px] text-fg">{text(d.old)}</p>
                </div>
              )}
              {d.op !== "remove" && (
                <div className="min-w-0 rounded-control border border-success/25 bg-success-soft/50 px-3 py-2">
                  <span className="text-[12px] font-medium text-success-text">After</span>
                  <p className="mt-0.5 whitespace-pre-wrap break-words text-[13px] text-fg">{text(d.value)}</p>
                </div>
              )}
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function Scorecard({ exp }: { exp: Experiment }) {
  const active = isSimActive(exp.status);
  const [mode, setMode] = useState<"original" | "experiment">("original");
  const [baselineId, setBaselineId] = useState<string | null>(null);
  const others = useAgentExperiments(exp.agent_id);
  const candidates = (others.data ?? []).filter((e) => e.experiment_id !== exp.experiment_id && e.status !== "pending");
  const chosen = mode === "experiment" ? (baselineId ?? candidates[0]?.experiment_id ?? null) : null;
  const card = useScorecard(exp.experiment_id, chosen, active);
  const data = card.data;
  const baselineName = chosen ? candidates.find((c) => c.experiment_id === chosen)?.name : null;
  const baselineLabel = chosen ? "Baseline batch" : "Original";

  return (
    <Panel
      title="Scorecard"
      description={
        data
          ? `${plural(data.sim_call_count, "simulated call")} against ${chosen ? `the batch "${baselineName ?? "chosen"}"` : plural(data.base_call_count, "original call")}${active ? ". Figures update as runs finish." : "."}`
          : "Pass rates before and after, per check."
      }
      icon={<Scale aria-hidden />}
      bodyClassName="p-0"
    >
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
        <span className="text-[13px] text-fg-3">Compare against</span>
        <Segmented
          size="sm"
          aria-label="Compare against"
          value={mode}
          onValueChange={setMode}
          options={[
            { value: "original", label: "Original calls" },
            { value: "experiment", label: "Another batch", disabled: candidates.length === 0 },
          ]}
        />
        {mode === "experiment" && candidates.length > 0 && (
          <Select
            size="sm"
            aria-label="Baseline batch"
            className="w-[300px] max-w-full"
            value={chosen ?? undefined}
            onValueChange={setBaselineId}
            options={candidates.map((c) => ({ value: c.experiment_id, label: c.name, meta: timeAgo(c.created_at) }))}
          />
        )}
      </div>
      {card.isError ? (
        <div className="p-5">
          <ProblemAlert error={card.error} kind="scorecard" className="[&>div]:mb-0" />
          {isApiError(card.error) && card.error.status === 422 && (
            <p className="text-[13px] text-fg-3">A batch can only be compared with another batch over the same calls.</p>
          )}
        </div>
      ) : !data ? (
        <div className="flex flex-col gap-2 p-5">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      ) : data.evaluators.length === 0 ? (
        <EmptyState compact icon={<Scale aria-hidden />} title={active ? "Waiting for the first runs" : "No checks to compare"}>
          {active
            ? "The scorecard fills in as simulated calls finish and their checks run."
            : "Turn on checks for this agent in its Quality tab, then run a batch to compare them."}
        </EmptyState>
      ) : (
        <>
          <ScorecardTable rows={data.evaluators} baselineLabel={baselineLabel} caption="Scorecard by check" />
          {data.by_node.length > 0 && (
            <div className="border-t border-line">
              <h3 className="px-5 pb-2 pt-4 text-[13px] font-semibold text-fg">By flow node</h3>
              <ScorecardTable rows={data.by_node} byNode baselineLabel={baselineLabel} caption="Scorecard by flow node" />
            </div>
          )}
          {data.excluded_runs.length > 0 && (
            <div className="border-t border-line px-5 py-4">
              <p className="mb-2 flex items-center gap-2 text-[13px] font-medium text-fg">
                <TriangleAlert className="size-4 text-warning" aria-hidden />
                {plural(data.excluded_runs.length, "run")} left out of the simulated side
              </p>
              <ul className="flex flex-col gap-1.5 text-[13px]">
                {data.excluded_runs.map((r) => (
                  <li key={r.simulation_run_id} className="flex min-w-0 flex-col gap-0.5 sm:flex-row sm:gap-3">
                    <span className="shrink-0 font-mono text-fg-3">{r.status}</span>
                    <span className="min-w-0 break-words text-fg-2">{r.error_message ?? "Cancelled before it started"}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </Panel>
  );
}

export function ExperimentPage() {
  const { experimentId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get("page") ?? 1) || 1);
  const qc = useQueryClient();
  const exp = useExperiment(experimentId);
  const active = isSimActive(exp.data?.status);
  const runs = useExperimentRuns(experimentId, page, active);
  const [confirm, setConfirm] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  if (isApiError(exp.error) && exp.error.status === 404)
    return <RecordNotFound kind="batch" backTo={SIMULATIONS_PATH} backLabel="Back to Simulations" />;
  if (exp.isError)
    return (
      <EmptyState
        icon={<Flask weight="duotone" />}
        title="The batch did not load"
        actions={<Button onClick={() => void exp.refetch()}>Try again</Button>}
      >
        {problemText(exp.error, "batch")}
      </EmptyState>
    );
  if (!exp.data) return <PanelLoader label="Opening batch" />;
  const e = exp.data;

  const cancel = async () => {
    setCancelling(true);
    try {
      const updated = await cancelExperiment(e.experiment_id);
      qc.setQueryData(simKeys.experiment(e.experiment_id), updated);
      await qc.invalidateQueries({ queryKey: simKeys.experiment(e.experiment_id) });
      toast({ tone: "info", title: "Batch cancelled", description: "Runs not yet started were cancelled and are not charged." });
      setConfirm(false);
    } catch (err) {
      toast({ tone: "error", title: "The batch was not cancelled", description: problemText(err) });
    } finally {
      setCancelling(false);
    }
  };

  const settled = e.completed_count + e.failed_count + e.cancelled_count;
  return (
    <div className="flex flex-col">
      <Link
        to={SIMULATIONS_PATH}
        className="link-underline mb-4 inline-flex w-fit items-center gap-1 rounded-inline text-[13px] text-fg-2 hover:text-fg"
      >
        <ChevronLeft className="size-4" aria-hidden /> Back to Simulations
      </Link>
      <PageHeader
        title={<span className="break-words">{e.name}</span>}
        description={`${MODE_LABELS[e.mode]} of ${plural(e.total_count, "call")} from ${e.agent_name ?? "the agent"}, against ${targetPhrase(e)}.`}
        actions={
          active ? (
            <Button icon={<CircleStop aria-hidden />} onClick={() => setConfirm(true)}>
              Cancel batch
            </Button>
          ) : undefined
        }
      />

      <div className="flex flex-col gap-6">
        <section aria-label="Progress" className="rounded-panel border border-line bg-surface px-5 py-4 shadow-1">
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <SimStatusBadge status={e.status} />
            <span className="text-[13px] text-fg-3">Started {whenLong(e.created_at)}</span>
            {e.source === "dataset" && e.dataset_id && (
              <Link to={datasetPath(e.dataset_id)} className="text-[13px] text-accent-text hover:underline">
                From a dataset
              </Link>
            )}
            {e.source === "issue_validation" && <span className="text-[13px] text-fg-3">Started by issue validation</span>}
          </div>
          <div className="mb-4 flex items-center gap-3">
            <ProgressBar
              completed={e.completed_count}
              failed={e.failed_count}
              cancelled={e.cancelled_count}
              total={e.total_count}
              label="Batch progress"
            />
            <span className="shrink-0 font-mono text-[12px] text-fg-2 tnum">
              {settled} / {e.total_count}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
            <Figure label="Completed">
              <span className="text-success-text">{e.completed_count}</span>
            </Figure>
            <Figure label="Failed">
              <span className={e.failed_count ? "text-danger-text" : undefined}>{e.failed_count}</span>
            </Figure>
            <Figure label="Cancelled">{e.cancelled_count}</Figure>
            <Figure label="Still to run">{e.total_count - settled}</Figure>
            <Figure label="Cost">{active && e.cost_usd == null ? "Running" : costUsd(e.cost_usd)}</Figure>
          </div>
        </section>

        <VariantDiff exp={e} />
        <Scorecard exp={e} />

        <Panel
          title="Runs"
          description="Each base call simulated once. Open a run to compare it side by side."
          icon={<ListChecks aria-hidden />}
          bodyClassName="p-0"
        >
          <Table
            caption="Runs of this batch"
            columns={RUN_COLUMNS}
            rows={runs.data?.items}
            rowKey={(r) => r.simulation_run_id}
            loading={runs.isPending}
            stale={runs.isPlaceholderData}
            skeletonRows={6}
          />
          {runs.data && runs.data.total > SIM_PAGE_SIZE && (
            <div className="border-t border-line">
              <Pagination
                page={page}
                totalPages={runs.data.total_pages}
                total={runs.data.total}
                pageSize={SIM_PAGE_SIZE}
                noun="runs"
                onPageChange={(p) => {
                  const next = new URLSearchParams(params);
                  if (p === 1) next.delete("page");
                  else next.set("page", String(p));
                  setParams(next, { replace: true });
                }}
              />
            </div>
          )}
        </Panel>
      </div>

      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="Cancel this batch?"
        description="Runs not yet started are cancelled and not charged. Runs in progress finish and are charged."
        confirmLabel="Cancel batch"
        cancelLabel="Keep running"
        tone="danger"
        pending={cancelling}
        onConfirm={() => void cancel()}
      />
    </div>
  );
}
