import { useQuery } from "@tanstack/react-query";
import { ArrowUp, Clock, CloudOff, Maximize2, Minimize2, RotateCcw, Sparkles, SquarePen, Wallet, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router";
import { api, unwrap } from "../../api/client";
import { isApiError } from "../../api/errors";
import { Button, IconButton, cn, focusRing } from "../../components";
import { viewerTimeZone } from "../../routes/calls/filters";
import { chartVars } from "../../routes/dashboard/charts/ChartFrame";
import { AnswerView, SuggestionChips, type ChatAnswer } from "./AnswerView";
import { onOpenAsk } from "./bus";

type Turn = { role: "user"; content: string } | { role: "assistant"; content: string; answer: ChatAnswer };
type Failure = { kind: "credit" | "busy" | "unavailable" | "other"; title: string; message: string };

function failureOf(e: unknown): Failure {
  if (isApiError(e)) {
    if (e.status === 402)
      return { kind: "credit", title: "Out of credit", message: "You're out of credit, so the assistant can't answer. Add funds to keep asking." };
    if (e.status === 429)
      return { kind: "busy", title: "Taking a breather", message: "That's a lot of questions in a minute. Wait a moment, then try again." };
    if (e.status === 503 || e.status === 504 || e.status === 0)
      return {
        kind: "unavailable",
        title: "Assistant unavailable",
        message: "The assistant is unavailable right now. Nothing was charged; your question is still in the box, so just retry.",
      };
  }
  return { kind: "other", title: "That didn't go through", message: "Something went wrong on our side. Nothing was charged; try again in a moment." };
}

const FAILURE_ICONS = { credit: Wallet, busy: Clock, unavailable: CloudOff, other: CloudOff } as const;

/**
 * "Ask about your data" (US5): a compact launcher in the copilot dock (an icon that widens to its
 * label on hover or focus) and a panel (420 px, expandable to a wide split view) with a
 * conversation kept only in this browser tab. The panel is portalled to the body so it is never
 * clipped by the dock or the top bar. `placement` "bar" opens it under the top bar. Each answered question is charged once; the
 * Idempotency-Key is fixed per question so a retry after a network error never charges twice.
 * Errors name the cause and the next step and keep the typed question (FR-041).
 */
export function AskPanel({ placement = "dock" }: { placement?: "dock" | "bar" }) {
  const [open, setOpen] = useState(false);
  const [wide, setWide] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const keyFor = useRef<{ question: string; key: string } | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const catalog = useQuery({
    queryKey: ["analytics", "catalog"],
    queryFn: () => unwrap(api.GET("/analytics/catalog")),
    enabled: open,
    staleTime: 10 * 60_000,
  });

  useEffect(
    () =>
      onOpenAsk((question) => {
        setOpen(true);
        if (question) setDraft(question);
        window.setTimeout(() => input.current?.focus(), 50);
      }),
    [],
  );

  useEffect(() => {
    const el = scroller.current;
    if (el && typeof el.scrollTo === "function") el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [turns, pending]);

  const ask = async (question: string) => {
    const q = question.trim();
    if (!q || pending) return;
    if (keyFor.current?.question !== q) keyFor.current = { question: q, key: crypto.randomUUID() };
    const history = turns.map((t) => ({ role: t.role, content: t.content })).slice(-18);
    setPending(true);
    setFailure(null);
    try {
      const answer = (await unwrap(
        api.POST("/analytics/chat", {
          params: { header: { "Idempotency-Key": keyFor.current.key } },
          body: { messages: [...history, { role: "user", content: q }], timezone: viewerTimeZone() },
        }),
      )) as ChatAnswer;
      setTurns((t) => [...t, { role: "user", content: q }, { role: "assistant", content: answer.content, answer }]);
      setDraft("");
      keyFor.current = null;
    } catch (e) {
      setFailure(failureOf(e));
      setDraft(q);
    } finally {
      setPending(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void ask(draft);
  };

  const suggestions = catalog.data?.suggested_questions ?? [];
  const bar = placement === "bar";
  const FailureIcon = failure ? FAILURE_ICONS[failure.kind] : null;
  // On a phone the panel covers the page, so following a call link closes it to show the call.
  const afterNavigate = () => {
    if (window.matchMedia?.("(max-width: 639px)").matches) setOpen(false);
  };

  return (
    <>
      <button
        type="button"
        aria-label="Ask about your data"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "group/ask grad-action sheen relative flex cursor-pointer items-center overflow-hidden rounded-full text-white transition-[transform,box-shadow] duration-200 hover:scale-[1.03] active:scale-[0.97]",
          bar ? "h-8 pl-2 pr-2" : "h-9 pl-2.5 pr-2.5",
          open && "ring-2 ring-accent/35 ring-offset-2 ring-offset-surface",
          focusRing,
        )}
      >
        <Sparkles className="size-4 shrink-0 transition-transform duration-300 group-hover/ask:rotate-12" aria-hidden />
        <span
          className={cn(
            "max-w-0 overflow-hidden whitespace-nowrap text-[13px] font-medium opacity-0 transition-[max-width,opacity,margin] duration-300 ease-out",
            "group-hover/ask:ml-1.5 group-hover/ask:max-w-[150px] group-hover/ask:opacity-100 group-focus-visible/ask:ml-1.5 group-focus-visible/ask:max-w-[150px] group-focus-visible/ask:opacity-100",
          )}
          aria-hidden
        >
          Ask about your data
        </span>
      </button>
      {createPortal(
        <AnimatePresence>
          {open && (
            <motion.section
              role="dialog"
              aria-label="Ask about your data"
              initial={{ opacity: 0, y: bar ? -16 : 16, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: bar ? -16 : 16, scale: 0.98 }}
              transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
              style={{ transformOrigin: bar ? "top right" : "bottom right" }}
              onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
              className={cn(
                chartVars,
                "fixed right-4 z-50 flex flex-col overflow-hidden rounded-panel border border-line bg-surface shadow-pop",
                bar ? "top-[68px] max-h-[calc(100dvh-84px)]" : "bottom-4 max-h-[calc(100dvh-32px)]",
                wide
                  ? "h-[min(760px,calc(100dvh-32px))] w-[min(860px,calc(100vw-32px))]"
                  : "h-[min(620px,calc(100dvh-32px))] w-[min(420px,calc(100vw-32px))]",
              )}
            >
              <header className="flex items-center gap-2 border-b border-line px-4 py-3">
                <span className="grad-action grid size-7 place-items-center rounded-control text-white">
                  <Sparkles className="size-3.5" aria-hidden />
                </span>
                <h2 className="flex-1 text-[14px] font-semibold text-fg">Ask about your data</h2>
                <IconButton
                  label="New chat"
                  onClick={() => {
                    setTurns([]);
                    setFailure(null);
                    setDraft("");
                  }}
                  className="size-8"
                >
                  <SquarePen className="size-4" aria-hidden />
                </IconButton>
                <IconButton label={wide ? "Narrow view" : "Wide view"} onClick={() => setWide((w) => !w)} className="hidden size-8 sm:inline-flex">
                  {wide ? <Minimize2 className="size-4" aria-hidden /> : <Maximize2 className="size-4" aria-hidden />}
                </IconButton>
                <IconButton label="Close" onClick={() => setOpen(false)} className="size-8">
                  <X className="size-4" aria-hidden />
                </IconButton>
              </header>

              <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto px-4 py-4" aria-live="polite">
                {turns.length === 0 && !pending && (
                  <div className="flex flex-col gap-3">
                    <p className="text-[13.5px] leading-relaxed text-fg-2">
                      Ask about a specific call (your last one, the most expensive) or about totals and trends: calls, talk time, cost, latency and
                      sentiment. Each answer costs a small feature charge.
                    </p>
                    <SuggestionChips items={suggestions} onAsk={(q) => void ask(q)} label="Try asking" />
                  </div>
                )}
                <ol className="flex flex-col gap-4">
                  {turns.map((t, i) =>
                    t.role === "user" ? (
                      <li
                        key={i}
                        className="ml-auto max-w-[85%] rounded-panel rounded-br-[4px] bg-accent-soft px-3.5 py-2 text-[13.5px] text-accent-text"
                      >
                        {t.content}
                      </li>
                    ) : (
                      <motion.li key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="max-w-full">
                        <AnswerView answer={t.answer} onAsk={(q) => void ask(q)} onNavigate={afterNavigate} />
                      </motion.li>
                    ),
                  )}
                  {pending && (
                    <li className="flex items-center gap-2 text-[12.5px] text-fg-3" aria-label="Working on it">
                      <span className="flex gap-1" aria-hidden>
                        {[0, 1, 2].map((d) => (
                          <motion.span
                            key={d}
                            className="size-1.5 rounded-full bg-accent"
                            animate={{ opacity: [0.3, 1, 0.3] }}
                            transition={{ duration: 1, repeat: Infinity, delay: d * 0.15 }}
                          />
                        ))}
                      </span>
                      Looking at your calls
                    </li>
                  )}
                </ol>
              </div>

              <AnimatePresence>
                {failure && FailureIcon && (
                  <motion.div
                    role="alert"
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: 6 }}
                    className="mx-3 mb-2 flex items-start gap-2.5 rounded-panel border border-line bg-surface-2/80 px-3 py-2.5"
                  >
                    <span
                      className={cn(
                        "grid size-7 shrink-0 place-items-center rounded-control",
                        failure.kind === "credit" ? "bg-warning-soft text-warning-text" : "bg-accent-soft text-accent-text",
                      )}
                    >
                      <FailureIcon className="size-3.5" aria-hidden />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-[13px] font-medium text-fg">{failure.title}</p>
                      <p className="mt-0.5 text-[12.5px] leading-snug text-fg-2">{failure.message}</p>
                    </div>
                    {failure.kind === "credit" ? (
                      <Button asChild size="sm" variant="secondary" icon={<Wallet aria-hidden />}>
                        <Link to="/billing">Add funds</Link>
                      </Button>
                    ) : (
                      <Button size="sm" variant="secondary" icon={<RotateCcw aria-hidden />} onClick={() => void ask(draft)}>
                        Retry
                      </Button>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>

              <form onSubmit={submit} className="flex items-end gap-2 border-t border-line px-3 py-3">
                <label htmlFor="ask-input" className="sr-only">
                  Your question
                </label>
                <textarea
                  id="ask-input"
                  ref={input}
                  rows={1}
                  value={draft}
                  maxLength={2000}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void ask(draft);
                    }
                  }}
                  placeholder="What did my last call cost?"
                  className={cn(
                    "max-h-28 min-h-9 flex-1 resize-none rounded-control border border-line-strong bg-surface px-3 py-2 text-[13.5px] text-fg placeholder:text-fg-3",
                    focusRing,
                  )}
                />
                <button
                  type="submit"
                  aria-label="Ask"
                  disabled={!draft.trim() || pending}
                  className={cn(
                    "grad-action grid size-9 shrink-0 cursor-pointer place-items-center rounded-control text-white transition-[opacity,transform] active:scale-95 disabled:cursor-not-allowed disabled:opacity-40",
                    focusRing,
                  )}
                >
                  <ArrowUp className="size-4" aria-hidden />
                </button>
              </form>
            </motion.section>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
}
