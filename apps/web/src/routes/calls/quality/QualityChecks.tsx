import { ShieldCheck } from "@phosphor-icons/react";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, CircleCheck, CircleDashed, CircleX, History, LoaderCircle, RotateCw, TriangleAlert } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useId, useState } from "react";
import { callKeys } from "../../../api/calls";
import { isApiError } from "../../../api/errors";
import { problemMessage } from "../../../api/problems";
import { newIdempotencyKey, qualityKeys, rerunEvaluations, useCallEvaluations, type EvaluatorRun, type ResultItem } from "../../../api/quality";
import { Badge, Button, Skeleton, cn, toast } from "../../../components";
import { SCOPE_LABELS, VERDICT_LABELS, evaluatorIcon, runStateLabel, runTone } from "../../agents/quality/evaluatorMeta";
import { when } from "../format";
import { withoutLineRefs } from "../../../lib/text";

export const RUNNING_TEXT = "Running checks, results appear as each one finishes";
const TURN_PAGE = 20;

const order = (r: EvaluatorRun) =>
  r.status === "pending" || r.status === "running"
    ? 0
    : r.status === "error"
      ? 1
      : r.verdict === "fail"
        ? 2
        : r.verdict === "pass"
          ? 3
          : r.verdict === "not_applicable"
            ? 4
            : 5;

const fmt = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 3 });
const clock = (ms: number) => `${Math.floor(ms / 60_000)}:${String(Math.floor((ms % 60_000) / 1000)).padStart(2, "0")}`;

function itemLabel(item: ResultItem, index: number): string {
  if (item.turn_index != null) return `Turn ${item.turn_index}`;
  if (item.flow_node_label) return item.flow_node_label;
  if (item.start_ms != null) return `At ${clock(item.start_ms)}`;
  return `Item ${index + 1}`;
}

function VerdictIcon({ verdict }: { verdict: ResultItem["verdict"] }) {
  if (verdict === "pass") return <CircleCheck className="size-4 text-success" aria-label={VERDICT_LABELS.pass} />;
  if (verdict === "fail") return <CircleX className="size-4 text-danger" aria-label={VERDICT_LABELS.fail} />;
  return <CircleDashed className="size-4 text-fg-3" aria-label={VERDICT_LABELS.not_applicable} />;
}

function Items({ run }: { run: EvaluatorRun }) {
  const items = run.items ?? [];
  const [all, setAll] = useState(false);
  if (items.length <= 1 && run.scope !== "turn") return null;
  const shown = all ? items : items.slice(0, TURN_PAGE);
  return (
    <div className="flex flex-col">
      <ol
        className="divide-y divide-line overflow-hidden rounded-control border border-line"
        aria-label={`${run.evaluator_display_name ?? run.evaluator_name} results`}
      >
        {shown.map((it, i) => (
          <li key={i} className={cn("flex items-start gap-2.5 px-3 py-2", it.verdict === "fail" && "bg-danger-soft/40")}>
            <span className="mt-px">
              <VerdictIcon verdict={it.verdict} />
            </span>
            <span className="w-24 shrink-0 text-[13px] font-medium text-fg">{itemLabel(it, i)}</span>
            <span className="min-w-0 flex-1 text-[13px] leading-relaxed text-fg-2">
              {withoutLineRefs(it.rationale)}
              {it.evidence?.quote && <span className="mt-0.5 block italic text-fg-3">"{it.evidence.quote}"</span>}
            </span>
            {it.score != null && <span className="shrink-0 font-mono text-[12px] text-fg-3 tnum">{fmt(it.score)}</span>}
          </li>
        ))}
      </ol>
      {items.length > TURN_PAGE && (
        <Button size="sm" variant="link" className="mt-2 self-start" onClick={() => setAll((a) => !a)}>
          {all ? "Show fewer" : `Show all ${items.length} rows`}
        </Button>
      )}
    </div>
  );
}

function snapshotText(run: EvaluatorRun): string | null {
  const entries = Object.entries(run.settings_snapshot ?? {}).filter(([k]) => k !== "judge_model");
  if (!entries.length) return null;
  return entries.map(([k, v]) => `${k} ${typeof v === "number" ? fmt(v) : String(v)}`).join(", ");
}

function RunCard({ run, defaultOpen }: { run: EvaluatorRun; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  const Icon = evaluatorIcon(run.evaluator_name);
  const running = run.status === "pending" || run.status === "running";
  const failed = run.status === "completed" && run.verdict === "fail";
  const items = run.items ?? [];
  const failing = items.filter((i) => i.verdict === "fail").length;
  const snapshot = snapshotText(run);
  return (
    <motion.li
      layout="position"
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("overflow-hidden rounded-control border bg-surface", failed ? "border-danger/40" : "border-line")}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full cursor-pointer items-start gap-3 px-3.5 py-3 text-left hover:bg-surface-2/50"
      >
        <span
          className={cn(
            "mt-0.5 grid size-7 shrink-0 place-items-center rounded-control [&_svg]:size-3.5",
            failed
              ? "bg-danger-soft text-danger-text"
              : running
                ? "bg-accent-soft text-accent-text"
                : run.verdict === "pass"
                  ? "bg-success-soft text-success-text"
                  : "bg-surface-3 text-fg-3",
          )}
        >
          {running ? <LoaderCircle className="animate-spin" aria-hidden /> : <Icon aria-hidden />}
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-[13px] font-semibold text-fg">{run.evaluator_display_name ?? run.evaluator_name}</span>
            <span className="font-mono text-[11px] text-fg-3">v{run.evaluator_version}</span>
            <Badge tone={runTone(run)}>{runStateLabel(run)}</Badge>
            {run.scope === "turn" && items.length > 0 && (
              <span className="font-mono text-[12px] text-fg-3 tnum">
                {failing} of {items.length} turns failed
              </span>
            )}
          </span>
          {!open && run.rationale && run.verdict !== "not_applicable" && (
            <span className="line-clamp-1 text-[13px] text-fg-2">{withoutLineRefs(run.rationale)}</span>
          )}
          {run.status === "error" && run.error && <span className="text-[13px] text-danger-text">{run.error}</span>}
        </span>
        {run.score != null && run.status === "completed" && (
          <span className="mt-0.5 shrink-0 font-mono text-[12px] text-fg-2 tnum">{fmt(run.score)}</span>
        )}
        <ChevronDown className={cn("mt-1 size-4 shrink-0 text-fg-3 transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={id}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="flex flex-col gap-3 border-t border-line px-3.5 py-3">
              {run.rationale && <p className="text-[13px] leading-relaxed text-fg">{withoutLineRefs(run.rationale)}</p>}
              <Items run={run} />
              <p className="flex flex-wrap gap-x-3 gap-y-1 font-mono text-[11px] text-fg-3">
                <span>
                  {run.evaluator_name} v{run.evaluator_version}
                </span>
                <span>{SCOPE_LABELS[run.scope ?? "call"]}</span>
                {run.judge_model && <span>judge {run.judge_model}</span>}
                {run.cost_usd != null && <span>${run.cost_usd.toFixed(4)}</span>}
                {snapshot && <span>{snapshot}</span>}
                {run.completed_at && <span>{when(run.completed_at)}</span>}
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.li>
  );
}

function Summary({ status, pass, fail, errors }: { status: string; pass: number; fail: number; errors: number }) {
  if (status === "running") {
    return (
      <span role="status" className="inline-flex items-center gap-2 text-[13px] text-accent-text">
        <LoaderCircle className="size-4 animate-spin" aria-hidden />
        {RUNNING_TEXT}
      </span>
    );
  }
  if (status === "not_evaluated") return <Badge icon={<CircleDashed aria-hidden />}>Not yet evaluated</Badge>;
  if (status === "failed")
    return (
      <span className="flex flex-wrap items-center gap-1.5">
        <Badge tone="danger" icon={<CircleX aria-hidden />}>
          {fail} failed
        </Badge>
        {pass > 0 && (
          <Badge tone="success" icon={<CircleCheck aria-hidden />}>
            {pass} passed
          </Badge>
        )}
      </span>
    );
  if (status === "error" || errors > 0)
    return (
      <Badge tone="warning" icon={<TriangleAlert aria-hidden />}>
        {errors ? `${errors} hit an error` : "Checks hit an error"}
      </Badge>
    );
  return (
    <Badge tone="success" icon={<CircleCheck aria-hidden />}>
      No issues detected
    </Badge>
  );
}

/**
 * Quality checks in the call drawer (US2, T043): results grouped by check with their verdict,
 * reason and version, per-turn rows, a running state that fills in without a reload, "Re-run
 * checks" (earlier results move to history) and the history itself.
 */
export function QualityChecks({ callId, canRerun }: { callId: string; canRerun: boolean }) {
  const qc = useQueryClient();
  const evals = useCallEvaluations(callId);
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);

  const rerun = async () => {
    setBusy(true);
    setRefused(null);
    try {
      await rerunEvaluations(callId, newIdempotencyKey());
      await qc.invalidateQueries({ queryKey: qualityKeys.evaluations(callId) });
      void qc.invalidateQueries({ queryKey: callKeys.all });
    } catch (e) {
      if (isApiError(e) && e.status === 409)
        setRefused(
          e.problem.code === "checks_running" || /running/i.test(e.problem.detail ?? e.problem.title)
            ? "Checks are already running"
            : (e.problem.detail ?? e.problem.title),
        );
      else toast({ tone: "error", title: "Could not re-run checks", description: problemMessage(e, "call") });
    } finally {
      setBusy(false);
    }
  };

  if (evals.isPending) {
    return (
      <div className="flex flex-col gap-2" aria-busy="true">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-14 w-full rounded-control" />
        <Skeleton className="h-14 w-full rounded-control" />
      </div>
    );
  }
  if (evals.isError) {
    return (
      <div className="flex items-start gap-3 rounded-panel border border-dashed border-line-strong px-4 py-3.5">
        <ShieldCheck weight="duotone" className="mt-0.5 size-4 shrink-0 text-fg-3" aria-hidden />
        <p className="text-[13px] text-fg-3">Quality checks could not load. {problemMessage(evals.error, "call")}</p>
      </div>
    );
  }
  const data = evals.data;
  const runs = [...data.runs].sort(
    (a, b) => order(a) - order(b) || (a.evaluator_display_name ?? a.evaluator_name).localeCompare(b.evaluator_display_name ?? b.evaluator_name),
  );
  const history = data.history ?? [];
  const errors = runs.filter((r) => r.status === "error").length;
  const running = data.eval_status === "running";
  return (
    <section aria-labelledby="checks-h" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h3 id="checks-h" className="text-[14px] font-semibold text-fg">
          Quality checks
        </h3>
        <Summary status={data.eval_status} pass={data.pass_count} fail={data.fail_count} errors={errors} />
        {canRerun && (
          <Button size="sm" className="ml-auto" icon={<RotateCw aria-hidden />} onClick={() => void rerun()} pending={busy} disabled={running}>
            Re-run checks
          </Button>
        )}
      </div>
      {refused && (
        <p role="alert" className="text-[13px] text-warning-text">
          {refused}
        </p>
      )}
      {runs.length === 0 ? (
        <div className="flex items-start gap-3 rounded-panel border border-dashed border-line-strong px-4 py-3.5">
          <ShieldCheck weight="duotone" className="mt-0.5 size-4 shrink-0 text-fg-3" aria-hidden />
          <div>
            <p className="text-[13px] font-medium text-fg">No checks ran on this call</p>
            <p className="text-[13px] text-fg-3">Turn on checks in the agent's Quality tab; calls that end afterwards are scored automatically.</p>
          </div>
        </div>
      ) : (
        <ul className="flex flex-col gap-2" aria-label="Check results">
          {runs.map((r) => (
            <RunCard
              key={r.id}
              run={r}
              defaultOpen={r.status === "completed" && r.verdict === "fail" && runs.filter((x) => x.verdict === "fail").length <= 2}
            />
          ))}
        </ul>
      )}
      {history.length > 0 && (
        <div className="flex flex-col gap-2">
          <Button
            size="sm"
            variant="ghost"
            className="self-start"
            icon={<History aria-hidden />}
            aria-expanded={historyOpen}
            onClick={() => setHistoryOpen((o) => !o)}
          >
            {historyOpen ? "Hide history" : `History (${history.length} earlier ${history.length === 1 ? "result" : "results"})`}
          </Button>
          <AnimatePresence initial={false}>
            {historyOpen && (
              <motion.ul
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="flex flex-col divide-y divide-line overflow-hidden rounded-control border border-line"
                aria-label="Earlier results"
              >
                {history.map((r) => (
                  <li key={r.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-[13px]">
                    <span className="font-medium text-fg-2">{r.evaluator_display_name ?? r.evaluator_name}</span>
                    <span className="font-mono text-[11px] text-fg-3">v{r.evaluator_version}</span>
                    <Badge tone={runTone(r)}>{runStateLabel(r)}</Badge>
                    <span className="ml-auto font-mono text-[11px] text-fg-3">
                      {r.superseded_at ? `replaced ${when(r.superseded_at)}` : when(r.created_at)}
                    </span>
                  </li>
                ))}
              </motion.ul>
            )}
          </AnimatePresence>
        </div>
      )}
    </section>
  );
}
