import { RotateCcw, Sparkles } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { askAssistant, FlowProblem, type ChatTurn, type FlowGraph } from "../../../api/flows";
import { problemMessage } from "../../../api/problems";
import { Button, Composer, ThinkingIndicator, cn } from "../../../components";
import type { Proposal } from "./ProposalBar";

const SUGGESTIONS = [
  "Add a step that collects the caller's date of birth before booking",
  "Send billing questions to a person",
  "Add a goodbye step when the caller is done",
];

/**
 * Flow assistant (T091, US5): a chat beside the canvas. Each answer is a set of proposed
 * changes shown on the canvas; history lives in this browser session only. A timeout leaves the
 * canvas unchanged and offers a retry.
 */
export function AssistantPanel({
  flowId,
  revision,
  graph,
  dirty,
  pending,
  onProposal,
  onBusy,
}: {
  flowId: string;
  revision: number;
  graph: FlowGraph;
  dirty: boolean;
  pending: boolean;
  onProposal: (p: Proposal) => void;
  onBusy?: (busy: boolean) => void;
}) {
  const [chat, setChat] = useState<ChatTurn[]>(() => {
    try {
      return JSON.parse(sessionStorage.getItem(`cw.flow-chat.${flowId}`) ?? "[]") as ChatTurn[];
    } catch {
      return [];
    }
  });
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<{ message: string; retry: ChatTurn[] } | null>(null);
  const list = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      sessionStorage.setItem(`cw.flow-chat.${flowId}`, JSON.stringify(chat.slice(-50)));
    } catch {
      /* session history is a convenience */
    }
    list.current?.scrollTo?.({ top: list.current.scrollHeight, behavior: "smooth" });
  }, [chat, flowId]);

  const send = async (turns: ChatTurn[]) => {
    // Show the message at once, so the conversation (and the thinking line under it) appears
    // while the assistant works, including on the first message.
    setChat(turns);
    setBusy(true);
    onBusy?.(true);
    setFailed(null);
    try {
      const out = await askAssistant(flowId, turns.slice(-50), revision, dirty ? graph : null);
      setChat([...turns, { role: "assistant", content: out.message }]);
      if (out.operations.length || out.flow_name)
        onProposal({
          message: out.message,
          graph: out.proposed_graph as unknown as FlowGraph,
          name: out.flow_name ?? null,
          issues: out.issues,
          baseRevision: out.base_revision,
        });
    } catch (e) {
      const message =
        e instanceof FlowProblem && e.status === 409
          ? "The flow was saved somewhere else. Reload, then ask again."
          : e instanceof FlowProblem && e.status === 504
            ? "The assistant did not answer in time. Nothing changed and nothing was charged."
            : problemMessage(e, "flow");
      setChat(turns);
      setFailed({ message, retry: turns });
    } finally {
      setBusy(false);
      onBusy?.(false);
    }
  };

  const submit = () => {
    const content = text.trim();
    if (!content || busy) return;
    if (pending) return setFailed({ message: "Approve or decline the pending changes first.", retry: chat });
    setText("");
    void send([...chat, { role: "user", content }]);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={list} className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {chat.length === 0 ? (
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2.5">
              <span className="grad-action grid size-8 place-items-center rounded-control text-white shadow-glow" aria-hidden>
                <Sparkles className="size-4" />
              </span>
              <div>
                <p className="text-[13.5px] font-semibold text-fg">Build with the assistant</p>
                <p className="text-[12px] text-fg-3">Describe a change; review it on the canvas before it applies.</p>
              </div>
            </div>
            <ul className="flex flex-col gap-1.5">
              {SUGGESTIONS.map((s) => (
                <li key={s}>
                  <button
                    type="button"
                    disabled={busy || pending}
                    onClick={() => setText(s)}
                    className="lift w-full cursor-pointer rounded-control border border-line bg-surface px-3 py-2 text-left text-[12.5px] text-fg-2 hover:border-line-strong hover:text-fg disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {s}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <ol className="flex flex-col gap-2.5" aria-label="Assistant conversation">
            <AnimatePresence initial={false}>
              {chat.map((t, i) => (
                <motion.li
                  key={i}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={cn(
                    "max-w-[88%] rounded-panel px-3.5 py-2.5 text-[13px] leading-relaxed",
                    t.role === "user"
                      ? "ml-auto rounded-br-[4px] bg-accent text-accent-fg"
                      : "rounded-bl-[4px] border border-line bg-surface text-fg",
                  )}
                >
                  {t.content}
                </motion.li>
              ))}
            </AnimatePresence>
            {busy && (
              <li className="py-1">
                <ThinkingIndicator
                  label="Assistant is working"
                  verbs={["Reading the flow", "Planning the change", "Wiring the steps", "Checking the routes", "Preparing the changes"]}
                />
              </li>
            )}
          </ol>
        )}
        {failed && (
          <div className="mt-3 flex items-start gap-2 rounded-control bg-warning-soft px-3 py-2.5 text-[12.5px] text-warning-text">
            <span className="flex-1">{failed.message}</span>
            {failed.retry.length > 0 && failed.retry.at(-1)?.role === "user" && !pending && (
              <Button size="sm" variant="ghost" icon={<RotateCcw aria-hidden />} onClick={() => void send(failed.retry)}>
                Retry
              </Button>
            )}
          </div>
        )}
      </div>
      <div className="border-t border-line p-3">
        <Composer
          label="Ask the assistant"
          value={text}
          onChange={setText}
          onSubmit={submit}
          disabled={busy}
          busy={busy}
          placeholder={pending ? "Approve or decline the pending changes first" : "Describe a change to the flow"}
        />
      </div>
    </div>
  );
}
