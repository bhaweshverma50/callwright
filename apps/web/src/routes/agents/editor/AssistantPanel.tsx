import { useMutation } from "@tanstack/react-query";
import { ArrowUp, Check, CircleAlert, RotateCcw, Sparkles, Undo2, Wallet } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { idempotencyKey, type PromptProposal } from "../../../api/agents";
import { api } from "../../../api/client";
import { ApiError, toProblem } from "../../../api/errors";
import { problemMessage } from "../../../api/problems";
import { Button, Drawer, IconButton, Textarea, Waveform, cn } from "../../../components";
import { formatUsd } from "../../../lib/money";
import { lineDiff } from "../versions/lineDiff";
import { DiffView } from "../versions/DiffView";
import { syncVariables } from "./catalogs";
import type { AgentDraft } from "./useAgentDraft";

interface Turn {
  id: number;
  role: "user" | "assistant";
  content: string;
  proposal?: PromptProposal | null;
  billed?: string;
  error?: { message: string; credit?: boolean };
}

const SUGGESTIONS = ["A receptionist for a dental clinic that books appointments", "Make it more concise", "Make the tone warmer"];

/**
 * Prompt assistant (US6, T083). A chat that sends the conversation and the current prompt; when
 * the assistant proposes a prompt it shows the difference from the editor's prompt. Apply only
 * changes the editor (unsaved, FR-036) and can be undone; each request is charged as prompt
 * generation and refused without credit (402).
 */
export function AssistantPanel({
  open,
  onOpenChange,
  draft,
  agentId,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  draft: AgentDraft;
  agentId: string | null;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [applied, setApplied] = useState<{ turn: number; prompt: string; greeting: string | null } | null>(null);
  const seq = useRef(0);
  const end = useRef<HTMLDivElement>(null);

  const ask = useMutation({
    mutationFn: async (messages: { role: "user" | "assistant"; content: string }[]) => {
      const { data, error, response } = await api.POST("/prompt-ai/generate", {
        params: { header: { "Idempotency-Key": idempotencyKey() } },
        body: {
          ...(agentId && { agent_id: agentId }),
          language: draft.config.language,
          messages,
          current: draft.config.prompt.trim()
            ? {
                prompt: draft.config.prompt,
                begin_message: draft.config.begin_message ?? null,
                dynamic_variables: draft.config.dynamic_variables.map((v) => v.name),
              }
            : null,
        },
      });
      if (!response.ok) throw new ApiError(response.status, toProblem(response.status, error));
      return data!;
    },
    onSuccess: (res) =>
      setTurns((t) => [...t, { id: ++seq.current, role: "assistant", content: res.reply, proposal: res.proposal, billed: res.billed_usd }]),
    onError: (e) =>
      setTurns((t) => [
        ...t,
        {
          id: ++seq.current,
          role: "assistant",
          content: "",
          error:
            e instanceof ApiError && e.status === 402
              ? { message: "Your balance is at zero, so the assistant cannot run. Add funds to continue.", credit: true }
              : {
                  message:
                    e instanceof ApiError && e.status === 504
                      ? "The assistant took too long and you were not charged. Try again."
                      : problemMessage(e),
                },
        },
      ]),
  });

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [turns.length, ask.isPending]);

  const send = (content: string) => {
    const c = content.trim();
    if (!c || ask.isPending) return;
    const next: Turn[] = [...turns, { id: ++seq.current, role: "user", content: c }];
    setTurns(next);
    setText("");
    ask.mutate(
      next
        .filter((t) => !t.error && t.content)
        .slice(-40)
        .map((t) => ({ role: t.role, content: t.content.slice(0, 8000) })),
    );
  };

  const apply = (turn: Turn) => {
    const p = turn.proposal!;
    setApplied({ turn: turn.id, prompt: draft.config.prompt, greeting: draft.config.begin_message ?? null });
    draft.update((c) => {
      c.prompt = p.prompt;
      if (p.begin_message !== undefined && p.begin_message !== null) c.begin_message = p.begin_message;
      syncVariables(c);
    });
  };
  const undo = () => {
    if (!applied) return;
    draft.update((c) => {
      c.prompt = applied.prompt;
      c.begin_message = applied.greeting;
    });
    setApplied(null);
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    send(text);
  };

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      width="lg"
      title="Write with AI"
      meta="Drafts and edits your prompt. Nothing is saved until you save the agent."
      footer={
        <form onSubmit={onSubmit} className="flex w-full items-end gap-2">
          <Textarea
            aria-label="Message the assistant"
            rows={2}
            className="min-h-[44px] flex-1 resize-none"
            placeholder={
              draft.config.prompt.trim()
                ? "Ask for a change, for example: add a step to confirm the caller's address"
                : "Describe what the agent should do"
            }
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(text);
              }
            }}
          />
          <IconButton
            label="Send"
            type="submit"
            variant="primary"
            className="size-11 shrink-0 rounded-control"
            disabled={!text.trim() || ask.isPending}
          >
            <ArrowUp className="size-4" aria-hidden />
          </IconButton>
        </form>
      }
    >
      <div className="flex min-h-full flex-col gap-4" aria-live="polite">
        {turns.length === 0 && (
          <div className="flex flex-col gap-4">
            <div className="flex items-start gap-3 rounded-panel bg-surface-2/60 p-4">
              <span className="grid size-9 shrink-0 place-items-center rounded-control grad-action text-white">
                <Sparkles className="size-4" aria-hidden />
              </span>
              <p className="text-[13.5px] leading-relaxed text-fg-2">
                The assistant drafts prompts in the same structure as the templates: role, steps, rules. Each request costs about $0.02 from your
                balance.
              </p>
            </div>
            <div className="flex flex-col gap-2">
              <p className="text-[12.5px] text-fg-3">Try one of these</p>
              {SUGGESTIONS.filter((s) => draft.config.prompt.trim() || s.startsWith("A ")).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => send(s)}
                  className="w-fit rounded-full border border-line-strong bg-surface px-3.5 py-1.5 text-left text-[13px] text-fg-2 transition-colors hover:border-accent/50 hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        <AnimatePresence initial={false}>
          {turns.map((t) => (
            <motion.div
              key={t.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            >
              {t.role === "user" ? (
                <div className="ml-auto w-fit max-w-[85%] rounded-panel rounded-br-[4px] bg-accent-soft px-3.5 py-2.5 text-[13.5px] text-fg">
                  {t.content}
                </div>
              ) : t.error ? (
                <div className="flex items-start gap-2.5 rounded-panel border border-danger/30 bg-danger-soft/50 px-3.5 py-3 text-[13px] text-fg">
                  <CircleAlert className="mt-0.5 size-4 shrink-0 text-danger-text" aria-hidden />
                  <div className="flex flex-col gap-2">
                    <span>{t.error.message}</span>
                    {t.error.credit && (
                      <Button asChild size="sm" variant="secondary" icon={<Wallet aria-hidden />} className="w-fit">
                        <Link to="/billing">Add funds</Link>
                      </Button>
                    )}
                  </div>
                </div>
              ) : (
                <div className="flex flex-col gap-3">
                  <p className="max-w-[92%] text-[13.5px] leading-relaxed text-fg">{t.content}</p>
                  {t.proposal && (
                    <ProposalCard turn={t} current={draft.config.prompt} applied={applied?.turn === t.id} onApply={() => apply(t)} onUndo={undo} />
                  )}
                  {t.billed && <span className="text-[11.5px] text-fg-3">Charged {formatUsd(t.billed, { places: 3 })}</span>}
                </div>
              )}
            </motion.div>
          ))}
        </AnimatePresence>

        {ask.isPending && (
          <div className="flex items-center gap-3 text-[13px] text-fg-3" role="status">
            <span className="w-16">
              <Waveform bars={14} height={18} live progress={1} />
            </span>
            Writing
          </div>
        )}
        <div ref={end} />
      </div>
    </Drawer>
  );
}

function ProposalCard({
  turn,
  current,
  applied,
  onApply,
  onUndo,
}: {
  turn: Turn;
  current: string;
  applied: boolean;
  onApply: () => void;
  onUndo: () => void;
}) {
  const p = turn.proposal!;
  const lines = current.trim() ? lineDiff(current, p.prompt) : null;
  return (
    <div className={cn("overflow-hidden rounded-panel border bg-surface", applied ? "border-success/50" : "border-line")}>
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
        <span className="flex items-center gap-2 text-[13px] font-medium text-fg">
          <Sparkles className="size-3.5 text-accent-text" aria-hidden />
          {lines ? "Proposed changes to the prompt" : "Proposed prompt"}
        </span>
        {applied ? (
          <Button size="sm" variant="ghost" icon={<Undo2 aria-hidden />} onClick={onUndo}>
            Undo
          </Button>
        ) : (
          <Button size="sm" variant="primary" icon={<Check aria-hidden />} onClick={onApply}>
            Apply
          </Button>
        )}
      </div>
      <div className="max-h-[300px] overflow-y-auto">
        {lines ? (
          <DiffView lines={lines} />
        ) : (
          <pre className="whitespace-pre-wrap px-4 py-3 font-sans text-[12.5px] leading-relaxed text-fg-2">{p.prompt}</pre>
        )}
      </div>
      {applied && (
        <p className="flex items-center gap-1.5 border-t border-line bg-success-soft/50 px-4 py-2 text-[12.5px] text-success-text">
          <RotateCcw className="size-3.5" aria-hidden /> Applied to the editor. Save the agent to keep it.
        </p>
      )}
    </div>
  );
}
