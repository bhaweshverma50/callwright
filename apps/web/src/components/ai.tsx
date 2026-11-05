/**
 * Shared pieces for AI surfaces (Write with AI, the flow assistant, Ask about your data, analysis):
 * a composer with the send button inside the field, and a thinking line whose verb changes while
 * the model works, with elapsed time.
 */
import { ArrowUp } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useLayoutEffect, useRef, useState, type Ref, type ReactNode } from "react";
import { cn, focusRing } from "./cn";
import { Waveform } from "./signal";

const MAX_INPUT_PX = 168;

export interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  placeholder: string;
  /** Accessible name of the field (unless `id` points a visible label at it). */
  label?: string;
  id?: string;
  sendLabel?: string;
  /** The field itself is read-only (for example while changes wait for approval). */
  disabled?: boolean;
  /** Sending is not possible right now (a request is running). */
  busy?: boolean;
  maxLength?: number;
  inputRef?: Ref<HTMLTextAreaElement>;
  /** Take focus when mounted (a panel whose main job is the conversation). */
  autoFocus?: boolean;
  className?: string;
}

/** One rounded field: the text grows with what you type, the send button sits inside it. Enter
 * sends, Shift+Enter adds a line. */
export function Composer({
  value,
  onChange,
  onSubmit,
  placeholder,
  label,
  id,
  sendLabel = "Send",
  disabled,
  busy,
  maxLength,
  inputRef,
  autoFocus,
  className,
}: ComposerProps) {
  const local = useRef<HTMLTextAreaElement | null>(null);
  const canSend = Boolean(value.trim()) && !busy && !disabled;
  useLayoutEffect(() => {
    const el = local.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_INPUT_PX)}px`;
  }, [value]);
  const setRefs = (el: HTMLTextAreaElement | null) => {
    local.current = el;
    if (typeof inputRef === "function") inputRef(el);
    else if (inputRef) (inputRef as { current: HTMLTextAreaElement | null }).current = el;
  };
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (canSend) onSubmit();
      }}
      className={cn(
        "flex w-full items-end gap-2 rounded-[14px] border border-line-strong bg-surface py-1.5 pl-3.5 pr-1.5 shadow-1 transition-[border-color,box-shadow]",
        "focus-within:border-accent focus-within:shadow-[0_0_0_3px_var(--accent-soft)]",
        disabled && "bg-surface-2",
        className,
      )}
    >
      <textarea
        ref={setRefs}
        id={id}
        aria-label={id ? undefined : label}
        rows={1}
        autoFocus={autoFocus}
        value={value}
        maxLength={maxLength}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            if (canSend) onSubmit();
          }
        }}
        className="max-h-[168px] min-h-[36px] flex-1 resize-none bg-transparent py-[7px] text-[14px] leading-[22px] text-fg outline-none placeholder:text-fg-3 disabled:cursor-not-allowed"
      />
      <button
        type="submit"
        aria-label={sendLabel}
        disabled={!canSend}
        className={cn(
          "grid size-9 shrink-0 cursor-pointer place-items-center rounded-full transition-[background,color,transform,box-shadow] duration-150 active:scale-95",
          canSend ? "bg-accent text-white hover:bg-accent-hover" : "cursor-not-allowed bg-surface-3 text-fg-3",
          focusRing,
        )}
      >
        <ArrowUp className="size-4" aria-hidden />
      </button>
    </form>
  );
}

const VERB_MS = 2400;

function elapsedText(ms: number): string {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

/** A live waveform with "Drafting… 4s" under it: a verb that changes every few seconds with a soft
 * shimmer, and the time so far. Screen readers hear `label` once. */
export function ThinkingIndicator({
  verbs,
  label,
  className,
  extra,
  since,
}: {
  verbs: string[];
  label: string;
  className?: string;
  extra?: ReactNode;
  /** When the work started (server time). The timer and verb then survive remounts such as tab changes. */
  since?: string | number | null;
}) {
  const reduce = useReducedMotion() ?? false;
  const [mounted] = useState(() => Date.now());
  const parsed = since == null ? NaN : typeof since === "number" ? since : Date.parse(since);
  const start = Number.isFinite(parsed) ? Math.min(parsed, mounted) : mounted;
  const [now, setNow] = useState(mounted);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const elapsed = now - start;
  const verb = verbs.length ? verbs[Math.floor(elapsed / VERB_MS) % verbs.length]! : label;
  return (
    <div role="status" aria-label={label} className={cn("flex flex-col items-start gap-2 text-[13px]", className)}>
      <span className="w-24" aria-hidden>
        <Waveform bars={18} height={20} live progress={1} />
      </span>
      <span aria-hidden className="relative inline-flex min-w-0 items-baseline gap-2">
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.span
            key={verb}
            initial={reduce ? false : { opacity: 0, y: 6, filter: "blur(2px)" }}
            animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, y: -6, filter: "blur(2px)" }}
            transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
            className="text-shimmer truncate font-medium"
          >
            {verb}…
          </motion.span>
        </AnimatePresence>
        {elapsed >= 2000 && <span className="font-mono text-[12px] text-fg-3 tnum">{elapsedText(elapsed)}</span>}
        {extra}
      </span>
    </div>
  );
}
