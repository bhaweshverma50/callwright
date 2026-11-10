/**
 * Run panel (US1, T042): the chosen run (latest by default) with its totals, progress while it
 * runs (polling every 3 s), a summary toast when it finishes, cancel, export and the result rows
 * with manual override. Earlier runs are one pick away.
 */
import { ClipboardText } from "@phosphor-icons/react";
import { useQueryClient } from "@tanstack/react-query";
import { CircleStop, Download, History } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  cancelTestRun,
  exportTestRun,
  isRunActive,
  overrideTestResult,
  testingKeys,
  useTestRun,
  type TestCategory,
  type TestRun,
  type TestRunDetail,
} from "../../../api/testing";
import { Badge, Button, EmptyState, Figure, Panel, ProgressBar, Segmented, Select, Skeleton, toast } from "../../../components";
import { ResultRow } from "./ResultRow";
import { costUsd, timeAgo } from "../../../lib/format";
import { downloadJson } from "../../../lib/download";
import { problemText } from "../../../api/problems";

type Filter = "all" | "failed" | "error" | "manual";

const TARGETS: Record<TestRun["target"]["type"], string> = { draft: "Saved draft", published: "Published version", version: "Earlier version" };

function summary(run: TestRun): string {
  const parts = [`${run.passed} passed`, `${run.failed} failed`];
  if (run.errored) parts.push(`${run.errored} with errors`);
  return parts.join(", ");
}

export function TestRunPanel({
  agentId,
  runs,
  runId,
  onRunId,
  categories,
}: {
  agentId: string;
  runs: TestRun[] | undefined;
  runId: string | null;
  onRunId: (id: string) => void;
  categories: TestCategory[] | undefined;
}) {
  const qc = useQueryClient();
  const run = useTestRun(runId);
  const [filter, setFilter] = useState<Filter>("all");
  const [pendingCase, setPendingCase] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const data = run.data;
  const active = isRunActive(data?.status);

  // Summary toast when a run this page watched finishes (T042).
  const watched = useRef<{ id: string; active: boolean } | null>(null);
  useEffect(() => {
    if (!data) return;
    const prev = watched.current;
    if (prev && prev.id === data.test_run_id && prev.active && !isRunActive(data.status)) {
      toast({
        tone: data.status === "completed" ? "success" : "info",
        title: data.status === "completed" ? `Run ${data.number ?? ""} finished`.replace("  ", " ") : `Run ${data.status}`,
        description: summary(data),
      });
      void qc.invalidateQueries({ queryKey: testingKeys.cases(agentId) });
      void qc.invalidateQueries({ queryKey: testingKeys.runs(agentId) });
    }
    watched.current = { id: data.test_run_id, active: isRunActive(data.status) };
  }, [data, agentId, qc]);

  const results = useMemo(() => {
    const all = data?.results ?? [];
    if (filter === "failed") return all.filter((r) => r.status === "failed");
    if (filter === "error") return all.filter((r) => r.status === "error");
    if (filter === "manual") return all.filter((r) => r.is_manual);
    return all;
  }, [data, filter]);

  const override = async (caseId: string, status: "passed" | "failed" | null) => {
    if (!data) return;
    setPendingCase(caseId);
    try {
      const res = await overrideTestResult(data.test_run_id, caseId, status);
      qc.setQueryData<TestRunDetail>(testingKeys.run(data.test_run_id), (old) =>
        old ? { ...old, ...res.run, results: old.results.map((r) => (r.test_case_id === caseId ? res.result : r)) } : old,
      );
      void qc.invalidateQueries({ queryKey: testingKeys.cases(agentId) });
      void qc.invalidateQueries({ queryKey: testingKeys.runs(agentId) });
    } catch (e) {
      toast({ tone: "error", title: "The verdict was not changed", description: problemText(e) });
    } finally {
      setPendingCase(null);
    }
  };

  const cancel = async () => {
    if (!data) return;
    setCancelling(true);
    try {
      await cancelTestRun(data.test_run_id);
      await qc.invalidateQueries({ queryKey: testingKeys.run(data.test_run_id) });
    } catch (e) {
      toast({ tone: "error", title: "The run was not cancelled", description: problemText(e) });
    } finally {
      setCancelling(false);
    }
  };

  const doExport = async () => {
    if (!data) return;
    try {
      downloadJson(`test_run_${data.test_run_id}_results.json`, await exportTestRun(data.test_run_id));
    } catch (e) {
      toast({ tone: "error", title: "Export failed", description: problemText(e) });
    }
  };

  if (!runs) return <Skeleton className="h-48 w-full rounded-panel" />;
  if (runs.length === 0 || !runId) {
    return (
      <Panel title="Runs" icon={<History aria-hidden />}>
        <EmptyState compact className="px-0 py-2" icon={<ClipboardText weight="duotone" />} title="No runs yet">
          Run the test cases to see each reply with a pass or fail verdict and the judge's reasoning.
        </EmptyState>
      </Panel>
    );
  }

  const done = data ? data.passed + data.failed + data.errored : 0;
  return (
    <Panel
      title={data ? `Run ${data.number ?? ""}`.trim() : "Run"}
      description={data ? `${TARGETS[data.target.type]}, judged by ${data.judge_model}, ${timeAgo(data.created_at)}` : undefined}
      icon={<History aria-hidden />}
      bodyClassName="p-0"
      actions={
        <>
          {active ? (
            <Button size="sm" variant="secondary" icon={<CircleStop aria-hidden />} pending={cancelling} onClick={() => void cancel()}>
              Cancel
            </Button>
          ) : (
            <Button size="sm" variant="ghost" icon={<Download aria-hidden />} disabled={!data} onClick={() => void doExport()}>
              {/* Narrow screens show the icon only; sr-only keeps the name. */}
              <span className="sr-only sm:not-sr-only">Export</span>
            </Button>
          )}
        </>
      }
    >
      {!data ? (
        <div className="flex flex-col gap-3 p-5">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : (
        <>
          <div className="flex flex-col gap-4 border-b border-line px-5 py-4">
            <div role="group" aria-label="Run totals" className="grid grid-cols-2 gap-4 sm:grid-cols-5">
              <Figure label="Passed">
                <span className="text-success-text">{data.passed}</span>
              </Figure>
              <Figure label="Failed">
                <span className={data.failed ? "text-danger-text" : undefined}>{data.failed}</span>
              </Figure>
              <Figure label="Errors">
                <span className={data.errored ? "text-warning-text" : undefined}>{data.errored}</span>
              </Figure>
              <Figure label="Cases">{data.total}</Figure>
              <Figure label="Cost">{active ? "Running" : costUsd(data.cost_usd)}</Figure>
            </div>
            <div className="flex items-center gap-3">
              <ProgressBar completed={data.passed} failed={data.failed} cancelled={data.errored} total={data.total} label="Run progress" />
              <span className="shrink-0 font-mono text-[12px] text-fg-3 tnum">
                {done} / {data.total}
              </span>
              {active && <Badge tone="accent">{data.status === "queued" ? "Queued" : "Running"}</Badge>}
              {data.status === "cancelled" && <Badge tone="neutral">Cancelled</Badge>}
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-2.5">
            <Segmented
              size="sm"
              aria-label="Show results"
              value={filter}
              onValueChange={setFilter}
              options={[
                { value: "all", label: "All" },
                { value: "failed", label: "Failed" },
                { value: "error", label: "Errors" },
                { value: "manual", label: "Manual" },
              ]}
            />
            {runs.length > 1 && (
              <Select
                size="sm"
                aria-label="Choose a run"
                className="w-[130px]"
                value={runId}
                onValueChange={onRunId}
                options={runs.map((r) => ({ value: r.test_run_id, label: `Run ${r.number ?? ""}`.trim(), meta: timeAgo(r.created_at) }))}
              />
            )}
          </div>
          {results.length === 0 ? (
            <p className="px-5 py-6 text-[13px] text-fg-3">No results match this filter.</p>
          ) : (
            <ul className="divide-y divide-line" aria-label="Results">
              {results.map((r) => (
                <ResultRow
                  key={r.test_case_id}
                  result={r}
                  categories={categories}
                  canOverride={data.status === "completed" || data.status === "cancelled"}
                  pending={pendingCase === r.test_case_id}
                  onOverride={(s) => void override(r.test_case_id, s)}
                />
              ))}
            </ul>
          )}
        </>
      )}
    </Panel>
  );
}
