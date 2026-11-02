/**
 * Labels and badges shared by the issues pages (spec 009).
 */
import { CircleDashed, Loader2 } from "lucide-react";
import type {
  ApplyBlocker,
  DismissReason,
  EvaluatorEvidence,
  FixKind,
  FixStatus,
  IssueScope,
  IssueStatus,
  IssueSummary,
  StatusFilter,
  ValidationAttempt,
  ValidationReason,
} from "../../api/issues";
import { Badge, type Tone } from "../../components";

export const STATUS_LABELS: Record<IssueStatus, string> = {
  open: "Open",
  validating: "Validating",
  validated: "Validated",
  applied: "Applied",
  dismissed: "Dismissed",
};

export const STATUS_FILTER_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "open", label: "Open" },
  { value: "validating", label: "Validating" },
  { value: "validated", label: "Validated" },
  { value: "applied", label: "Applied" },
  { value: "dismissed", label: "Dismissed" },
];

export const SCOPE_LABELS: Record<IssueScope, string> = { real: "Real calls", real_and_simulated: "Real + simulated" };

const STATUS_TONES: Record<IssueStatus, Tone> = {
  open: "warning",
  validating: "accent",
  validated: "success",
  applied: "success",
  dismissed: "neutral",
};

export function IssueStatusBadge({ status }: { status: IssueStatus }) {
  return (
    <Badge tone={STATUS_TONES[status]} icon={status === "validating" ? <Loader2 className="animate-spin" aria-hidden /> : undefined}>
      {STATUS_LABELS[status]}
    </Badge>
  );
}

export const ORIGIN_LABELS: Record<IssueSummary["origin"], string> = {
  real: "Real calls",
  simulated: "Mostly simulated",
  mixed: "Real and simulated",
};

export const KIND_LABELS: Record<FixKind, string> = {
  prompt_edit: "Prompt edit",
  node_prompt_edit: "Node instructions edit",
  add_guardrail: "Add guardrail",
  tool_description_edit: "Tool description edit",
  transition_condition_edit: "Transition condition edit",
  add_transition: "Add transition",
  node_tool_attachment: "Node tools",
  kb_attach: "Attach knowledge base",
};

export const KIND_HINTS: Record<FixKind, string> = {
  prompt_edit: "Rewrite the agent prompt.",
  node_prompt_edit: "Rewrite the instructions of one flow node.",
  add_guardrail: "Add one rule to the prompt or to agent nodes.",
  tool_description_edit: "Rewrite how a tool is described to the model.",
  transition_condition_edit: "Change when the flow moves along one transition.",
  add_transition: "Add a transition between two existing nodes.",
  node_tool_attachment: "Attach or detach tools on one node.",
  kb_attach: "Attach knowledge bases that cover the missing topics.",
};

const FIX_STATUS: Record<FixStatus, { label: string; tone: Tone }> = {
  draft: { label: "Not validated", tone: "neutral" },
  validating: { label: "Validating", tone: "accent" },
  passed: { label: "Passed", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
  inconclusive: { label: "Inconclusive", tone: "warning" },
  superseded: { label: "Superseded", tone: "neutral" },
  applied: { label: "Applied", tone: "success" },
  advisory: { label: "Advice only", tone: "warning" },
};

export function FixStatusBadge({ status }: { status: FixStatus }) {
  const s = FIX_STATUS[status];
  return (
    <Badge tone={s.tone} icon={status === "validating" ? <Loader2 className="animate-spin" aria-hidden /> : undefined}>
      {s.label}
    </Badge>
  );
}

type AttemptState = NonNullable<ValidationAttempt["decision"]> | "running" | "cancelled" | "error";

const ATTEMPT: Record<AttemptState, { label: string; tone: Tone }> = {
  running: { label: "Running", tone: "accent" },
  passed: { label: "Passed", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
  inconclusive: { label: "Inconclusive", tone: "warning" },
  cancelled: { label: "Cancelled", tone: "neutral" },
  error: { label: "Error", tone: "danger" },
};

export function attemptState(a: Pick<ValidationAttempt, "status" | "decision">): AttemptState {
  if (a.status === "completed" && a.decision) return a.decision;
  if (a.status === "completed") return "error";
  return a.status;
}

export function AttemptBadge({ attempt }: { attempt: Pick<ValidationAttempt, "status" | "decision"> }) {
  const state = attemptState(attempt);
  const s = ATTEMPT[state];
  return (
    <Badge
      tone={s.tone}
      icon={state === "running" ? <Loader2 className="animate-spin" aria-hidden /> : state === "cancelled" ? <CircleDashed aria-hidden /> : undefined}
    >
      {s.label}
    </Badge>
  );
}

export const SET_LABELS: Record<EvaluatorEvidence["set"], string> = {
  affected: "Affected calls",
  guard: "Guard calls",
  combined: "Affected and guard",
};

/** One plain-language line per reason code. `names` maps evaluator ids to display names. */
export function reasonText(r: ValidationReason, names: Record<string, string>, t: ValidationAttempt["thresholds"]): string {
  const check = r.evaluator_id ? (names[r.evaluator_id] ?? r.evaluator_id) : "The headline check";
  const set = r.set ? SET_LABELS[r.set].toLowerCase() : null;
  const delta = r.delta_pp != null ? `${r.delta_pp > 0 ? "+" : ""}${r.delta_pp.toFixed(1)} pp` : null;
  switch (r.code) {
    case "insufficient_sample":
      return `Too few affected calls finished with a verdict in both batches${r.n != null ? ` (${r.n})` : ""}. At least ${t.min_sample} are needed.`;
    case "too_many_failed_runs":
      return "More than 20% of the simulations with the fix failed to run, so the result cannot be trusted.";
    case "improvement_below_threshold":
      return `${check} improved by ${delta ?? "less than needed"}, below the ${t.min_improvement_pp} pp needed.`;
    case "regression":
      return `${check} dropped by ${r.delta_pp != null ? `${Math.abs(r.delta_pp).toFixed(1)} pp` : "too much"}${set ? ` on ${set}` : ""}, more than the ${t.max_regression_pp} pp allowed.`;
    case "insufficient_data":
      return `${check} has too few pairs${set ? ` on ${set}` : ""} to judge a regression${r.n != null ? ` (${r.n})` : ""}.`;
  }
}

export const BLOCKER_TEXT: Record<ApplyBlocker, string> = {
  no_passing_validation: "This fix has no passing validation. Validate it first.",
  base_version_changed: "The agent's published version changed since validation. Validate again against the current version.",
  draft_changed: "The agent's draft has changes saved since validation. Validate again so the evidence covers them.",
  wrong_status: "Only a validated issue can be applied.",
  advisory_fix: "This fix is advice only. Attach the knowledge it lists, then draft another fix.",
};

export const DISMISS_REASONS: { value: DismissReason; label: string; description: string }[] = [
  { value: "not_a_problem", label: "Not a real problem", description: "The calls went fine for the caller." },
  { value: "evaluator_wrong", label: "The check is wrong", description: "The check flags calls that are fine." },
  { value: "wont_fix", label: "Won't fix", description: "Known and accepted for now." },
  { value: "duplicate", label: "Duplicate", description: "Another issue covers the same failures." },
  { value: "other", label: "Other", description: "Say why in a note." },
];

export const DISMISS_LABELS = Object.fromEntries(DISMISS_REASONS.map((r) => [r.value, r.label])) as Record<DismissReason, string>;

/** "+40.0 pp": one decimal, half away from zero. */
export function pp(delta: number | null | undefined): string {
  if (delta === null || delta === undefined) return "n/a";
  const rounded = (Math.sign(delta) * Math.round(Math.abs(delta) * 10)) / 10;
  if (rounded === 0) return "0.0 pp";
  return `${rounded > 0 ? "+" : "-"}${Math.abs(rounded).toFixed(1)} pp`;
}

/** "Oct 30 to Nov 13" for a detection window. */
export function windowRange(start?: string, end?: string): string {
  if (!start || !end) return "";
  const f = (iso: string) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return `${f(start)} to ${f(end)}`;
}
