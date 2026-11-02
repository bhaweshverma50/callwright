/** Display helpers shared by the quality tab, the call drawer, review and calibration (007). */
import {
  BookCheck,
  Flag,
  GitBranch,
  LibraryBig,
  MessageCircleQuestion,
  OctagonX,
  Radar,
  Repeat,
  ShieldCheck,
  Target,
  TextSearch,
  Timer,
  TrendingUp,
  VolumeX,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import type { EvaluatorRun, Verdict } from "../../api/quality";
import type { Tone } from "../../components";

const ICONS: Record<string, LucideIcon> = {
  anomaly_detection: Radar,
  factual_consistency: BookCheck,
  flow_completion: Flag,
  intent_fulfillment: Target,
  kb_relevance: LibraryBig,
  audio_silence: VolumeX,
  node_dead_end: OctagonX,
  process_reward: TrendingUp,
  stuck_loop_detector: Repeat,
  tool_call_correctness: Wrench,
  transition_correctness: GitBranch,
  latency_slo: Timer,
  phrase_check: TextSearch,
  llm_judge_custom: MessageCircleQuestion,
};

/** Icon for a check by built-in name or custom type. */
export function evaluatorIcon(nameOrType: string, type?: string): LucideIcon {
  return ICONS[nameOrType] ?? (type ? ICONS[type] : undefined) ?? ShieldCheck;
}

export const SCOPE_LABELS = { call: "Whole call", turn: "Each turn", flow_node: "Each node" } as const;

export const VERDICT_LABELS: Record<Verdict, string> = { pass: "Passed", fail: "Failed", not_applicable: "Not applicable" };
export const VERDICT_TONES: Record<Verdict, Tone> = { pass: "success", fail: "danger", not_applicable: "neutral" };

const SKIP_LABELS: Record<NonNullable<EvaluatorRun["skip_reason"]>, string> = {
  insufficient_credit: "Skipped: insufficient credit",
  not_applicable_agent_type: "Skipped: does not apply to this agent type",
  evaluator_disabled: "Skipped: check turned off",
  not_sampled: "Skipped: not sampled",
  too_short: "Skipped: call too short to judge",
};

/** One-line state of a run for chips and rows ("Passed", "Skipped: not sampled", "Not applicable: no recording"). */
export function runStateLabel(run: EvaluatorRun): string {
  if (run.status === "skipped") return run.skip_reason ? SKIP_LABELS[run.skip_reason] : "Skipped";
  if (run.status === "error") return "Error";
  if (run.status === "pending" || run.status === "running") return "Running";
  if (run.verdict === "not_applicable") {
    const reason = (run.rationale ?? "").replace(/\.$/, "");
    return reason ? `Not applicable: ${reason.charAt(0).toLowerCase()}${reason.slice(1)}` : "Not applicable";
  }
  return run.verdict ? VERDICT_LABELS[run.verdict] : "Not evaluated";
}

export function runTone(run: EvaluatorRun): Tone {
  if (run.status === "error") return "danger";
  if (run.status === "pending" || run.status === "running") return "accent";
  if (run.status === "skipped") return "neutral";
  return run.verdict ? VERDICT_TONES[run.verdict] : "neutral";
}

/** "Model judge" checks spend credit on every judged call. */
export const COST_LABELS = { free: "Free", llm_judge: "Model judge" } as const;
