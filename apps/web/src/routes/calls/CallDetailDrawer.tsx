import { ClipboardText, PhoneX } from "@phosphor-icons/react";
import {
  ArrowLeftRight,
  Bot,
  ChartNoAxesColumn,
  FlaskConical,
  GitBranch,
  Hash,
  MessagesSquare,
  PhoneIncoming,
  Receipt,
  ShieldCheck,
  Timer,
  type LucideIcon,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { callKeys, isOnAir, useCall, useFlowTransitions, useTranscript, useTurnLatencies, type CallDetail } from "../../api/calls";
import { callbackKeys } from "../../api/callbacks";
import { qualityKeys } from "../../api/quality";
import { problemMessage } from "../../api/problems";
import {
  Badge,
  Button,
  CallStatusBadge,
  CHANNEL_LABELS,
  CopyButton,
  Drawer,
  EmptyState,
  ORIGIN_LABELS,
  REASON_LABELS,
  Skeleton,
  TabPanel,
  Tabs,
  TruncatedText,
} from "../../components";
import { useMediaQuery } from "../../lib/useMediaQuery";
import { CostHeader, CostPanel } from "./CostBreakdown";
import { FlowPath } from "./FlowPath";
import { CallAnalysisPanel } from "./quality/CallAnalysisPanel";
import { QualityChecks } from "./quality/QualityChecks";
import { YourReview } from "./quality/YourReview";
import { LatencyPanel } from "./LatencyPanel";
import { RecordingPlayer } from "./RecordingPlayer";
import { Transcript } from "./Transcript";
import { AddToDatasetMenu } from "../datasets/AddToDatasetMenu";
import { StartSimulationDialog } from "../simulations/StartSimulationDialog";
import { summaryHeadline, summaryOutcome } from "./quality/SummaryText";
import { CallCallbacks } from "./callbacks/CallbackParts";
import { CallLanguageCard } from "./CallLanguageCard";
import { LiveDuration } from "./live/LiveDuration";
import { mss, phone, usd, whenLong } from "../../lib/format";
import { diagnosticText } from "./format";
import { callComparePath } from "../../lib/paths";

export type DrawerTab = "transcript" | "latency" | "cost" | "analysis" | "quality" | "flow";

function Fact({ icon: Icon, label, children }: { icon: LucideIcon; label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 items-start gap-2.5">
      <Icon className="mt-0.5 size-4 shrink-0 text-fg-3" aria-hidden />
      <div className="min-w-0">
        <dt className="text-[12px] text-fg-3">{label}</dt>
        <dd className="min-w-0 text-[13px] text-fg">{children}</dd>
      </div>
    </div>
  );
}

function Header({ call }: { call: CallDetail }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <CallStatusBadge status={call.status} />
        <Badge tone="neutral">{CHANNEL_LABELS[call.channel]}</Badge>
        {call.origin !== "live" && <Badge tone={call.origin === "simulation" ? "accent" : "neutral"}>{ORIGIN_LABELS[call.origin]}</Badge>}
        {call.disconnect_reason && <span className="text-[13px] text-fg-3">{REASON_LABELS[call.disconnect_reason]}</span>}
        <span className="ml-auto flex items-baseline gap-3">
          {call.cost && <CostHeader cost={call.cost} className="hidden sm:flex" />}
          {!isOnAir(call.status) && <span className="font-mono text-[15px] font-semibold text-fg tnum">{usd(call.cost_usd ?? null)}</span>}
        </span>
      </div>
      {call.status === "failed" && diagnosticText(call.diagnostic) && (
        <p role="status" className="rounded-panel border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger-text">
          {diagnosticText(call.diagnostic)}
        </p>
      )}
      <dl className="grid grid-cols-[minmax(0,1fr)] gap-x-6 gap-y-3 rounded-panel border border-line bg-surface-2/50 p-4 sm:grid-cols-2">
        <Fact icon={Bot} label="Agent">
          <span className="flex min-w-0 items-center gap-1.5">
            <TruncatedText>
              {call.agent.name}
              {call.agent.deleted ? " (deleted)" : ""}
            </TruncatedText>
            {call.agent_version_label && <Badge tone="accent">{call.agent_version_label}</Badge>}
          </span>
        </Fact>
        <Fact icon={Hash} label="Call ID">
          <span className="flex min-w-0 items-center gap-1">
            <TruncatedText className="font-mono text-[13px]">{call.call_id}</TruncatedText>
            <CopyButton value={call.call_id} label="Copy call ID" className="-my-1" />
          </span>
        </Fact>
        <Fact icon={PhoneIncoming} label="From and to">
          {call.channel !== "web" && (call.from_number || call.to_number) ? (
            <span className="font-mono text-[13px] tnum">
              {phone(call.from_number) || "Unknown"} <span className="text-fg-3">to</span> {phone(call.to_number) || "Unknown"}
            </span>
          ) : (
            <span className="text-fg-2">Browser call</span>
          )}
        </Fact>
        <Fact icon={Timer} label="Duration">
          {isOnAir(call.status) ? <LiveDuration since={call.connected_at} /> : <span className="font-mono tnum">{mss(call.duration_s)}</span>}
          {call.latency.avg_ms != null && <span className="ml-2 text-fg-3">avg turn {call.latency.avg_ms} ms</span>}
        </Fact>
      </dl>
    </div>
  );
}

/**
 * When the open call answers, ends or finishes processing, the parts that only change at those
 * moments (final transcript, latencies, analysis, checks, a callback booked during the call) are
 * fetched again, so the drawer never shows a stale tab.
 */
function useRefreshOnStatusChange(callId: string, status: string | undefined, processing: string | undefined) {
  const qc = useQueryClient();
  const last = useRef<string | null>(null);
  const key = status ? `${status}:${processing ?? ""}` : null;
  useEffect(() => {
    if (!key) return;
    const before = last.current;
    last.current = key;
    if (before === null || before === key) return;
    for (const k of [callKeys.transcript(callId), callKeys.latencies(callId), callKeys.flow(callId)]) void qc.invalidateQueries({ queryKey: k });
    void qc.invalidateQueries({ queryKey: qualityKeys.analysis(callId) });
    void qc.invalidateQueries({ queryKey: qualityKeys.evaluations(callId) });
    void qc.invalidateQueries({ queryKey: callbackKeys.forCall(callId) });
  }, [key, callId, qc]);
}

function Body({
  callId,
  tab,
  onTab,
  onLabelled,
}: {
  callId: string;
  tab: DrawerTab;
  onTab: (t: DrawerTab) => void;
  onLabelled?: (label: "good" | "bad" | null) => void;
}) {
  const call = useCall(callId);
  const wide = useMediaQuery("(min-width: 640px)");
  const status = call.data?.status;
  const live = status !== undefined && isOnAir(status);
  const transcript = useTranscript(callId, live);
  const latencies = useTurnLatencies(callId, live);
  const flow = useFlowTransitions(callId, live);
  useRefreshOnStatusChange(callId, status, call.data?.processing_state);
  if (call.isError) {
    return (
      <EmptyState compact icon={<PhoneX weight="duotone" />} title="Call not found">
        {problemMessage(call.error, "call")}
      </EmptyState>
    );
  }
  if (!call.data) {
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        <Skeleton className="h-6 w-1/2" />
        <Skeleton className="h-[108px] w-full rounded-panel" />
        <Skeleton className="h-[58px] w-full rounded-panel" />
        <Skeleton className="h-64 w-full rounded-panel" />
      </div>
    );
  }
  const c = call.data;
  const flowItems = flow.data ?? [];
  const icons = wide;

  const tabs = [
    { value: "transcript", label: "Transcript", icon: icons ? <MessagesSquare aria-hidden /> : undefined },
    { value: "latency", label: "Latency", icon: icons ? <ChartNoAxesColumn aria-hidden /> : undefined },
    { value: "cost", label: "Cost", icon: icons ? <Receipt aria-hidden /> : undefined },
    { value: "analysis", label: "Analysis", icon: icons ? <ClipboardText aria-hidden /> : undefined },
    {
      value: "quality",
      label: "Quality",
      icon: icons ? <ShieldCheck aria-hidden /> : undefined,
      ...(c.quality.fail_count ? { alerts: c.quality.fail_count } : {}),
    },
    ...(flowItems.length
      ? [{ value: "flow", label: "Flow path", icon: icons ? <GitBranch aria-hidden /> : undefined, count: flowItems.length }]
      : []),
  ];
  const active = tab === "flow" && !flowItems.length ? "transcript" : tab;
  return (
    <div className="flex flex-col gap-5">
      <Header call={c} />
      {c.summary && <SummaryCard summary={c.summary} onOpen={() => onTab("analysis")} />}
      <CallCallbacks callId={c.call_id} />
      <CallLanguageCard callId={c.call_id} />
      {/* Nothing to play while the call is on air; the recording follows once it ends. */}
      {!live && (
        <RecordingPlayer
          callId={c.call_id}
          hasRecording={c.has_recording}
          durationS={c.duration_s}
          processing={c.processing_state === "pending" || !!c.recording_pending}
        />
      )}
      <Tabs aria-label="Call detail" value={active} onValueChange={(v) => onTab(v as DrawerTab)} items={tabs}>
        <TabPanel value="transcript">
          <Transcript
            items={transcript.data?.items}
            latencies={latencies.data?.turns}
            loading={transcript.isPending}
            processing={c.processing_state === "pending"}
            live={live}
          />
        </TabPanel>
        <TabPanel value="latency">
          <LatencyPanel summary={c.latency} turns={latencies.data?.turns} loading={latencies.isPending} />
        </TabPanel>
        <TabPanel value="cost">
          {c.cost ? (
            <CostPanel cost={c.cost} />
          ) : (
            <EmptyState compact icon={<Receipt />} title={live ? "Cost appears when the call ends" : "Not priced"}>
              {live
                ? "Calls are priced per second once they end."
                : "Calls that never connected, test calls in a free plan and simulations are not charged per call."}
            </EmptyState>
          )}
        </TabPanel>
        <TabPanel value="analysis">
          <CallAnalysisPanel call={c} />
        </TabPanel>
        <TabPanel value="quality">
          <div className="flex flex-col gap-5">
            <YourReview callId={c.call_id} onLabelled={onLabelled} />
            <QualityChecks callId={c.call_id} canRerun={c.status === "completed" || c.status === "voicemail"} />
          </div>
        </TabPanel>
        {flowItems.length > 0 && (
          <TabPanel value="flow">
            <FlowPath items={flowItems} />
          </TabPanel>
        )}
      </Tabs>
    </div>
  );
}

/**
 * Call detail at `/calls?call=<id>` (US2): header with the agent version, recording, then the
 * transcript, latency, cost, analysis and (for flow agents) the flow path. Escape closes it.
 */
export function CallDetailDrawer({
  callId,
  tab,
  onTab,
  onClose,
  onLabelled,
  footer,
}: {
  callId: string | null;
  tab: DrawerTab;
  onTab: (t: DrawerTab) => void;
  onClose: () => void;
  /** 007: called after the viewer labels the call (the review queue offers the next call). */
  onLabelled?: (label: "good" | "bad" | null) => void;
  footer?: ReactNode;
}) {
  const [lastId, setLastId] = useState(callId);
  if (callId && callId !== lastId) setLastId(callId);
  const shown = callId ?? lastId;
  const call = useCall(shown);
  const [simulating, setSimulating] = useState(false);
  const c = call.data;
  // 008: only completed live calls can be replayed or kept in a dataset.
  const simulatable = Boolean(c && c.origin !== "simulation" && c.status === "completed");
  return (
    <>
      <Drawer
        open={Boolean(callId)}
        onOpenChange={(o) => !o && onClose()}
        width="xl"
        footer={footer}
        title={call.data ? `Call with ${call.data.agent.name}` : "Call"}
        meta={call.data ? whenLong(call.data.started_at) : undefined}
        actions={
          shown ? (
            <>
              {simulatable && c && (
                <>
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={<FlaskConical aria-hidden />}
                    aria-label="Simulate this call"
                    onClick={() => setSimulating(true)}
                  >
                    <span className="hidden sm:inline">Simulate</span>
                  </Button>
                  <AddToDatasetMenu agentId={c.agent.id} callIds={[c.call_id]} compact />
                </>
              )}
              <Button asChild size="sm" variant="secondary" icon={<ArrowLeftRight aria-hidden />}>
                <Link to={callComparePath(shown)} aria-label="Compare with another call">
                  <span className="hidden sm:inline">Compare</span>
                </Link>
              </Button>
            </>
          ) : null
        }
      >
        {shown && <Body callId={shown} tab={tab} onTab={onTab} onLabelled={onLabelled} />}
      </Drawer>
      {simulating && c && (
        <StartSimulationDialog open onOpenChange={setSimulating} agentId={c.agent.id} agentName={c.agent.name} baseCallIds={[c.call_id]} />
      )}
    </>
  );
}

/** The summary's headline (and outcome) at the top of the drawer; the full one is on Analysis. */
function SummaryCard({ summary, onOpen }: { summary: string; onOpen: () => void }) {
  const outcome = summaryOutcome(summary);
  return (
    <section aria-label="Summary" className="flex items-start gap-3 rounded-panel border border-line bg-surface px-4 py-3.5">
      <span className="grid size-7 shrink-0 place-items-center rounded-control bg-accent-soft text-accent-text" aria-hidden>
        <ClipboardText className="size-3.5" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[14px] font-medium leading-relaxed text-fg">{summaryHeadline(summary)}</p>
        {outcome && (
          <p className="mt-1 text-[13px] leading-relaxed text-fg-2">
            <span className="font-semibold text-fg">Outcome </span>
            {outcome}
          </p>
        )}
        <button type="button" onClick={onOpen} className="link-underline mt-1.5 text-[13px] font-medium text-accent-text">
          Full summary
        </button>
      </div>
    </section>
  );
}
