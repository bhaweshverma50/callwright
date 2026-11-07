/**
 * Labels, badges and small pieces shared by the testing tab, simulations and datasets (spec 008).
 */
import { CircleDashed, Loader2 } from "lucide-react";
import type { AnswerSource, Experiment, SimEndReason, SimMode, SimStatus, SimulationRun, TargetType, VerdictDiff } from "../../api/simulations";
import { Badge, type Tone } from "../../components";

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
