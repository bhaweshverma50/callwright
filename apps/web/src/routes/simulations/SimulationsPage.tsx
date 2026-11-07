/**
 * Simulations (US3, US4; T066, T093, T094): batches and individual runs in two tabs, filtered by
 * agent on the server (each filter change fetches again, with totals in the tab labels and
 * paging), the filter and page kept in the address. Lists poll every 3 s while anything shown is
 * queued or running. "New simulation" starts a standalone persona run.
 */
import { Flask } from "@phosphor-icons/react";
import { Layers, UserRoundPlus, Workflow } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { SIM_PAGE_SIZE, useExperiments, useStandaloneRuns, type Experiment, type SimulationRun } from "../../api/simulations";
import { Button, type Column, EmptyState, PageHeader, Pagination, ProgressBar, Select, Table, TabPanel, Tabs, TruncatedText } from "../../components";
import { NewSimulationDialog } from "./NewSimulationDialog";
import { END_REASONS, MODE_LABELS, SimStatusBadge, targetPhrase } from "./shared";
import { costUsd, timeAgo } from "../../lib/format";
import { useAllAgents } from "../../api/agents";
import { problemText } from "../../api/problems";
import { CALLS_PATH, experimentPath, simulationRunPath } from "../../lib/paths";

const ALL = "all";
type Tab = "batches" | "runs";

function runTitle(r: SimulationRun): string {
  if (r.base_call_id) return `${MODE_LABELS[r.mode]} of ${r.base_call_id}`;
  return r.persona_brief?.goal ? `Persona: ${r.persona_brief.goal}` : "Persona from a written brief";
}

const BATCH_COLUMNS: Column<Experiment>[] = [
  {
    key: "name",
    header: "Batch",
    cell: (e) => (
      <Link
        to={experimentPath(e.experiment_id)}
        className="flex min-w-0 max-w-[52vw] flex-col py-1 md:max-w-[42ch] gap-0.5 rounded-inline hover:underline"
      >
        <TruncatedText className="text-[14px] font-medium text-fg">{e.name}</TruncatedText>
        <span className="truncate text-[12px] text-fg-3">
          {MODE_LABELS[e.mode]} against {targetPhrase(e)}
        </span>
      </Link>
    ),
  },
  {
    key: "agent",
    header: "Agent",
    hideOnNarrow: true,
    cell: (e) => <TruncatedText className="max-w-[20ch] text-fg-2">{e.agent_name ?? e.agent_id}</TruncatedText>,
  },
  {
    key: "progress",
    header: "Progress",
    hideOnNarrow: true,
    width: "180px",
    cell: (e) => (
      <span className="flex items-center gap-2.5">
        <ProgressBar
          className="w-20"
          completed={e.completed_count}
          failed={e.failed_count}
          cancelled={e.cancelled_count}
          total={e.total_count}
          label={`${e.name} progress`}
        />
        <span className="whitespace-nowrap font-mono text-[12px] text-fg-2 tnum">
          {e.completed_count + e.failed_count} / {e.total_count}
        </span>
      </span>
    ),
  },
  { key: "status", header: "Status", cell: (e) => <SimStatusBadge status={e.status} /> },
  { key: "cost", header: "Cost", numeric: true, hideOnNarrow: true, cell: (e) => costUsd(e.cost_usd) },
  {
    key: "created",
    header: "Started",
    hideOnNarrow: true,
    cell: (e) => <span className="whitespace-nowrap text-fg-2">{timeAgo(e.created_at)}</span>,
  },
];

const RUN_COLUMNS: Column<SimulationRun>[] = [
  {
    key: "run",
    header: "Run",
    cell: (r) => (
      <Link
        to={simulationRunPath(r.simulation_run_id)}
        className="flex min-w-0 max-w-[52vw] flex-col py-1 md:max-w-[46ch] gap-0.5 rounded-inline hover:underline"
      >
        <TruncatedText className="text-[14px] font-medium text-fg">{runTitle(r)}</TruncatedText>
        <span className="truncate text-[12px] text-fg-3">Against {targetPhrase(r)}</span>
      </Link>
    ),
  },
  {
    key: "agent",
    header: "Agent",
    hideOnNarrow: true,
    cell: (r) => <TruncatedText className="max-w-[20ch] text-fg-2">{r.agent_name ?? r.agent_id}</TruncatedText>,
  },
  { key: "status", header: "Status", cell: (r) => <SimStatusBadge status={r.status} /> },
  {
    key: "end",
    header: "Ended because",
    hideOnNarrow: true,
    cell: (r) => <span className="whitespace-nowrap text-fg-2">{r.end_reason ? END_REASONS[r.end_reason] : "n/a"}</span>,
  },
  { key: "cost", header: "Cost", numeric: true, hideOnNarrow: true, cell: (r) => costUsd(r.cost_usd) },
  {
    key: "created",
    header: "Started",
    hideOnNarrow: true,
    cell: (r) => <span className="whitespace-nowrap text-fg-2">{timeAgo(r.created_at)}</span>,
  },
];

export function SimulationsPage() {
  const [params, setParams] = useSearchParams();
  const agentParam = params.get("agent") ?? ALL;
  const agentId = agentParam === ALL ? null : agentParam;
  const tab: Tab = params.get("tab") === "runs" ? "runs" : "batches";
  const page = Math.max(1, Number(params.get("page") ?? 1) || 1);
  const batches = useExperiments(agentId, tab === "batches" ? page : 1);
  const runs = useStandaloneRuns(agentId, tab === "runs" ? page : 1);
  const agents = useAllAgents();
  const [creating, setCreating] = useState(false);

  const set = (patch: Record<string, string | null>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) p.delete(k);
      else p.set(k, v);
    }
    setParams(p, { replace: true });
  };

  const agentOptions = useMemo(
    () => [{ value: ALL, label: "All agents" }, ...(agents.data ?? []).map((a) => ({ value: a.id, label: a.name }))],
    [agents.data],
  );
  const active = tab === "batches" ? batches : runs;

  const empty =
    tab === "batches" ? (
      <EmptyState
        compact
        icon={<Layers aria-hidden />}
        title={agentId ? "No batches for this agent" : "No batches yet"}
        actions={
          <Button asChild variant="secondary">
            <Link to={CALLS_PATH}>Select calls</Link>
          </Button>
        }
      >
        Select calls of one agent in Calls and choose Run simulation, or start one from a dataset. The batch page shows a scorecard of every check,
        before and after.
      </EmptyState>
    ) : (
      <EmptyState
        compact
        icon={<Workflow aria-hidden />}
        title={agentId ? "No individual runs for this agent" : "No individual runs yet"}
        actions={
          <Button variant="secondary" icon={<UserRoundPlus aria-hidden />} onClick={() => setCreating(true)}>
            New simulation
          </Button>
        }
      >
        Replay one call from its detail view, or write a persona brief to simulate a caller who has never called.
      </EmptyState>
    );

  return (
    <>
      <PageHeader
        title="Simulations"
        description="Replay real callers or simulated personas against a version of an agent, then compare every check before and after."
        actions={
          <Button variant="primary" icon={<UserRoundPlus aria-hidden />} onClick={() => setCreating(true)}>
            New simulation
          </Button>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Select
          size="sm"
          aria-label="Agent"
          className="w-[240px] max-w-full"
          value={agentParam}
          onValueChange={(v) => set({ agent: v === ALL ? null : v, page: null })}
          options={agentOptions}
        />
      </div>
      <Tabs
        aria-label="Simulations"
        value={tab}
        onValueChange={(v) => set({ tab: v === "runs" ? "runs" : null, page: null })}
        items={[
          { value: "batches", label: "Batches", icon: <Layers aria-hidden />, ...(batches.data && { count: batches.data.total }) },
          { value: "runs", label: "Individual runs", icon: <Workflow aria-hidden />, ...(runs.data && { count: runs.data.total }) },
        ]}
      >
        {(["batches", "runs"] as const).map((t) => (
          <TabPanel key={t} value={t}>
            <section
              aria-label={t === "batches" ? "Batches" : "Individual runs"}
              className="overflow-hidden rounded-panel border border-line bg-surface shadow-1"
            >
              {active.isError && !active.data ? (
                <EmptyState
                  compact
                  icon={<Flask weight="duotone" />}
                  title="Simulations did not load"
                  actions={<Button onClick={() => void active.refetch()}>Try again</Button>}
                >
                  {problemText(active.error, "simulation")}
                </EmptyState>
              ) : t === "batches" ? (
                <Table
                  caption="Batches, newest first"
                  columns={BATCH_COLUMNS}
                  rows={batches.data?.items}
                  rowKey={(e) => e.experiment_id}
                  loading={batches.isPending}
                  stale={batches.isPlaceholderData}
                  skeletonRows={5}
                  empty={empty}
                />
              ) : (
                <Table
                  caption="Individual runs, newest first"
                  columns={RUN_COLUMNS}
                  rows={runs.data?.items}
                  rowKey={(r) => r.simulation_run_id}
                  loading={runs.isPending}
                  stale={runs.isPlaceholderData}
                  skeletonRows={5}
                  empty={empty}
                />
              )}
              {active.data && active.data.total > SIM_PAGE_SIZE && (
                <div className="border-t border-line">
                  <Pagination
                    page={page}
                    totalPages={active.data.total_pages}
                    total={active.data.total}
                    pageSize={SIM_PAGE_SIZE}
                    noun={t === "batches" ? "batches" : "runs"}
                    onPageChange={(p) => set({ page: p === 1 ? null : String(p) })}
                  />
                </div>
              )}
            </section>
          </TabPanel>
        ))}
      </Tabs>
      {creating && <NewSimulationDialog open onOpenChange={setCreating} defaultAgentId={agentId} />}
    </>
  );
}
