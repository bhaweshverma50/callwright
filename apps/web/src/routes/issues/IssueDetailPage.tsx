/**
 * Issue page `/issues/:id` (T024, T047, T053): what fails and how often, the calibration warning,
 * sample calls with the check's reasoning, the fix panel, validation evidence, apply, dismiss,
 * post-apply figures and the recurrence link. Polls every 2 s while a validation runs.
 */
import { WarningDiamond } from "@phosphor-icons/react";
import { useQueryClient } from "@tanstack/react-query";
import { Archive, ChevronLeft, ListChecks, Repeat, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { useAgentOptions } from "../../api/calls";
import { isApiError } from "../../api/errors";
import {
  ISSUE_PAGE_SIZE,
  cancelValidation,
  issueKeys,
  useIssue,
  useIssueSamples,
  useIssueValidations,
  type DetectedIssue,
  type FixKind,
  type IssueSample,
} from "../../api/issues";
import { Badge, Button, EmptyState, PageHeader, Pagination, Panel, PanelLoader, Table, TruncatedText, toast, type Column } from "../../components";
import { RecordNotFound } from "../NotFound";
import { relative } from "../calls/format";
import { Figure, problemText, shortId } from "../simulations/shared";
import { ApplyPanel } from "./ApplyPanel";
import { DismissDialog } from "./DismissDialog";
import { FixPanel } from "./FixPanel";
import { ValidateDialog } from "./ValidateDialog";
import { ValidationEvidence } from "./ValidationEvidence";
import { DISMISS_LABELS, IssueStatusBadge, ORIGIN_LABELS } from "./shared";
import { withoutLineRefs } from "../../lib/text";
import { agentPath } from "../../lib/paths";

const SAMPLE_COLUMNS: Column<IssueSample>[] = [
  {
    key: "call",
    header: "Call",
    cell: (s) => (
      <span className="flex flex-col gap-0.5 py-0.5">
        <Link
          to={`/calls?call=${s.call_id}`}
          title={s.call_id}
          className="whitespace-nowrap rounded-inline font-mono text-[13px] text-fg-2 hover:text-fg hover:underline"
        >
          {shortId(s.call_id)}
        </Link>
        {s.call_origin === "simulation" && <span className="text-[12px] text-fg-3">Simulated</span>}
        <span className="max-w-[78vw] whitespace-normal py-0.5 text-[13px] leading-relaxed text-fg md:hidden">
          {withoutLineRefs(s.reason_excerpt)}
        </span>
      </span>
    ),
  },
  {
    key: "reason",
    header: "Why the check failed it",
    hideOnNarrow: true,
    cell: (s) => <p className="min-w-[24ch] max-w-[72ch] py-0.5 text-[13px] leading-relaxed text-fg">{withoutLineRefs(s.reason_excerpt)}</p>,
  },
  {
    key: "version",
    header: "Version",
    hideOnNarrow: true,
    cell: (s) => (
      <span title={s.agent_version_id} className="whitespace-nowrap font-mono text-[12px] text-fg-3">
        {shortId(s.agent_version_id, 8, 4)}
      </span>
    ),
  },
  { key: "when", header: "When", hideOnNarrow: true, cell: (s) => <span className="whitespace-nowrap text-fg-2">{relative(s.failed_at)}</span> },
];

function Summary({ issue, agentName }: { issue: DetectedIssue; agentName: string }) {
  return (
    <section aria-label="Summary" className="rounded-panel border border-line bg-surface px-5 py-4 shadow-1">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <IssueStatusBadge status={issue.status} />
        {issue.origin !== "real" && <Badge tone="neutral">{ORIGIN_LABELS[issue.origin]}</Badge>}
        <span className="text-[13px] text-fg-3">
          Found by{" "}
          <span className="text-fg-2">
            {issue.evaluator_display_name ?? issue.evaluator_name} v{issue.evaluator_version}
          </span>{" "}
          on{" "}
          <Link to={agentPath({ id: issue.agent_id, type: issue.agent_type })} className="text-accent-text hover:underline">
            {agentName}
          </Link>
          {issue.flow_node_label && (
            <>
              , node <span className="text-fg-2">{issue.flow_node_label}</span>
            </>
          )}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Figure label="Affected calls">{issue.affected_call_count}</Figure>
        <Figure label="On the published version">{issue.current_version_call_count}</Figure>
        <Figure label="First seen">{issue.first_seen_at ? relative(issue.first_seen_at) : "n/a"}</Figure>
        <Figure label="Last seen">{relative(issue.last_seen_at)}</Figure>
      </div>
      {issue.suspected_cause && (
        <p className="mt-4 border-t border-line pt-3 text-[13px] text-fg-2">
          <span className="text-fg-3">Suspected cause: </span>
          {issue.suspected_cause}
        </p>
      )}
    </section>
  );
}

function Notices({ issue }: { issue: DetectedIssue }) {
  return (
    <>
      {issue.calibration_warning && (
        <div role="note" className="flex items-start gap-3 rounded-panel border border-line bg-surface px-4 py-3 shadow-1">
          <span className="grid size-8 shrink-0 place-items-center rounded-control bg-warning-soft text-warning-text">
            <TriangleAlert className="size-4" aria-hidden />
          </span>
          <p className="text-[14px] leading-relaxed text-fg-2">
            <span className="font-medium text-fg">This check may be wrong.</span> It often disagrees with the labels people gave in calibration, so
            some of these failures may not be real.{" "}
            <Link to={`/calibration?agent=${issue.agent_id}`} className="font-medium text-accent-text hover:underline">
              Open calibration
            </Link>
          </p>
        </div>
      )}
      {issue.recurrence_of && (
        <div role="note" className="flex items-start gap-3 rounded-panel border border-line bg-surface px-4 py-3 shadow-1">
          <span className="grid size-8 shrink-0 place-items-center rounded-control bg-accent-soft text-accent-text">
            <Repeat className="size-4" aria-hidden />
          </span>
          <p className="text-[14px] leading-relaxed text-fg-2">
            <span className="font-medium text-fg">This pattern came back after a fix.</span> It matches an issue that was fixed earlier and showed up
            again on the new version.{" "}
            <Link to={`/issues/${issue.recurrence_of}`} className="font-medium text-accent-text hover:underline">
              Open the earlier issue
            </Link>
          </p>
        </div>
      )}
      {issue.status === "dismissed" && (
        <div role="note" className="flex items-start gap-3 rounded-panel border border-line bg-surface px-4 py-3 shadow-1">
          <span className="grid size-8 shrink-0 place-items-center rounded-control bg-surface-3 text-fg-2">
            <Archive className="size-4" aria-hidden />
          </span>
          <div className="flex flex-col gap-1 text-[14px] text-fg-2">
            <p>
              <span className="font-medium text-fg">Dismissed{issue.dismiss_reason ? `: ${DISMISS_LABELS[issue.dismiss_reason]}` : ""}.</span>{" "}
              {issue.dismissed_at && `${relative(issue.dismissed_at)}. `}Later detections update its counts and keep it dismissed.
            </p>
            {issue.dismiss_note && <p className="text-fg">{issue.dismiss_note}</p>}
            {issue.duplicate_of && (
              <Link to={`/issues/${issue.duplicate_of}`} className="w-fit font-medium text-accent-text hover:underline">
                Open the issue it duplicates
              </Link>
            )}
          </div>
        </div>
      )}
    </>
  );
}

export function IssueDetailPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const issue = useIssue(id);
  const validating = issue.data?.status === "validating";
  const validations = useIssueValidations(id, validating);
  const [samplePage, setSamplePage] = useState(1);
  const samples = useIssueSamples(id, samplePage);
  const agents = useAgentOptions();
  const [validate, setValidate] = useState<{ draft: { kind: FixKind; guidance: string | null } | null } | null>(null);
  const [dismissing, setDismissing] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const wasValidating = useRef(false);

  // When a validation finishes, refresh the fix revisions and the list (statuses changed).
  useEffect(() => {
    if (wasValidating.current && !validating) {
      void qc.invalidateQueries({ queryKey: issueKeys.fixes(id) });
      void qc.invalidateQueries({ queryKey: issueKeys.validations(id) });
      void qc.invalidateQueries({ queryKey: issueKeys.lists });
    }
    wasValidating.current = validating;
  }, [validating, id, qc]);

  if (isApiError(issue.error) && issue.error.status === 404) return <RecordNotFound kind="issue" backTo="/issues" backLabel="Back to Issues" />;
  if (issue.isError)
    return (
      <EmptyState
        icon={<WarningDiamond weight="duotone" />}
        title="The issue did not load"
        actions={<Button onClick={() => void issue.refetch()}>Try again</Button>}
      >
        {problemText(issue.error, "issue")}
      </EmptyState>
    );
  if (!issue.data) return <PanelLoader label="Opening issue" />;
  const i = issue.data;
  const agentName = agents.data?.find((a) => a.id === i.agent_id)?.name ?? "the agent";
  const closed = i.status === "applied" || i.status === "dismissed";

  async function cancel() {
    setCancelling(true);
    try {
      const updated = await cancelValidation(i.issue_id);
      qc.setQueryData(issueKeys.issue(i.issue_id), updated);
      void qc.invalidateQueries({ queryKey: issueKeys.all });
      toast({ tone: "info", title: "Validation cancelled", description: "Simulations not yet started are not charged. The issue is open again." });
    } catch (e) {
      toast({ tone: "error", title: "The validation was not cancelled", description: problemText(e, "issue") });
    } finally {
      setCancelling(false);
    }
  }

  const refreshAfterStart = () => {
    void qc.invalidateQueries({ queryKey: issueKeys.issue(i.issue_id) });
    void qc.invalidateQueries({ queryKey: issueKeys.fixes(i.issue_id) });
    void qc.invalidateQueries({ queryKey: issueKeys.validations(i.issue_id) });
    void qc.invalidateQueries({ queryKey: issueKeys.lists });
    toast({ tone: "success", title: "Validation started", description: "Both batches are running. The result appears on this page." });
  };

  return (
    <div className="flex flex-col">
      <Link
        to={`/issues?agent=${i.agent_id}`}
        className="link-underline mb-4 inline-flex w-fit items-center gap-1 rounded-inline text-[13px] text-fg-2 hover:text-fg"
      >
        <ChevronLeft className="size-4" aria-hidden /> Back to Issues
      </Link>
      <PageHeader
        title={<span className="break-words">{i.title}</span>}
        description={i.description}
        actions={
          !closed ? (
            <Button icon={<Archive aria-hidden />} onClick={() => setDismissing(true)}>
              Dismiss
            </Button>
          ) : undefined
        }
      />
      <div className="flex flex-col gap-6">
        <Summary issue={i} agentName={agentName} />
        <Notices issue={i} />
        <FixPanel
          key={`${i.issue_id}-${i.current_fix?.revision ?? 0}`}
          issue={i}
          onValidate={() => setValidate({ draft: null })}
          onDraftAndValidate={(draft) => setValidate({ draft })}
        />
        {validations.data && validations.data.length > 0 && (
          <ValidationEvidence
            attempts={validations.data}
            canCancel={i.status === "validating"}
            cancelling={cancelling}
            onCancel={() => void cancel()}
          />
        )}
        <ApplyPanel issue={i} />
        <Panel
          title="Sample calls"
          description={`Up to 50 recent failing calls with the check's reasoning, newest first.${samples.data ? ` ${samples.data.total} kept.` : ""}`}
          icon={<ListChecks aria-hidden />}
          bodyClassName="p-0"
        >
          <Table
            caption="Sample calls"
            columns={SAMPLE_COLUMNS}
            rows={samples.data?.items}
            rowKey={(s) => s.call_id}
            loading={samples.isPending}
            stale={samples.isPlaceholderData}
            skeletonRows={4}
            empty={<p className="px-5 py-6 text-[13px] text-fg-3">The sample calls are no longer available. Retention removed them.</p>}
          />
          {samples.data && samples.data.total > ISSUE_PAGE_SIZE && (
            <div className="border-t border-line">
              <Pagination
                page={samplePage}
                totalPages={samples.data.total_pages}
                total={samples.data.total}
                pageSize={ISSUE_PAGE_SIZE}
                noun="calls"
                onPageChange={setSamplePage}
              />
            </div>
          )}
        </Panel>
        <p className="text-[12px] text-fg-3">
          <TruncatedText className="max-w-full">{`Issue ${i.issue_id}`}</TruncatedText>
        </p>
      </div>
      {validate && (
        <ValidateDialog open onOpenChange={(o) => !o && setValidate(null)} issue={i} draft={validate.draft} onStarted={refreshAfterStart} />
      )}
      <DismissDialog open={dismissing} onOpenChange={setDismissing} issue={i} />
    </div>
  );
}
