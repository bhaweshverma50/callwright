import { ListChecks } from "@phosphor-icons/react";
import { ArrowRight, Bot, CircleCheck, CircleDashed, CircleX, Clock, Shuffle, Split, TriangleAlert } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { problemMessage } from "../../api/problems";
import { useReviewQueue, useReviewSummary, type QueueItem, type ReviewStrategy } from "../../api/quality";
import { Button, EmptyState, PageHeader, Select, Skeleton, cn, focusRing } from "../../components";
import { CallDetailDrawer, type DrawerTab } from "../calls/CallDetailDrawer";
import { mss, timeAgo } from "../../lib/format";
import { SentimentBadge } from "../../components/callVocabulary";
import { useAllAgents } from "../../api/agents";

export const EMPTY_QUEUE = "Nothing to review. Every recent call in this queue is labelled, or no checks have run yet.";

const STRATEGIES: { value: ReviewStrategy; label: string; hint: string; icon: typeof Split }[] = [
  { value: "random", label: "Random", hint: "A sample of unlabelled calls, for an unbiased baseline.", icon: Shuffle },
  { value: "failed", label: "Flagged", hint: "Calls where at least one check failed, most failures first.", icon: TriangleAlert },
  { value: "disagreement", label: "Mixed verdicts", hint: "Calls where checks split. These teach calibration the most.", icon: Split },
];
const ALL_AGENTS = "all";

/** "all 5 passed", "2 failed · 3 passed" or "no checks run yet" (US6, FR-025). */
export function verdictLine(item: Pick<QueueItem, "pass_count" | "fail_count">): string {
  const total = item.pass_count + item.fail_count;
  if (total === 0) return "no checks run yet";
  if (item.fail_count === 0) return `all ${item.pass_count} passed`;
  if (item.pass_count === 0) return `all ${item.fail_count} failed`;
  return `${item.fail_count} failed · ${item.pass_count} passed`;
}

function SplitBar({ pass, fail }: { pass: number; fail: number }) {
  const total = pass + fail;
  if (!total) return <span className="h-1.5 w-full rounded-full bg-surface-3" aria-hidden />;
  return (
    <span className="flex h-1.5 w-full gap-0.5 overflow-hidden rounded-full" aria-hidden>
      {fail > 0 && (
        <motion.span
          className="h-full rounded-full bg-[linear-gradient(90deg,var(--heat-2),var(--danger))]"
          initial={{ width: 0 }}
          animate={{ width: `${(fail / total) * 100}%` }}
          transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
        />
      )}
      {pass > 0 && (
        <motion.span
          className="h-full flex-1 rounded-full bg-success/70"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.2 }}
        />
      )}
    </span>
  );
}

function QueueCard({ item, index, onOpen }: { item: QueueItem; index: number; onOpen: () => void }) {
  const total = item.pass_count + item.fail_count;
  const Icon = total === 0 ? CircleDashed : item.fail_count === 0 ? CircleCheck : CircleX;
  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.97 }}
      transition={{ delay: Math.min(index, 12) * 0.03, duration: 0.25 }}
    >
      <button
        type="button"
        onClick={onOpen}
        aria-label={`Review call with ${item.agent_name}, ${verdictLine(item)}`}
        className={cn(
          "group flex h-full w-full cursor-pointer flex-col gap-3 rounded-panel border border-line bg-surface p-4 text-left shadow-1",
          "transition-[border-color,box-shadow,transform] duration-200 hover:border-accent/45",
          focusRing,
        )}
      >
        <span className="flex w-full items-start justify-between gap-3">
          <span className="flex min-w-0 items-center gap-2.5">
            <span className="bg-accent grid size-8 shrink-0 place-items-center rounded-control text-white [&_svg]:size-4">
              <Bot aria-hidden />
            </span>
            <span className="flex min-w-0 flex-col">
              <span className="truncate text-[14px] font-semibold text-fg">{item.agent_name}</span>
              <span className="flex items-center gap-1 text-[12px] text-fg-3">
                <Clock className="size-3" aria-hidden />
                {timeAgo(item.ended_at)}
                <span aria-hidden>·</span>
                <span className="font-mono tnum">{mss(item.duration_s)}</span>
              </span>
            </span>
          </span>
          <SentimentBadge value={item.sentiment ?? "unknown"} />
        </span>
        <SplitBar pass={item.pass_count} fail={item.fail_count} />
        <span className="flex w-full items-center justify-between gap-2">
          <span
            className={cn(
              "inline-flex items-center gap-1.5 text-[13px] font-medium",
              total === 0 ? "text-fg-3" : item.fail_count === 0 ? "text-success-text" : "text-danger-text",
            )}
          >
            <Icon className="size-3.5" aria-hidden />
            {verdictLine(item)}
          </span>
          <ArrowRight
            className="size-4 text-fg-3 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-accent-text"
            aria-hidden
          />
        </span>
      </button>
    </motion.li>
  );
}

/**
 * Review queue (US6, T067): unlabelled recent calls in three orders with counts. A card opens
 * the call drawer on its Quality tab; after labelling, "Next call" moves on and the labelled
 * call leaves the queue.
 */
export function ReviewPage() {
  const [params, setParams] = useSearchParams();
  const strategy = (STRATEGIES.some((s) => s.value === params.get("queue")) ? params.get("queue") : "disagreement") as ReviewStrategy;
  const agent = params.get("agent") ?? ALL_AGENTS;
  const agentId = agent === ALL_AGENTS ? null : agent;
  const queue = useReviewQueue(strategy, agentId);
  const summary = useReviewSummary(agentId);
  const agents = useAllAgents();
  const callId = params.get("call");
  const tab = (params.get("tab") as DrawerTab | null) ?? "quality";
  const [labelled, setLabelled] = useState(false);
  // The order the operator started from, so "Next call" walks it while labelled calls drop out.
  const [frozen, setFrozen] = useState<QueueItem[]>([]);

  const items = useMemo(() => queue.data ?? [], [queue.data]);
  const agentOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const a of agents.data ?? []) seen.set(a.id, a.name);
    for (const i of items) if (!seen.has(i.agent_id)) seen.set(i.agent_id, i.agent_name);
    return [{ value: ALL_AGENTS, label: "All agents" }, ...[...seen].map(([value, label]) => ({ value, label }))];
  }, [agents.data, items]);

  const set = (mut: (p: URLSearchParams) => void, replace = true) => {
    const p = new URLSearchParams(params);
    mut(p);
    setParams(p, { replace });
  };
  const open = (id: string) => {
    setLabelled(false);
    if (!callId) setFrozen(items);
    set((p) => {
      p.set("call", id);
      p.delete("tab");
    }, false);
  };
  const close = () =>
    set((p) => {
      p.delete("call");
      p.delete("tab");
    });
  const list = frozen.length ? frozen : items;
  const at = list.findIndex((i) => i.call_id === callId);
  const next = list.slice(at + 1).find((i) => i.call_id !== callId) ?? null;
  const counts = summary.data;

  return (
    <>
      <PageHeader
        title="Review"
        description="Label calls good or bad so the automatic checks can be calibrated against people. Labelled calls leave the queue."
        actions={
          <Select
            aria-label="Agent"
            size="sm"
            className="w-56"
            value={agent}
            onValueChange={(v) =>
              set((p) => {
                if (v === ALL_AGENTS) p.delete("agent");
                else p.set("agent", v);
              })
            }
            options={agentOptions}
          />
        }
      />
      <div role="tablist" aria-label="Queue" className="mb-5 grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-3">
        {STRATEGIES.map((s) => {
          const on = s.value === strategy;
          const n = counts?.[s.value];
          const Icon = s.icon;
          return (
            <button
              key={s.value}
              type="button"
              role="tab"
              aria-selected={on}
              onClick={() => set((p) => (s.value === "disagreement" ? p.delete("queue") : p.set("queue", s.value)))}
              className={cn(
                "relative flex cursor-pointer flex-col gap-1.5 overflow-hidden rounded-panel border p-4 text-left transition-[border-color,box-shadow,background-color] duration-200",
                on ? "border-accent bg-accent-soft/40 shadow-[0_0_0_1px_var(--accent)]" : "border-line bg-surface hover:border-accent/40",
                focusRing,
              )}
            >
              {on && (
                <span
                  aria-hidden
                  className="pointer-events-none absolute -right-8 -top-12 size-36 rounded-full bg-[radial-gradient(closest-side,var(--glow-b),transparent)]"
                />
              )}
              <span className="flex w-full items-center justify-between gap-2">
                <span className="flex items-center gap-2 text-[14px] font-semibold text-fg">
                  <span
                    className={cn(
                      "grid size-7 place-items-center rounded-control [&_svg]:size-3.5",
                      on ? "bg-accent text-white" : "bg-surface-3 text-fg-2",
                    )}
                  >
                    <Icon aria-hidden />
                  </span>
                  {s.label}
                </span>
                <span className="font-mono text-[20px] font-semibold text-fg tnum" aria-label={`${n ?? 0} calls`}>
                  {n ?? <Skeleton className="inline-block h-5 w-6" />}
                </span>
              </span>
              <span className="text-[13px] leading-relaxed text-fg-3">{s.hint}</span>
            </button>
          );
        })}
      </div>

      {queue.isPending ? (
        <ul className="grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-[132px] rounded-panel" />
          ))}
        </ul>
      ) : queue.isError ? (
        <EmptyState icon={<ListChecks weight="duotone" />} title="The queue could not load">
          {problemMessage(queue.error, "queue")}
        </EmptyState>
      ) : items.length === 0 ? (
        <EmptyState icon={<ListChecks weight="duotone" />} title="All caught up">
          {EMPTY_QUEUE}
        </EmptyState>
      ) : (
        <ul
          className="grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2 xl:grid-cols-3"
          aria-label={`${STRATEGIES.find((s) => s.value === strategy)?.label} queue`}
        >
          <AnimatePresence initial={false} mode="popLayout">
            {items.map((item, i) => (
              <QueueCard key={item.call_id} item={item} index={i} onOpen={() => open(item.call_id)} />
            ))}
          </AnimatePresence>
        </ul>
      )}

      <CallDetailDrawer
        callId={callId}
        tab={tab}
        onTab={(t) => set((p) => (t === "quality" ? p.delete("tab") : p.set("tab", t)))}
        onClose={close}
        onLabelled={(l) => setLabelled(l !== null)}
        footer={
          callId ? (
            <div className="flex w-full items-center gap-3">
              <span className="text-[13px] text-fg-3" aria-live="polite">
                {labelled ? "Labelled. It leaves the queue." : "Label the call, then move on."}
              </span>
              <Button
                variant={labelled ? "primary" : "secondary"}
                className="ml-auto"
                icon={<ArrowRight aria-hidden />}
                disabled={!next}
                onClick={() => next && open(next.call_id)}
              >
                {next ? "Next call" : "Last call in the queue"}
              </Button>
            </div>
          ) : null
        }
      />
    </>
  );
}
