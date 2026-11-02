/**
 * Datasets (US5, T082): named sets of calls of one agent, filtered by agent on the server, with
 * paging and the filter in the address. "New dataset" opens the create form.
 */
import { Database as DatabaseDuo } from "@phosphor-icons/react";
import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { useAgentOptions } from "../../api/calls";
import { DATASETS_PAGE_SIZE, useDatasets, type Dataset } from "../../api/datasets";
import { Button, EmptyState, PageHeader, Pagination, Select, Table, TruncatedText, type Column } from "../../components";
import { relative } from "../calls/format";
import { problemText } from "../simulations/shared";
import { NewDatasetDialog } from "./NewDatasetDialog";

const ALL = "all";

const COLUMNS: Column<Dataset>[] = [
  {
    key: "name",
    header: "Dataset",
    cell: (d) => (
      <Link to={`/datasets/${d.dataset_id}`} className="flex min-w-0 max-w-[52ch] flex-col gap-0.5 rounded-inline py-1 hover:underline">
        <TruncatedText className="text-[13.5px] font-medium text-fg">{d.name}</TruncatedText>
        {d.description && <span className="truncate text-[12px] text-fg-3">{d.description}</span>}
      </Link>
    ),
  },
  {
    key: "agent",
    header: "Agent",
    hideOnNarrow: true,
    cell: (d) => <TruncatedText className="max-w-[22ch] text-fg-2">{d.agent_name ?? d.agent_id}</TruncatedText>,
  },
  { key: "calls", header: "Calls", numeric: true, cell: (d) => d.item_count.toLocaleString() },
  {
    key: "updated",
    header: "Updated",
    hideOnNarrow: true,
    cell: (d) => <span className="whitespace-nowrap text-fg-2">{relative(d.updated_at)}</span>,
  },
];

export function DatasetsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const agentParam = params.get("agent") ?? ALL;
  const agentId = agentParam === ALL ? null : agentParam;
  const page = Math.max(1, Number(params.get("page") ?? 1) || 1);
  const datasets = useDatasets(agentId, page);
  const agents = useAgentOptions();
  const [creating, setCreating] = useState(false);
  const agentOptions = useMemo(
    () => [{ value: ALL, label: "All agents" }, ...(agents.data ?? []).map((a) => ({ value: a.id, label: a.name }))],
    [agents.data],
  );
  const set = (patch: Record<string, string | null>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) p.delete(k);
      else p.set(k, v);
    }
    setParams(p, { replace: true });
  };
  const total = datasets.data?.total ?? 0;

  return (
    <>
      <PageHeader
        title="Datasets"
        description="Saved sets of calls of one agent. Re-run every check on them, or replay them against a new prompt or model."
        actions={
          <Button variant="primary" icon={<Plus aria-hidden />} onClick={() => setCreating(true)}>
            New dataset
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
        {datasets.data && (
          <span className="text-[12.5px] text-fg-3" aria-live="polite">
            <span className="font-mono text-fg-2 tnum">{total.toLocaleString()}</span> {total === 1 ? "dataset" : "datasets"}
          </span>
        )}
      </div>
      <section aria-label="Datasets" className="overflow-hidden rounded-panel border border-line bg-surface shadow-1">
        {datasets.isError && !datasets.data ? (
          <EmptyState
            compact
            icon={<DatabaseDuo weight="duotone" />}
            title="Datasets did not load"
            actions={<Button onClick={() => void datasets.refetch()}>Try again</Button>}
          >
            {problemText(datasets.error, "dataset")}
          </EmptyState>
        ) : (
          <Table
            caption="Datasets, most recently updated first"
            columns={COLUMNS}
            rows={datasets.data?.items}
            rowKey={(d) => d.dataset_id}
            loading={datasets.isPending}
            stale={datasets.isPlaceholderData}
            skeletonRows={4}
            empty={
              <EmptyState
                compact
                icon={<DatabaseDuo weight="duotone" />}
                title={agentId ? "No datasets for this agent" : "No datasets yet"}
                actions={
                  <>
                    <Button variant="primary" icon={<Plus aria-hidden />} onClick={() => setCreating(true)}>
                      New dataset
                    </Button>
                    <Button asChild>
                      <Link to="/calls">Open Calls</Link>
                    </Button>
                  </>
                }
              >
                Keep the calls that matter, such as hard cases or past failures, and replay them after every change. Add calls from Calls or from a
                call's detail view.
              </EmptyState>
            }
          />
        )}
        {datasets.data && total > DATASETS_PAGE_SIZE && (
          <div className="border-t border-line">
            <Pagination
              page={page}
              totalPages={datasets.data.total_pages}
              total={total}
              pageSize={DATASETS_PAGE_SIZE}
              noun="datasets"
              onPageChange={(p) => set({ page: p === 1 ? null : String(p) })}
            />
          </div>
        )}
      </section>
      {creating && (
        <NewDatasetDialog open onOpenChange={setCreating} defaultAgentId={agentId} onCreated={(d) => navigate(`/datasets/${d.dataset_id}`)} />
      )}
    </>
  );
}
