/**
 * Comparison `/simulations/runs/:runId` (US2, US4; T058, FR-019): the original and simulated
 * transcripts side by side with the flow nodes visited on each side, where a replay diverged and
 * the caller turns it never used, tool calls badged by what answered them, the persona brief, and
 * every check's verdict on both sides with the change. A standalone persona run has no original
 * side. While the run is queued or running the page polls every 3 s.
 */
import { Flask } from "@phosphor-icons/react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Bot, ChevronLeft, CircleStop, GitBranch, Loader2, Split, User, Wrench, LoaderCircle } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useParams } from "react-router";
import { isApiError } from "../../api/errors";
import {
  cancelSimulationRun,
  isSimActive,
  simKeys,
  useComparison,
  useSimulationRun,
  type ConversationSide,
  type SimTranscriptItem,
  type SimulationRun,
  type VerdictDiff,
} from "../../api/simulations";
import { Badge, Button, EmptyState, PageHeader, Panel, PanelLoader, Segmented, Skeleton, Table, cn, toast, type Column } from "../../components";
import { useMediaQuery } from "../../lib/useMediaQuery";
import { RecordNotFound } from "../NotFound";
import { whenLong } from "../calls/format";
import { FormAlert } from "../public/FormAlert";
import { PersonaBriefView } from "./PersonaBriefEditor";
import {
  ANSWER_SOURCES,
  AnswerSourceBadge,
  CHANGE,
  END_REASONS,
  MODE_LABELS,
  ProblemAlert,
  SimStatusBadge,
  VerdictBadge,
  cost,
  problemText,
  targetText,
} from "./shared";
import { withoutLineRefs } from "../../lib/text";

/** 1-based caller turn number for each user message, so divergence can be marked. */
function callerTurns(items: SimTranscriptItem[]): Map<number, number> {
  const out = new Map<number, number>();
  let n = 0;
  items.forEach((it, i) => {
    if (it.type === "message" && it.role === "user") out.set(i, ++n);
  });
  return out;
}

function prettyArgs(raw: string | undefined): string {
  if (!raw) return "";
  try {
    return JSON.stringify(JSON.parse(raw));
  } catch {
    return raw;
  }
}

function Item({ item, turn, diverged }: { item: SimTranscriptItem; turn: number | undefined; diverged: boolean }) {
  if (item.type === "message") {
    const caller = item.role === "user";
    return (
      <li className={cn("flex gap-2.5 px-4 py-2.5", diverged && "bg-warning-soft/40")}>
        <span
          className={cn(
            "mt-0.5 grid size-6 shrink-0 place-items-center rounded-full [&_svg]:size-3.5",
            caller ? "bg-surface-3 text-fg-2" : "bg-accent-soft text-accent-text",
          )}
          aria-hidden
        >
          {caller ? <User /> : <Bot />}
        </span>
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="flex items-center gap-2 text-[12px] text-fg-3">
            {caller ? "Caller" : "Agent"}
            {turn !== undefined && <span className="font-mono tnum">turn {turn}</span>}
          </span>
          <p className="whitespace-pre-wrap break-words text-[13.5px] leading-relaxed text-fg">{item.content}</p>
        </div>
      </li>
    );
  }
  if (item.type === "function_call") {
    return (
      <li className="flex gap-2.5 px-4 py-1.5">
        <span className="mt-0.5 grid size-6 shrink-0 place-items-center text-fg-3" aria-hidden>
          <Wrench className="size-3.5" />
        </span>
        <p className="min-w-0 break-all font-mono text-[12px] text-fg-2">
          {item.name}({prettyArgs(item.arguments)})
        </p>
      </li>
    );
  }
  return (
    <li className="flex gap-2.5 px-4 py-1.5">
      <span className="mt-0.5 grid size-6 shrink-0 place-items-center text-fg-3" aria-hidden>
        <ArrowRight className="size-3.5" />
      </span>
      <div className="flex min-w-0 flex-col gap-1">
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[12px] text-fg-3">{item.name}</span>
          {item.answer_source && <AnswerSourceBadge source={item.answer_source} />}
          {item.is_error && <Badge tone="danger">Tool error</Badge>}
        </span>
        <p className={cn("break-all font-mono text-[12px]", item.is_error ? "text-danger-text" : "text-fg-2")}>{item.output}</p>
      </div>
    </li>
  );
}

function NodePath({ side }: { side: ConversationSide }) {
  if (!side.node_path.length) return null;
  return (
    <ol className="flex flex-wrap items-center gap-1.5 border-b border-line px-4 py-2.5" aria-label="Flow nodes visited">
      <GitBranch className="mr-0.5 size-3.5 text-fg-3" aria-hidden />
      {side.node_path.map((n, i) => (
        <li key={`${n.node_id}-${i}`} className="flex items-center gap-1.5">
          {i > 0 && <ArrowRight className="size-3 text-fg-3" aria-hidden />}
          <Badge tone="neutral">{n.node_label ?? n.node_id}</Badge>
        </li>
      ))}
    </ol>
  );
}

function TranscriptPanel({
  title,
  side,
  divergedAt,
  extra,
  meta,
}: {
  title: string;
  side: ConversationSide;
  divergedAt: number | null;
  extra?: ReactNode;
  meta?: ReactNode;
}) {
  const turns = callerTurns(side.transcript);
  let reached = false;
  return (
    <section aria-label={title} className="flex min-w-0 flex-col overflow-hidden rounded-panel border border-line bg-surface shadow-1">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-4 py-3">
        <h2 className="text-[14px] font-semibold text-fg">{title}</h2>
        <Link to={`/calls?call=${side.call_id}`} className="min-w-0 truncate font-mono text-[11.5px] text-fg-3 hover:text-fg hover:underline">
          {side.call_id}
        </Link>
        {meta}
      </header>
      <NodePath side={side} />
      {side.transcript.length === 0 && (
        <p role="status" className="flex items-center gap-2 px-4 py-6 text-[13px] text-fg-3">
          <LoaderCircle className="size-4 animate-spin" aria-hidden />
          Writing the transcript. It appears a few seconds after the run ends.
        </p>
      )}
      <ol className="max-h-[68vh] overflow-y-auto py-1.5" aria-label={`${title} transcript`}>
        {side.transcript.map((it, i) => {
          const turn = turns.get(i);
          const marker = divergedAt !== null && turn === divergedAt;
          if (marker) reached = true;
          return (
            <FragmentWithMarker key={i} marker={marker} turn={divergedAt}>
              <Item item={it} turn={turn} diverged={reached && it.type === "message" && it.role === "user"} />
            </FragmentWithMarker>
          );
        })}
      </ol>
      {extra}
    </section>
  );
}

function FragmentWithMarker({ marker, turn, children }: { marker: boolean; turn: number | null; children: ReactNode }) {
  return (
    <>
      {marker && (
        <li className="flex items-center gap-2 px-4 py-1.5 text-[12px] font-medium text-warning-text" aria-label={`Diverged at turn ${turn}`}>
          <Split className="size-3.5" aria-hidden />
          Diverged at turn {turn}
          <span className="h-px flex-1 bg-warning/40" aria-hidden />
        </li>
      )}
      {children}
    </>
  );
}

/** Scores are raw evaluator numbers (fractions, counts or milliseconds); never print float noise. */
function fmtScore(n: number | null | undefined): string {
  if (n == null) return "n/a";
  return Math.abs(n) >= 10 ? Math.round(n).toLocaleString() : String(Math.round(n * 100) / 100);
}

/** Checks that need call audio can never run on a text simulation; list them once instead of as rows. */
const audioOnly = (v: VerdictDiff) => v.simulated === "not_applicable" && /no (audio|recording)/i.test(v.simulated_reason ?? "");

const VERDICT_COLUMNS: Column<VerdictDiff>[] = [
  {
    key: "check",
    header: "Check",
    cell: (v) => (
      <span className="flex flex-col gap-0.5">
        <span className="flex items-baseline gap-1.5 whitespace-nowrap">
          <span className="font-medium text-fg">{v.evaluator_display_name}</span>
          <span className="font-mono text-[11px] text-fg-3">v{v.evaluator_version}</span>
        </span>
        {v.node_id && <span className="text-[12px] text-fg-3">Node {v.node_id}</span>}
      </span>
    ),
  },
  { key: "original", header: "Original", cell: (v) => <VerdictBadge verdict={v.original} /> },
  { key: "simulated", header: "Simulated", cell: (v) => <VerdictBadge verdict={v.simulated} /> },
  { key: "change", header: "Change", cell: (v) => <Badge tone={CHANGE[v.change].tone}>{CHANGE[v.change].label}</Badge> },
  {
    key: "why",
    header: "Why, on the simulated call",
    cell: (v) => (
      <p className="min-w-[260px] max-w-[60ch] whitespace-normal py-2 text-[12.5px] leading-relaxed text-fg-2">
        {withoutLineRefs(v.simulated_reason) ?? "No rationale"}
        {v.original_score != null || v.simulated_score != null ? (
          <span className="mt-1 block font-mono text-[11.5px] text-fg-3 tnum">
            Score {fmtScore(v.original_score)} to {fmtScore(v.simulated_score)}
          </span>
        ) : null}
      </p>
    ),
  },
];

function Summary({ run }: { run: SimulationRun }) {
  const counts = run.answer_source_counts ?? {};
  const sources = (Object.keys(ANSWER_SOURCES) as (keyof typeof ANSWER_SOURCES)[]).filter((k) => (counts[k] ?? 0) > 0);
  return (
    <section
      aria-label="Run summary"
      className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-panel border border-line bg-surface px-5 py-3.5 shadow-1"
    >
      <SimStatusBadge status={run.status} />
      <span className="text-[12.5px] text-fg-2">
        <span className="text-fg-3">Mode </span>
        {MODE_LABELS[run.mode]}
      </span>
      <span className="text-[12.5px] text-fg-2">
        <span className="text-fg-3">Target </span>
        {targetText(run)}
      </span>
      {run.end_reason && <span className="text-[12.5px] text-fg-2">{END_REASONS[run.end_reason]}</span>}
      {sources.length > 0 && (
        <span className="flex flex-wrap items-center gap-1.5 text-[12.5px] text-fg-3">
          Tool answers
          {sources.map((k) => (
            <Badge key={k} tone={ANSWER_SOURCES[k].tone}>
              {ANSWER_SOURCES[k].label} {counts[k]}
            </Badge>
          ))}
        </span>
      )}
      <span className="font-mono text-[12.5px] text-fg tnum sm:ml-auto">{cost(run.cost_usd)}</span>
    </section>
  );
}

export function RunComparePage() {
  const { runId = "" } = useParams();
  const qc = useQueryClient();
  const run = useSimulationRun(runId);
  const done = run.data?.status === "completed";
  const comparison = useComparison(runId, done);
  const wide = useMediaQuery("(min-width: 1024px)");
  const [side, setSide] = useState<"original" | "simulated">("simulated");
  const [cancelling, setCancelling] = useState(false);

  if (isApiError(run.error) && run.error.status === 404)
    return <RecordNotFound kind="simulation run" backTo="/simulations?tab=runs" backLabel="Back to Simulations" />;
  if (run.isError)
    return (
      <EmptyState
        icon={<Flask weight="duotone" />}
        title="The run did not load"
        actions={<Button onClick={() => void run.refetch()}>Try again</Button>}
      >
        {problemText(run.error, "simulation run")}
      </EmptyState>
    );
  if (!run.data) return <PanelLoader label="Opening simulation" />;
  const r = run.data;
  const back = r.experiment_id
    ? { to: `/simulations/${r.experiment_id}`, label: "Back to the batch" }
    : { to: "/simulations?tab=runs", label: "Back to Simulations" };
  const c = comparison.data;
  const divergedAt = c?.diverged_at_turn ?? r.diverged_at_turn ?? null;

  const cancel = async () => {
    setCancelling(true);
    try {
      qc.setQueryData(simKeys.run(r.simulation_run_id), await cancelSimulationRun(r.simulation_run_id));
    } catch (e) {
      toast({ tone: "error", title: "The run was not cancelled", description: problemText(e) });
    } finally {
      setCancelling(false);
    }
  };

  const unused =
    c && c.unused_caller_turns && c.unused_caller_turns.length > 0 ? (
      <div className="border-t border-line bg-surface-2/60 px-4 py-3">
        <p className="mb-1.5 text-[12px] font-medium text-fg-2">Recorded caller turns never used</p>
        <ol className="flex flex-col gap-1 text-[12.5px] text-fg-3">
          {c.unused_caller_turns.map((t, i) => (
            <li key={i} className="break-words">
              {t}
            </li>
          ))}
        </ol>
      </div>
    ) : null;

  const original = c?.original ? <TranscriptPanel title="Original call" side={c.original} divergedAt={divergedAt} /> : null;
  const simulated = c ? (
    <TranscriptPanel
      title="Simulated call"
      side={c.simulated}
      divergedAt={divergedAt}
      extra={unused}
      meta={r.end_reason ? <span className="text-[12px] text-fg-3 sm:ml-auto">{END_REASONS[r.end_reason]}</span> : undefined}
    />
  ) : null;

  return (
    <div className="flex flex-col">
      <Link to={back.to} className="link-underline mb-4 inline-flex w-fit items-center gap-1 rounded-inline text-[13px] text-fg-2 hover:text-fg">
        <ChevronLeft className="size-4" aria-hidden /> {back.label}
      </Link>
      <PageHeader
        title={r.base_call_id ? `${MODE_LABELS[r.mode]} of a call` : "Persona simulation"}
        description={
          <>
            {r.agent_name ?? "Agent"}, started {whenLong(r.created_at)}
            {r.base_call_id && (
              <>
                {" "}
                from{" "}
                <Link to={`/calls?call=${r.base_call_id}`} className="break-all font-mono text-[12.5px] hover:underline">
                  {r.base_call_id}
                </Link>
              </>
            )}
            .
          </>
        }
        actions={
          r.status === "pending" ? (
            <Button icon={<CircleStop aria-hidden />} pending={cancelling} onClick={() => void cancel()}>
              Cancel run
            </Button>
          ) : undefined
        }
      />
      <div className="flex flex-col gap-6">
        <Summary run={r} />
        {isSimActive(r.status) && (
          <FormAlert tone="info">
            <span className="inline-flex items-center gap-2">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              {r.status === "pending" ? "Queued. The run starts when a slot is free." : "Running. The comparison appears here when the run finishes."}
            </span>
          </FormAlert>
        )}
        {r.status === "failed" && <FormAlert tone="error">{r.error_message ?? "The run failed before it finished."}</FormAlert>}
        {r.status === "cancelled" && <FormAlert tone="info">This run was cancelled before it started and was not charged.</FormAlert>}
        {r.persona_brief && <PersonaBriefView brief={r.persona_brief} source={r.persona_source} />}
        {done && comparison.isError && <ProblemAlert error={comparison.error} kind="comparison" />}
        {done && !c && !comparison.isError && <Skeleton className="h-[420px] w-full rounded-panel" />}
        {c && (
          <>
            {divergedAt !== null && c.original && (
              <FormAlert tone="warning">
                The simulated conversation went its own way at caller turn {divergedAt}.
                {c.unused_caller_turns?.length ? ` ${c.unused_caller_turns.length} recorded caller turns were not used.` : ""}
              </FormAlert>
            )}
            {!c.original && (
              <p className="text-[13px] text-fg-3">This run started from a written persona brief, so there is no original call to compare with.</p>
            )}
            {original && !wide && (
              <Segmented
                aria-label="Transcript"
                fill
                value={side}
                onValueChange={setSide}
                options={[
                  { value: "original", label: "Original" },
                  { value: "simulated", label: "Simulated" },
                ]}
              />
            )}
            {original ? (
              wide ? (
                <div className="grid grid-cols-2 items-start gap-4">
                  {original}
                  {simulated}
                </div>
              ) : side === "original" ? (
                original
              ) : (
                simulated
              )
            ) : (
              simulated
            )}
            <Panel title="Checks on both calls" description="Verdicts are compared only between the same check version." bodyClassName="p-0">
              <Table
                caption="Check verdicts, original and simulated"
                columns={c.original ? VERDICT_COLUMNS : VERDICT_COLUMNS.filter((col) => col.key !== "original" && col.key !== "change")}
                rows={c.verdicts.filter((v) => !audioOnly(v))}
                rowKey={(v) => `${v.evaluator_id}-${v.node_id ?? ""}`}
                empty={
                  <p className="px-5 py-6 text-[13px] text-fg-3">
                    {c.verdicts.length ? "No check can be compared on a text simulation." : "No checks are enabled on this agent."}
                  </p>
                }
              />
              {c.verdicts.some(audioOnly) && (
                <p className="border-t border-line px-5 py-3 text-[12.5px] text-fg-3">
                  Not run on text simulations, because they need call audio:{" "}
                  {[...new Set(c.verdicts.filter(audioOnly).map((v) => v.evaluator_display_name))].join(", ")}.
                </p>
              )}
            </Panel>
          </>
        )}
      </div>
    </div>
  );
}
