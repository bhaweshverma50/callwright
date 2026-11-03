import { ChatsCircle } from "@phosphor-icons/react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { AlertTriangle, Bot, CheckCircle2, ChevronDown, Scissors, User, Wrench } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import type { TranscriptItem, TurnLatency } from "../../api/calls";
import { Badge, CopyButton, EmptyState, OnAir, Skeleton, Tooltip, Waveform, cn, focusRing } from "../../components";
import { mss } from "./format";

const VIRTUAL_AFTER = 500;

/** JSON with ", " and ": " separators, as the API writes tool arguments. */
function spacedJson(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(spacedJson).join(", ")}]`;
  if (v && typeof v === "object") {
    return `{${Object.entries(v as Record<string, unknown>)
      .map(([k, x]) => `${JSON.stringify(k)}: ${spacedJson(x)}`)
      .join(", ")}}`;
  }
  return JSON.stringify(v) ?? "null";
}

/** The plain-text copy (FR-010); the same format as the API's `transcript_text`. */
export function transcriptText(items: TranscriptItem[]): string {
  return items
    .map((i) => {
      if (i.type === "message") return `${i.role === "user" ? "Caller" : "Agent"}: ${i.text}`;
      if (i.type === "tool_call") return `[Tool call: ${i.tool_name}(${spacedJson(i.arguments)})]`;
      return `[${i.is_error ? "Tool error" : "Tool result"}: ${i.tool_name} -> ${i.output}]`;
    })
    .join("\n");
}

const PARTS: [keyof TurnLatency, string, string][] = [
  ["stt_final_ms", "Speech to text", "var(--heat-1)"],
  ["llm_ttft_ms", "Model first token", "var(--heat-2)"],
  ["tts_ttfb_ms", "Voice first audio", "var(--heat-3)"],
];

/** End-to-end latency of one agent turn with its measured parts; a missing part reads "n/a". */
export function TurnLatencyChip({ turn }: { turn: TurnLatency }) {
  const known = PARTS.map(([k]) => turn[k] as number | null | undefined);
  const sum = known.reduce<number>((a, v) => a + (v ?? 0), 0);
  const e2e = turn.e2e_ms ?? null;
  const tone = e2e === null ? "text-fg-3" : e2e <= 1000 ? "text-success-text" : e2e <= 1600 ? "text-warning-text" : "text-danger-text";
  const label = `Answered in ${e2e === null ? "n/a" : `${e2e} milliseconds`}: ${PARTS.map(
    ([k, name]) => `${name.toLowerCase()} ${turn[k] ?? "n/a"}`,
  ).join(", ")}`;
  return (
    <Tooltip
      content={
        <span className="flex flex-col gap-1 py-0.5 text-[12px]">
          {PARTS.map(([k, name, color]) => (
            <span key={k} className="flex items-center justify-between gap-6">
              <span className="flex items-center gap-1.5">
                <span className="size-2 rounded-full" style={{ background: color }} aria-hidden />
                {name}
              </span>
              <span className="font-mono tnum">{turn[k] == null ? "n/a" : `${turn[k]} ms`}</span>
            </span>
          ))}
        </span>
      }
    >
      <span
        role="img"
        tabIndex={0}
        aria-label={label}
        className={cn("inline-flex h-6 cursor-default items-center gap-2 rounded-full border border-line bg-surface px-2", focusRing)}
      >
        <span className="flex h-1.5 w-12 overflow-hidden rounded-full bg-surface-3" aria-hidden>
          {sum > 0 &&
            PARTS.map(([k, , color]) =>
              turn[k] == null ? null : (
                <span key={k} style={{ width: `${((turn[k] as number) / Math.max(sum, e2e ?? 0)) * 100}%`, background: color }} />
              ),
            )}
        </span>
        <span className={cn("font-mono text-[11.5px] tnum", tone)}>{e2e === null ? "n/a" : `${e2e} ms`}</span>
      </span>
    </Tooltip>
  );
}

function ToolCall({
  item,
  result,
}: {
  item: Extract<TranscriptItem, { type: "tool_call" }>;
  result?: Extract<TranscriptItem, { type: "tool_result" }>;
}) {
  const [open, setOpen] = useState(false);
  const error = result?.is_error;
  const args = JSON.stringify(item.arguments, null, 2);
  return (
    <div
      className={cn(
        "ml-10 overflow-hidden rounded-control border bg-surface-2/60 text-[12.5px]",
        error ? "border-danger-text/30 bg-danger-soft/40" : "border-line",
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={cn("flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left hover:bg-surface-3/50", focusRing)}
      >
        <Wrench className="size-3.5 shrink-0 text-fg-3" aria-hidden />
        <span className="font-mono text-[12px] text-fg">{item.tool_name}</span>
        {result ? (
          error ? (
            <Badge tone="danger" icon={<AlertTriangle aria-hidden />}>
              Error
            </Badge>
          ) : (
            <Badge tone="success" icon={<CheckCircle2 aria-hidden />}>
              Done
            </Badge>
          )
        ) : (
          <Badge>No result</Badge>
        )}
        {result?.duration_ms != null && (
          <span className="whitespace-nowrap font-mono text-[11.5px] text-fg-3 tnum">{result.duration_ms.toLocaleString()} ms</span>
        )}
        <span className="ml-auto hidden font-mono text-[11px] text-fg-3 tnum sm:inline">{mss(item.offset_ms / 1000)}</span>
        <ChevronDown className={cn("size-3.5 text-fg-3 transition-transform duration-200", open && "rotate-180")} aria-hidden />
      </button>
      {open && (
        <div className="grid gap-2 border-t border-line px-3 py-2.5 sm:grid-cols-2">
          <div className="min-w-0">
            <p className="mb-1 text-[11.5px] text-fg-3">Arguments</p>
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-inline bg-surface px-2 py-1.5 font-mono text-[11.5px] text-fg-2">
              {args}
            </pre>
          </div>
          <div className="min-w-0">
            <p className="mb-1 text-[11.5px] text-fg-3">{error ? "Error" : "Result"}</p>
            <pre
              className={cn(
                "max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-inline bg-surface px-2 py-1.5 font-mono text-[11.5px]",
                error ? "text-danger-text" : "text-fg-2",
              )}
            >
              {result?.output ?? "No result was recorded."}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

function Message({ item, latency }: { item: Extract<TranscriptItem, { type: "message" }>; latency?: TurnLatency }) {
  const agent = item.role === "agent";
  return (
    <div className="flex items-start gap-3">
      <span
        className={cn(
          "mt-0.5 grid size-7 shrink-0 place-items-center rounded-full [&_svg]:size-3.5",
          agent ? "grad-action text-white" : "bg-surface-3 text-fg-2",
        )}
        aria-hidden
      >
        {agent ? <Bot /> : <User />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-[12.5px] font-medium text-fg">{agent ? "Agent" : "Caller"}</span>
          <span className="font-mono text-[11px] text-fg-3 tnum">{mss(item.offset_ms / 1000)}</span>
          {agent && latency && <TurnLatencyChip turn={latency} />}
          {!agent && item.stt_confidence != null && (
            <Tooltip content="Speech recognition confidence for these words (about 85% is normal on phone audio)">
              <span tabIndex={0} className={cn("rounded-inline font-mono text-[11px] text-fg-3 tnum", focusRing)}>
                {Math.round(item.stt_confidence * 100)}% sure
              </span>
            </Tooltip>
          )}
          {item.interrupted && (
            <Badge tone="warning" icon={<Scissors aria-hidden />}>
              Interrupted
            </Badge>
          )}
        </div>
        <p className={cn("text-[13.5px] leading-relaxed text-fg-2", item.interrupted && "text-fg-3")}>
          {item.text}
          {item.interrupted && <span aria-hidden> ...</span>}
        </p>
      </div>
    </div>
  );
}

type Row =
  | { kind: "message"; item: Extract<TranscriptItem, { type: "message" }> }
  | { kind: "tool"; item: Extract<TranscriptItem, { type: "tool_call" }>; result?: Extract<TranscriptItem, { type: "tool_result" }> }
  | { kind: "orphan"; item: Extract<TranscriptItem, { type: "tool_result" }> };

/** Groups each tool result under its call so a tool reads as one item. */
export function transcriptRows(items: TranscriptItem[]): Row[] {
  const results = new Map<string, Extract<TranscriptItem, { type: "tool_result" }>>();
  for (const i of items) if (i.type === "tool_result" && i.tool_call_id) results.set(i.tool_call_id, i);
  const used = new Set<string>();
  const rows: Row[] = [];
  for (const i of items) {
    if (i.type === "message") rows.push({ kind: "message", item: i });
    else if (i.type === "tool_call") {
      const r = results.get(i.id);
      if (r) used.add(r.id);
      rows.push({ kind: "tool", item: i, result: r });
    } else if (!used.has(i.id) && !results.has(i.tool_call_id)) rows.push({ kind: "orphan", item: i });
  }
  return rows;
}

function RowView({ row, latencies }: { row: Row; latencies: Map<number, TurnLatency> }) {
  if (row.kind === "message") {
    const latency = row.item.turn_index != null ? latencies.get(row.item.turn_index) : undefined;
    return <Message item={row.item} latency={latency} />;
  }
  if (row.kind === "tool") return <ToolCall item={row.item} result={row.result} />;
  return (
    <ToolCall
      item={{ id: row.item.id, type: "tool_call", tool_name: row.item.tool_name, arguments: {}, offset_ms: row.item.offset_ms }}
      result={row.item}
    />
  );
}

/**
 * The call as a conversation (FR-009): caller and agent turns, tool calls with their result inline,
 * an "Interrupted" marker, recognition confidence and a latency chip on every agent turn. Very long
 * transcripts render virtualised so the drawer never freezes.
 */
export function Transcript({
  items,
  latencies,
  loading,
  processing,
  live,
}: {
  items: TranscriptItem[] | undefined;
  latencies: TurnLatency[] | undefined;
  loading?: boolean;
  processing?: boolean;
  /** The call is ringing or on air: lines arrive as they are spoken and new ones ease in. */
  live?: boolean;
}) {
  const byTurn = new Map((latencies ?? []).map((t) => [t.turn_index, t]));
  if (loading && !items) {
    return (
      <div className="flex flex-col gap-5" aria-hidden>
        {Array.from({ length: 5 }, (_, i) => (
          <div key={i} className="flex gap-3">
            <Skeleton className="size-7 rounded-full" />
            <div className="flex flex-1 flex-col gap-2">
              <Skeleton className="h-3 w-24" />
              <Skeleton className={cn("h-3.5", i % 2 ? "w-2/3" : "w-11/12")} />
            </div>
          </div>
        ))}
      </div>
    );
  }
  if ((!items || items.length === 0) && live) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-panel border border-dashed border-line-strong/80 px-6 py-8 text-center">
        <OnAir label="Live transcript" />
        <Waveform quiet bars={28} height={22} className="max-w-[180px]" />
        <p className="max-w-[34ch] text-[12.5px] text-fg-3">Waiting for the first words. Lines appear here a few seconds after they are spoken.</p>
      </div>
    );
  }
  if (!items || items.length === 0) {
    return (
      <EmptyState compact icon={<ChatsCircle weight="duotone" />} title={processing ? "Transcript on its way" : "No transcript"}>
        {processing ? "The transcript is ready once the call finishes processing." : "Nobody spoke on this call, or it never connected."}
      </EmptyState>
    );
  }
  const rows = transcriptRows(items);
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        {live && <OnAir label="Live" />}
        <p className={cn("text-[12.5px] text-fg-3", live && "mr-auto")}>
          <span className="font-mono tnum">{items.filter((i) => i.type === "message").length}</span> turns,{" "}
          <span className="font-mono tnum">{items.filter((i) => i.type === "tool_call").length}</span> tool calls
        </p>
        <span className="flex items-center gap-1 text-[12.5px] text-fg-2">
          Copy transcript
          <CopyButton value={transcriptText(items)} label="Copy transcript" />
        </span>
      </div>
      {rows.length > VIRTUAL_AFTER ? <VirtualRows rows={rows} latencies={byTurn} /> : <PlainRows rows={rows} latencies={byTurn} live={live} />}
    </div>
  );
}

function PlainRows({ rows, latencies, live }: { rows: Row[]; latencies: Map<number, TurnLatency>; live?: boolean }) {
  const reduce = useReducedMotion();
  const end = useRef<HTMLLIElement>(null);
  const following = useRef(true);
  // Follow a live call: when the newest line was on screen, keep it there as lines arrive. A
  // reader who scrolled up to an earlier line is left where they are.
  useEffect(() => {
    const el = end.current;
    if (!live || !el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(([e]) => (following.current = Boolean(e?.isIntersecting)));
    io.observe(el);
    return () => io.disconnect();
  }, [live, rows.length]);
  useEffect(() => {
    if (live && following.current) end.current?.scrollIntoView?.({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
  }, [live, rows.length, reduce]);
  return (
    <ol className="flex flex-col gap-4">
      {rows.map((r, i) => (
        <motion.li
          key={r.item.id}
          ref={i === rows.length - 1 ? end : undefined}
          initial={live ? { opacity: 0, y: 6 } : false}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
        >
          <RowView row={r} latencies={latencies} />
        </motion.li>
      ))}
    </ol>
  );
}

function VirtualRows({ rows, latencies }: { rows: Row[]; latencies: Map<number, TurnLatency> }) {
  const parent = useRef<HTMLDivElement>(null);
  const v = useVirtualizer({ count: rows.length, getScrollElement: () => parent.current, estimateSize: () => 72, overscan: 8 });
  return (
    <div ref={parent} className="h-[70vh] overflow-y-auto pr-1" data-testid="virtual-transcript">
      <ol className="relative w-full" style={{ height: v.getTotalSize() }}>
        {v.getVirtualItems().map((vi) => (
          <li
            key={vi.key}
            data-index={vi.index}
            ref={v.measureElement}
            className="absolute left-0 top-0 w-full pb-4"
            style={{ transform: `translateY(${vi.start}px)` }}
          >
            <RowView row={rows[vi.index]!} latencies={latencies} />
          </li>
        ))}
      </ol>
    </div>
  );
}
