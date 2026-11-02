/**
 * Issues (T023, T061; US1, FR-026, FR-027): recurring evaluator failures per agent, sorted by
 * affected calls. Agent, status, window and source are filtered on the server and kept in the
 * address; each change fetches the list again. Detection runs for the chosen agent with the same
 * window and source and shows its progress until it finishes.
 */
import { WarningDiamond } from "@phosphor-icons/react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, Radar, Repeat, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { useAgentOptions } from "../../api/calls";
import { isApiError } from "../../api/errors";
import {
  DEFAULT_WINDOW,
  ISSUE_PAGE_SIZE,
  WINDOWS,
  detectIssues,
  issueKeys,
  useIssues,
  useLatestDetection,
  type Detection,
  type IssueScope,
  type IssueSummary,
  type StatusFilter,
  type WindowDays,
} from "../../api/issues";
import { useActionKey } from "../../api/paid";
import { Badge, Button, EmptyState, PageHeader, Pagination, Segmented, Select, Table, TruncatedText, cn, type Column } from "../../components";
import { relative } from "../calls/format";
import { ProblemAlert, plural, problemText } from "../simulations/shared";
import { IssueStatusBadge, KIND_LABELS, ORIGIN_LABELS, SCOPE_LABELS, STATUS_FILTER_OPTIONS, windowRange } from "./shared";

const ALL = "all";
const DETECT_HINT = "Choose an agent to run detection";

const columns = (agentNames: Record<string, string>, showAgent: boolean): Column<IssueSummary>[] => [
  {
    key: "issue",
    header: "Issue",
    cell: (i) => (
      <Link to={`/issues/${i.issue_id}`} className="flex min-w-0 max-w-[60vw] flex-col gap-0.5 rounded-inline py-1 hover:underline md:max-w-[56ch]">
        <TruncatedText className="text-[13.5px] font-medium text-fg">{i.title}</TruncatedText>
        <span className="flex min-w-0 items-center gap-1.5 text-[12px] text-fg-3">
          <span className="truncate">{`${i.evaluator_display_name ?? i.evaluator_name}${i.flow_node_label ? `, node ${i.flow_node_label}` : ""}`}</span>
          {i.calibration_warning && (
            <span title="The check often disagrees with human labels" className="inline-flex items-center text-warning-text">
              <TriangleAlert className="size-3.5" aria-label="Check may be wrong" />
            </span>
          )}
          {i.recurrence_of && (
            <span title="Came back after a fix" className="inline-flex items-center text-accent-text">
              <Repeat className="size-3.5" aria-label="Recurrence" />
            </span>
          )}
        </span>
        <span className="mt-1 md:hidden">
          <IssueStatusBadge status={i.status} />
        </span>
      </Link>
    ),
  },
  ...(showAgent
    ? [
        {
          key: "agent",
          header: "Agent",
          hideOnNarrow: true,
          cell: (i: IssueSummary) => <TruncatedText className="max-w-[18ch] text-fg-2">{agentNames[i.agent_id] ?? "Unknown agent"}</TruncatedText>,
        },
      ]
    : []),
  { key: "status", header: "Status", hideOnNarrow: true, cell: (i) => <IssueStatusBadge status={i.status} /> },
  {
    key: "affected",
    header: "Affected calls",
    numeric: true,
    cell: (i) => (
      <span className="flex flex-col items-end gap-0.5 pr-1 md:pr-0">
        <span className="text-[13.5px] font-medium text-fg">{i.affected_call_count}</span>
        <span className="whitespace-nowrap font-sans text-[11.5px] text-fg-3">{i.current_version_call_count} on published</span>
      </span>
    ),
  },
  {
    key: "origin",
    header: "Source",
    hideOnNarrow: true,
    cell: (i) => (i.origin === "real" ? <span className="text-fg-2">Real calls</span> : <Badge tone="neutral">{ORIGIN_LABELS[i.origin]}</Badge>),
  },
  {
    key: "fix",
    header: "Current fix",
    hideOnNarrow: true,
    cell: (i) => <span className="whitespace-nowrap text-fg-2">{i.current_fix_kind ? KIND_LABELS[i.current_fix_kind] : "None yet"}</span>,
  },
  {
    key: "seen",
    header: "Last seen",
    hideOnNarrow: true,
    cell: (i) => <span className="whitespace-nowrap text-fg-2">{relative(i.last_seen_at)}</span>,
  },
];

function DetectionStatus({ detection }: { detection: Detection }) {
  const range = windowRange(detection.window_start, detection.window_end);
  if (detection.status === "running")
    return (
      <p role="status" className="flex items-center gap-2 text-[13px] text-fg-2">
        <Loader2 className="size-4 animate-spin text-accent-text" aria-hidden />
        Detecting issues in the last {detection.window_days} days{detection.include_simulated ? ", simulated calls included" : ""}. This takes up to a
        few minutes.
      </p>
    );
  if (detection.status === "failed")
    return (
      <p role="status" className="flex items-start gap-2 text-[13px] text-danger-text">
        <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
        The last detection stopped: {detection.error_message ?? "an unexpected error"}. Run it again.
      </p>
    );
  const found = (detection.issues_created ?? 0) + (detection.issues_updated ?? 0);
  return (
    <p role="status" className="text-[13px] text-fg-2">
      {found === 0 ? (
        <>
          <span className="font-medium text-fg">No recurring failures found</span>
          {range && ` between ${range}`}. {plural(detection.calls_scanned ?? 0, "call")} scanned.
        </>
      ) : (
        <>
          Last detection {detection.finished_at ? relative(detection.finished_at) : ""}: scanned {plural(detection.calls_scanned ?? 0, "call")} and{" "}
          {plural(detection.failures_scanned ?? 0, "failure")}
          {range && ` from ${range}`}, created {plural(detection.issues_created ?? 0, "issue")} and updated {detection.issues_updated ?? 0}.
        </>
      )}
    </p>
  );
}

function parseWindow(raw: string | null): WindowDays {
  const n = Number(raw);
  return (WINDOWS as number[]).includes(n) ? (n as WindowDays) : DEFAULT_WINDOW;
}

export function IssuesPage() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const agentParam = params.get("agent") ?? ALL;
  const agentId = agentParam === ALL ? null : agentParam;
  const rawStatus = params.get("status");
  const status: StatusFilter = STATUS_FILTER_OPTIONS.some((o) => o.value === rawStatus) ? (rawStatus as StatusFilter) : "all";
  const windowDays = parseWindow(params.get("window"));
  const scope: IssueScope = params.get("source") === "real_and_simulated" ? "real_and_simulated" : "real";
  const page = Math.max(1, Number(params.get("page") ?? 1) || 1);

  const filters = useMemo(() => ({ agentId, status, scope, windowDays, page }), [agentId, status, scope, windowDays, page]);
  const issues = useIssues(filters);
  const agents = useAgentOptions();
  const detection = useLatestDetection(agentId);
  const action = useActionKey();
  const [detectError, setDetectError] = useState<unknown>(null);
  const [starting, setStarting] = useState(false);

  const set = (patch: Record<string, string | null>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) p.delete(k);
      else p.set(k, v);
    }
    p.delete("page");
    setParams(p, { replace: true });
    setDetectError(null);
  };

  // A detection that just finished changes the list.
  const lastStatus = useRef<string | undefined>(undefined);
  const detStatus = detection.data?.status;
  useEffect(() => {
    if (lastStatus.current === "running" && detStatus && detStatus !== "running") void qc.invalidateQueries({ queryKey: issueKeys.lists });
    lastStatus.current = detStatus;
  }, [detStatus, qc]);

  async function detect() {
    if (!agentId) return;
    setStarting(true);
    setDetectError(null);
    try {
      const started = await detectIssues(
        { agent_id: agentId, window_days: windowDays, include_simulated: scope === "real_and_simulated" },
        action.current(),
      );
      action.reset();
      qc.setQueryData(issueKeys.detection(agentId), started);
    } catch (e) {
      if (!isApiError(e) || e.status !== 0) action.reset();
      setDetectError(e);
      if (isApiError(e) && e.status === 409) void detection.refetch();
    } finally {
      setStarting(false);
    }
  }

  const agentOptions = useMemo(
    () => [{ value: ALL, label: "All agents" }, ...(agents.data ?? []).map((a) => ({ value: a.id, label: a.name }))],
    [agents.data],
  );
  const tableColumns = useMemo(() => columns(Object.fromEntries((agents.data ?? []).map((a) => [a.id, a.name])), !agentId), [agents.data, agentId]);
  const running = detection.data?.status === "running";
  const conflict = isApiError(detectError) && detectError.status === 409;

  return (
    <>
      <PageHeader
        title="Issues"
        description="Repeated failures of one agent grouped into issues, each with a drafted fix that is tested in simulation before it is applied."
        actions={
          <div className="flex flex-col items-start gap-1 sm:items-end">
            <Button
              variant="primary"
              icon={running ? <Loader2 className="animate-spin" aria-hidden /> : <Radar aria-hidden />}
              disabled={!agentId || running}
              pending={starting}
              aria-describedby={!agentId ? "detect-hint" : undefined}
              onClick={() => void detect()}
            >
              {running ? "Detecting" : "Detect issues"}
            </Button>
            {!agentId && (
              <span id="detect-hint" className="text-[12px] text-fg-3">
                {DETECT_HINT}
              </span>
            )}
          </div>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="flex w-full gap-3 sm:w-auto">
          <Select
            size="sm"
            aria-label="Agent"
            className="min-w-0 flex-1 sm:w-[220px] sm:flex-none"
            value={agentParam}
            onValueChange={(v) => set({ agent: v === ALL ? null : v })}
            options={agentOptions}
          />
          <Select
            size="sm"
            aria-label="Status"
            className="w-[140px] shrink-0"
            value={status}
            onValueChange={(v) => set({ status: v })}
            options={STATUS_FILTER_OPTIONS}
          />
        </div>
        <Segmented
          size="sm"
          aria-label="Window"
          value={String(windowDays)}
          onValueChange={(v) => set({ window: v })}
          options={WINDOWS.map((w) => ({ value: String(w), label: `${w} days` }))}
        />
        <Segmented
          size="sm"
          aria-label="Source"
          value={scope}
          onValueChange={(v) => set({ source: v })}
          options={(["real", "real_and_simulated"] as const).map((s) => ({ value: s, label: SCOPE_LABELS[s] }))}
        />
      </div>

      {(detection.data || detectError) && (
        <div className="mb-4 flex flex-col gap-2">
          {conflict ? (
            <p role="alert" className="flex items-start gap-2 text-[13px] text-warning-text">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />A detection is already running for this agent. Its progress shows below;
              run another once it finishes.
            </p>
          ) : (
            <ProblemAlert error={detectError} kind="detection" className="[&>div]:mb-0" />
          )}
          {detection.data && <DetectionStatus detection={detection.data} />}
        </div>
      )}

      <section aria-label="Issues" className={cn("overflow-hidden rounded-panel border border-line bg-surface shadow-1")}>
        {issues.isError && !issues.data ? (
          <EmptyState
            compact
            icon={<WarningDiamond weight="duotone" />}
            title="Issues did not load"
            actions={<Button onClick={() => void issues.refetch()}>Try again</Button>}
          >
            {problemText(issues.error, "issue")}
          </EmptyState>
        ) : (
          <Table
            caption="Issues, most affected calls first"
            columns={tableColumns}
            rows={issues.data?.items}
            rowKey={(i) => i.issue_id}
            loading={issues.isPending}
            stale={issues.isPlaceholderData}
            skeletonRows={5}
            empty={
              <EmptyState compact icon={<WarningDiamond weight="duotone" />} title={agentId ? "No issues in this window" : "No issues yet"}>
                {agentId
                  ? `Nothing matches these filters in the last ${windowDays} days. Run detection to look for recurring failures, or widen the window.`
                  : "Choose an agent and run detection. Failures that share a cause are grouped into issues here."}
              </EmptyState>
            }
          />
        )}
        {issues.data && issues.data.total > ISSUE_PAGE_SIZE && (
          <div className="border-t border-line">
            <Pagination
              page={page}
              totalPages={issues.data.total_pages}
              total={issues.data.total}
              pageSize={ISSUE_PAGE_SIZE}
              noun="issues"
              onPageChange={(p) => {
                const next = new URLSearchParams(params);
                if (p === 1) next.delete("page");
                else next.set("page", String(p));
                setParams(next, { replace: true });
              }}
            />
          </div>
        )}
      </section>
    </>
  );
}
