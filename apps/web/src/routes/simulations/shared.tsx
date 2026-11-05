/**
 * Labels, badges and small pieces shared by the testing tab, simulations and datasets (spec 008).
 */
import { Check, CircleDashed, Loader2, Minus } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { isApiError } from "../../api/errors";
import { isInsufficientCredit } from "../../api/paid";
import { problemMessage } from "../../api/problems";
import type { AnswerSource, Experiment, SimEndReason, SimMode, SimStatus, SimulationRun, TargetType, VerdictDiff } from "../../api/simulations";
import { Badge, Button, cn, focusRing, type Tone } from "../../components";
import { FormAlert } from "../public/FormAlert";

export const MODE_LABELS: Record<SimMode, string> = { replay: "Replay", persona: "Persona" };

export const TARGET_LABELS: Record<TargetType, string> = {
  published: "Published version",
  draft: "Saved draft",
  version: "Earlier version",
  variant: "Variant",
};

/** "the published version", "variant Shorter greeting": for use inside a sentence. */
export function targetPhrase(r: Pick<SimulationRun | Experiment, "target_type" | "variant_label">): string {
  if (r.target_type === "variant") return r.variant_label ? `variant "${r.variant_label}"` : "a variant";
  return `the ${TARGET_LABELS[r.target_type].toLowerCase()}`;
}

/** call_01MOCKSIMCALL0000000000007 -> "call_01MO...000007": long ids keep both ends visible. */
export function shortId(id: string, head = 9, tail = 6): string {
  return id.length <= head + tail + 3 ? id : `${id.slice(0, head)}...${id.slice(-tail)}`;
}

/** "Variant: Shorter greeting", "Published version". */
export function targetText(r: Pick<SimulationRun | Experiment, "target_type" | "variant_label">): string {
  if (r.target_type === "variant") return r.variant_label ? `Variant: ${r.variant_label}` : "Variant";
  return TARGET_LABELS[r.target_type];
}

const STATUS: Record<SimStatus, { label: string; tone: Tone }> = {
  pending: { label: "Queued", tone: "neutral" },
  running: { label: "Running", tone: "accent" },
  completed: { label: "Completed", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

export function SimStatusBadge({ status }: { status: SimStatus }) {
  const s = STATUS[status];
  return (
    <Badge
      tone={s.tone}
      icon={status === "running" ? <Loader2 className="animate-spin" aria-hidden /> : status === "pending" ? <CircleDashed aria-hidden /> : undefined}
    >
      {s.label}
    </Badge>
  );
}

export const END_REASONS: Record<SimEndReason, string> = {
  caller_turns_exhausted: "Recorded caller turns used up",
  caller_hung_up: "Caller ended the call",
  agent_hangup: "Agent ended the call",
  call_transfer: "Transferred",
  turn_limit_reached: "Turn limit reached",
  error: "Stopped by an error",
};

export const ANSWER_SOURCES: Record<AnswerSource, { label: string; tone: Tone; hint: string }> = {
  mock: { label: "Mock", tone: "accent", hint: "Answered by the tool's mock response." },
  recorded: { label: "Recorded", tone: "neutral", hint: "Answered by the output recorded in the original call." },
  synthesized: { label: "Generated", tone: "warning", hint: "No mock or recording: a stand-in output was generated." },
  error: { label: "Error", tone: "danger", hint: "No mock, and the run was set to answer with an error." },
};

export function AnswerSourceBadge({ source }: { source: AnswerSource }) {
  const s = ANSWER_SOURCES[source];
  return (
    <span title={s.hint}>
      <Badge tone={s.tone}>{s.label}</Badge>
    </span>
  );
}

export const CHANGE: Record<VerdictDiff["change"], { label: string; tone: Tone }> = {
  improved: { label: "Improved", tone: "success" },
  regressed: { label: "Regressed", tone: "danger" },
  unchanged: { label: "Unchanged", tone: "neutral" },
  not_comparable: { label: "Not comparable", tone: "neutral" },
};

const VERDICT: Record<NonNullable<VerdictDiff["original"]>, { label: string; tone: Tone }> = {
  pass: { label: "Pass", tone: "success" },
  fail: { label: "Fail", tone: "danger" },
  error: { label: "Error", tone: "warning" },
  not_applicable: { label: "Not applicable", tone: "neutral" },
};

export function VerdictBadge({ verdict }: { verdict: VerdictDiff["original"] }) {
  if (!verdict) return <span className="text-[13px] text-fg-3">None</span>;
  const v = VERDICT[verdict];
  return <Badge tone={v.tone}>{v.label}</Badge>;
}

/** 0.4 -> "40%"; null -> "n/a". */
export function pct(rate: number | null | undefined): string {
  return rate === null || rate === undefined ? "n/a" : `${Math.round(rate * 1000) / 10}%`;
}

/** Rounds half away from zero to one decimal: 30 -> "+30.0 pp", -0.05 -> "-0.1 pp". */
export function pp(delta: number | null | undefined): string {
  if (delta === null || delta === undefined) return "n/a";
  const rounded = (Math.sign(delta) * Math.round(Math.abs(delta) * 10)) / 10;
  if (rounded === 0) return "0.0 pp";
  return `${rounded > 0 ? "+" : "-"}${Math.abs(rounded).toFixed(1)} pp`;
}

export function deltaTone(delta: number | null | undefined): string {
  if (delta === null || delta === undefined || Math.abs(delta) < 0.05) return "text-fg-2";
  return delta > 0 ? "text-success-text" : "text-danger-text";
}

/** Dollar amounts from JSON numbers in the 008 contracts. */
export function cost(value: number | null | undefined): string {
  if (value === null || value === undefined) return "n/a";
  return `$${value.toFixed(value < 0.1 ? 4 : 2)}`;
}

export const plural = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString()} ${n === 1 ? one : many}`;

/**
 * Failed request message for 008 actions. A 402 says how to add funds and links to Billing; other
 * problems show the server's `detail` when it sent one.
 */
export function ProblemAlert({ error, kind = "record", className }: { error: unknown; kind?: string; className?: string }) {
  if (!error) return null;
  if (isInsufficientCredit(error)) {
    return (
      <div className={className}>
        <FormAlert
          tone="warning"
          action={
            <Button asChild size="sm" variant="secondary" className="w-fit">
              <Link to="/billing">Add funds</Link>
            </Button>
          }
        >
          Your balance is too low to start paid work. Add funds to continue.
        </FormAlert>
      </div>
    );
  }
  const detail = isApiError(error) && error.status !== 422 && error.problem.detail ? error.problem.detail : null;
  return (
    <div className={className}>
      <FormAlert tone="error">{detail ?? problemMessage(error, kind)}</FormAlert>
    </div>
  );
}

/** Message for a toast: same rules as ProblemAlert, as text. */
export function problemText(error: unknown, kind = "record"): string {
  if (isInsufficientCredit(error)) return "Your balance is too low. Add funds on the Billing page to continue.";
  if (isApiError(error) && error.problem.detail) return error.problem.detail;
  return problemMessage(error, kind);
}

/** Thin stacked bar: completed, failed, cancelled out of the total. */
export function ProgressBar({
  completed,
  failed,
  cancelled = 0,
  total,
  className,
  label,
}: {
  completed: number;
  failed: number;
  cancelled?: number;
  total: number;
  className?: string;
  label?: string;
}) {
  const w = (n: number) => `${total ? (n / total) * 100 : 0}%`;
  return (
    <div
      role="progressbar"
      aria-label={label ?? "Progress"}
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={completed + failed + cancelled}
      className={cn("flex h-1.5 w-full overflow-hidden rounded-full bg-surface-3", className)}
    >
      <span className="h-full bg-success transition-[width] duration-500" style={{ width: w(completed) }} />
      <span className="h-full bg-danger transition-[width] duration-500" style={{ width: w(failed) }} />
      <span className="h-full bg-fg-3/40 transition-[width] duration-500" style={{ width: w(cancelled) }} />
    </div>
  );
}

/** A labelled figure in a header strip (not a card): label above, mono value below. */
export function Figure({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="text-[12px] text-fg-3">{label}</span>
      <span className="truncate font-mono text-[15px] font-semibold text-fg tnum">{children}</span>
      {hint && <span className="text-[12px] text-fg-3">{hint}</span>}
    </div>
  );
}

/** Row checkbox in the Call History style (a button with role checkbox). */
export function Checkbox({ checked, mixed, onChange, label }: { checked: boolean; mixed?: boolean; onChange: () => void; label: string }) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={mixed ? "mixed" : checked}
      aria-label={label}
      onClick={(e) => {
        e.stopPropagation();
        onChange();
      }}
      className={cn(
        "grid size-[18px] shrink-0 cursor-pointer place-items-center rounded-[5px] border transition-[background-color,border-color,transform] duration-150 active:scale-90",
        checked || mixed ? "bg-accent border-transparent text-white" : "border-line-strong bg-surface hover:border-accent",
        focusRing,
      )}
    >
      {mixed ? <Minus className="size-3" strokeWidth={3} aria-hidden /> : checked ? <Check className="size-3" strokeWidth={3} aria-hidden /> : null}
    </button>
  );
}
