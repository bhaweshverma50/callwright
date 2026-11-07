import {
  Globe,
  MessageCircle,
  MessagesSquare,
  PhoneIncoming,
  PhoneOutgoing,
  ShieldCheck,
  ShieldAlert,
  ShieldQuestion,
  ThumbsDown,
  ThumbsUp,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useState, type ReactNode } from "react";
import type { CallListItem, Channel } from "../../api/calls";
import { Badge, IconButton, Tooltip, TruncatedText, cn, focusRing } from "../../components";
import { SentimentBadge } from "./AnalysisTable";
import { StatusBadge } from "./CallDetailDrawer";
import { CostCell } from "./CostBreakdown";
import { CHANNEL_LABELS, EVAL_LABELS, REASON_LABELS, type SortKey } from "./filters";
import { latencyTone, mss, phone, when } from "./format";
import type { DrawerTab } from "./CallDetailDrawer";
import { LiveDuration } from "./live/LiveDuration";
import { RecordingPlayer } from "./RecordingPlayer";
import { summaryHeadline } from "./quality/SummaryText";

export const CHANNEL_ICONS: Record<Channel, LucideIcon> = {
  web: Globe,
  sip_inbound: PhoneIncoming,
  sip_outbound: PhoneOutgoing,
  whatsapp: MessageCircle,
};

export interface CellContext {
  open: (id: string, tab?: DrawerTab) => void;
}

export interface CallColumn {
  key: string;
  label: string;
  /** Call ID, start time and status can never be hidden (FR-034). */
  required?: boolean;
  sort?: SortKey;
  numeric?: boolean;
  width?: string;
  cell: (row: CallListItem, ctx: CellContext) => ReactNode;
}

const TONE_TEXT = { success: "text-success-text", warning: "text-warning-text", danger: "text-danger-text", neutral: "text-fg-3", accent: "text-fg" };

function QualityCell({ q }: { q: CallListItem["quality"] }) {
  const icon =
    q.eval_status === "passed" ? (
      <ShieldCheck className="size-3.5 text-success-text" aria-hidden />
    ) : q.eval_status === "failed" || q.eval_status === "error" ? (
      <ShieldAlert className="size-3.5 text-danger-text" aria-hidden />
    ) : (
      <ShieldQuestion className="size-3.5 text-fg-3" aria-hidden />
    );
  return (
    <span className="flex items-center gap-2 whitespace-nowrap">
      <span className="flex items-center gap-1 text-[13px] text-fg-2">
        {icon}
        {q.eval_status === "not_evaluated" ? <span className="text-fg-3">Not evaluated</span> : EVAL_LABELS[q.eval_status]}
        {(q.pass_count > 0 || q.fail_count > 0) && (
          <span className="font-mono text-[12px] text-fg-3 tnum">
            {q.pass_count}/{q.pass_count + q.fail_count}
          </span>
        )}
      </span>
      {q.label === "good" && <ThumbsUp className="size-3.5 text-success-text" aria-label="You labelled it good" />}
      {q.label === "bad" && <ThumbsDown className="size-3.5 text-danger-text" aria-label="You labelled it bad" />}
    </span>
  );
}

/** Why a call has no summary, from the list's analysis_status. */
const NO_SUMMARY: Record<string, string> = {
  running: "Analysing",
  too_short: "Too short to analyse",
  not_run: "Not analysed",
  error: "Analysis failed",
  insufficient_credit: "Skipped: no credit",
};

function AnalysisCell({ values }: { values: CallListItem["analysis_values"] }) {
  const entries = Object.entries(values ?? {});
  if (!entries.length) return <span className="text-fg-3">None</span>;
  return (
    <Tooltip
      content={
        <span className="flex flex-col gap-0.5 text-[12px]">
          {entries.slice(0, 8).map(([k, v]) => (
            <span key={k}>
              <span className="font-mono">{k}</span>: {typeof v === "object" ? JSON.stringify(v) : String(v)}
            </span>
          ))}
        </span>
      }
    >
      <span tabIndex={0} className={cn("inline-flex rounded-full", focusRing)}>
        <Badge tone="accent">{entries.length} values</Badge>
      </span>
    </Tooltip>
  );
}

const ALL: CallColumn[] = [
  {
    key: "call_id",
    label: "Call ID",
    required: true,
    width: "150px",
    cell: (r, ctx) => (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          ctx.open(r.call_id);
        }}
        className={cn(
          "block max-w-[140px] cursor-pointer rounded-inline text-left font-mono text-[12px] text-accent-text hover:underline",
          focusRing,
        )}
        aria-label={`Open call ${r.call_id}`}
      >
        <TruncatedText focusable={false}>{r.call_id}</TruncatedText>
      </button>
    ),
  },
  {
    key: "started_at",
    label: "Start time",
    required: true,
    sort: "started_at",
    cell: (r) => (
      <span className="flex items-center gap-1.5 whitespace-nowrap text-fg-2">
        {when(r.started_at)}
        {r.origin === "simulation" && <Badge tone="accent">Simulated</Badge>}
        {r.origin === "test" && <Badge>Test</Badge>}
      </span>
    ),
  },
  {
    key: "agent",
    label: "Agent",
    cell: (r) => (
      <span className="flex min-w-0 max-w-[190px] flex-col">
        <TruncatedText className="text-fg">
          {r.agent.name}
          {r.agent.deleted ? " (deleted)" : ""}
        </TruncatedText>
        <TruncatedText className="font-mono text-[11px] text-fg-3">{r.agent.id}</TruncatedText>
      </span>
    ),
  },
  {
    key: "from_number",
    label: "From",
    cell: (r) =>
      r.channel === "web" && !r.from_number ? (
        <span className="text-[13px] text-fg-3">Browser</span>
      ) : (
        <span className="whitespace-nowrap font-mono text-[12px] text-fg-2 tnum">
          {phone(r.from_number) || <span className="text-fg-3">n/a</span>}
        </span>
      ),
  },
  {
    key: "to_number",
    label: "To",
    cell: (r) =>
      r.channel === "web" && !r.to_number ? null : (
        <span className="whitespace-nowrap font-mono text-[12px] text-fg-2 tnum">{phone(r.to_number) || <span className="text-fg-3">n/a</span>}</span>
      ),
  },
  {
    key: "channel",
    label: "Channel",
    cell: (r) => {
      const Icon = CHANNEL_ICONS[r.channel];
      return (
        <span className="flex items-center gap-1.5 whitespace-nowrap text-fg-2">
          <Icon className="size-3.5 text-fg-3" aria-hidden />
          {CHANNEL_LABELS[r.channel]}
        </span>
      );
    },
  },
  {
    key: "disconnect_reason",
    label: "Ended by",
    cell: (r) => (
      <span className="whitespace-nowrap text-fg-2">
        {r.disconnect_reason ? REASON_LABELS[r.disconnect_reason] : <span className="text-fg-3">n/a</span>}
      </span>
    ),
  },
  {
    key: "duration_s",
    label: "Duration",
    sort: "duration_s",
    numeric: true,
    cell: (r) =>
      r.status === "in_progress" ? (
        <LiveDuration since={r.connected_at} className="text-fg" />
      ) : r.status === "ringing" || r.status === "queued" ? (
        <span className="font-sans text-fg-3">Ringing</span>
      ) : (
        mss(r.duration_s)
      ),
  },
  { key: "status", label: "Status", required: true, cell: (r) => <StatusBadge status={r.status} /> },
  { key: "cost_usd", label: "Cost", sort: "cost_usd", numeric: true, cell: (r) => <CostCell callId={r.call_id} value={r.cost_usd} /> },
  {
    key: "latency_avg_ms",
    label: "Avg latency",
    sort: "latency_avg_ms",
    numeric: true,
    cell: (r) =>
      r.latency_avg_ms == null ? (
        <span className="text-fg-3">n/a</span>
      ) : (
        <span className={TONE_TEXT[latencyTone(r.latency_avg_ms)]}>{r.latency_avg_ms} ms</span>
      ),
  },
  {
    key: "recording",
    label: "Recording",
    cell: (r) => (
      <RecordingPlayer compact callId={r.call_id} hasRecording={r.has_recording} durationS={r.duration_s} processing={r.status === "processing"} />
    ),
  },
  {
    key: "transcript",
    label: "Transcript",
    cell: (r, ctx) => (
      <IconButton
        label="Open transcript"
        onClick={(e) => {
          e.stopPropagation();
          ctx.open(r.call_id, "transcript");
        }}
      >
        <MessagesSquare className="size-4" aria-hidden />
      </IconButton>
    ),
  },
  {
    key: "summary",
    label: "Summary",
    cell: (r) =>
      r.summary ? (
        <TruncatedText className="block max-w-[260px] text-fg-2">{summaryHeadline(r.summary)}</TruncatedText>
      ) : (
        <span className="text-fg-3">{NO_SUMMARY[r.analysis_status ?? "not_run"] ?? "n/a"}</span>
      ),
  },
  { key: "sentiment", label: "Sentiment", cell: (r) => <SentimentBadge value={r.sentiment} /> },
  { key: "analysis", label: "Extracted values", cell: (r) => <AnalysisCell values={r.analysis_values} /> },
  { key: "quality", label: "Quality", cell: (r) => <QualityCell q={r.quality} /> },
];

/** Every FR-002 column, in display order: identity, outcome and money first, detail after. */
const ORDER = [
  "call_id",
  "started_at",
  "status",
  "agent",
  "duration_s",
  "cost_usd",
  "latency_avg_ms",
  "recording",
  "transcript",
  "channel",
  "from_number",
  "to_number",
  "disconnect_reason",
  "sentiment",
  "summary",
  "analysis",
  "quality",
];
export const COLUMNS: CallColumn[] = ORDER.map((k) => ALL.find((c) => c.key === k)!);

/** The CSV columns each list column exports (calls.yaml ExportColumn). */
export const EXPORT_KEYS: Record<string, components["schemas"]["ExportColumn"][]> = {
  call_id: ["call_id"],
  started_at: ["started_at"],
  agent: ["agent_id", "agent_name"],
  from_number: ["from_number"],
  to_number: ["to_number"],
  channel: ["channel"],
  disconnect_reason: ["disconnect_reason"],
  duration_s: ["duration_s"],
  status: ["status"],
  cost_usd: ["cost_usd"],
  latency_avg_ms: ["latency_avg_ms"],
  recording: ["has_recording"],
  summary: ["summary"],
  sentiment: ["sentiment"],
  analysis: ["analysis_values"],
  quality: ["eval_status", "label"],
};

const STORAGE_KEY = "cw.calls.columns.hidden";

function readHidden(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const keys = raw ? (JSON.parse(raw) as unknown) : [];
    return new Set(Array.isArray(keys) ? keys.filter((k): k is string => typeof k === "string") : []);
  } catch {
    return new Set();
  }
}

/** Hidden columns, kept in this browser (FR-034). Required columns are never hidden. */
export function useColumnVisibility() {
  const [hidden, setHidden] = useState<Set<string>>(readHidden);
  const toggle = useCallback((key: string) => {
    if (COLUMNS.find((c) => c.key === key)?.required) return;
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify([...next]));
      } catch {
        /* storage blocked: the choice lasts for this visit */
      }
      return next;
    });
  }, []);
  const visible = COLUMNS.filter((c) => c.required || !hidden.has(c.key));
  return { hidden, toggle, visible };
}
