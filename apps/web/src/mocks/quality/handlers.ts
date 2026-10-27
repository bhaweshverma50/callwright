/**
 * Mock API for spec 007 (quality and evaluations), shaped by specs/007-quality-evals/contracts.
 * In memory. Runs, labels and analysis for the seeded mock calls are generated on first read and
 * are deterministic per call, so the review queue, calibration and the call drawer all agree.
 *
 * Behaviour for manual testing:
 * - "Re-run checks" starts a group that finishes about 2.5 s later; a second re-run inside that
 *   window is refused with 409 "Checks are already running".
 * - Calls still processing read as "running" checks; never-connected calls are not evaluated.
 * - A phrase pattern with a backreference ("(a)\1") is refused like RE2 would.
 */
import { http, HttpResponse, type JsonBodyType } from "msw";
import type { CallListItem } from "../../api/calls";
import type {
  AgentEvalSetting,
  AnalysisVariable,
  Annotation,
  CallAnalysis,
  CalibrationRow,
  CustomConfig,
  Evaluator,
  EvaluatorRun,
  JudgeQuestionConfig,
  PhraseCheckConfig,
  QueueItem,
  ResultItem,
  TrialResult,
  Verdict,
} from "../../api/quality";
import { env } from "../../lib/env";
import { MACHINE_NAME_RE, toVariableName } from "../../routes/agents/quality/variableName";
import { fieldError, schemaFields } from "../../routes/agents/quality/settingsSchema";
import { store as agentStore } from "../agents/store";
import { MOCK_AGENTS, mockCalls, setQualitySummarizer } from "../calls/handlers";
import { db } from "../db";
import { BUILTINS, DEFAULT_JUDGE, JUDGE_MODELS } from "./catalog";

const url = (path: string) => `${env.apiBaseUrl}${path}`;
const json = <T>(body: T, status = 200) => HttpResponse.json(body as unknown as JsonBodyType, { status });
function problem(status: number, code: string, title: string, detail?: string, errors?: { pointer: string; code: string; message: string }[]) {
  return HttpResponse.json(
    { type: `https://callwright.dev/problems/${code.replace(/_/g, "-")}`, title, status, code, ...(detail && { detail }), ...(errors && { errors }) } as JsonBodyType,
    { status, headers: { "content-type": "application/problem+json" } },
  );
}
const invalid = (pointer: string, message: string, code = "invalid") =>
  problem(422, "validation_failed", "Request failed validation", message, [{ pointer, code, message }]);

const nowIso = () => new Date().toISOString();
let seq = 0;
const nextId = (prefix: string) => `${prefix}_01MOCK${String(++seq).padStart(20, "0")}`;

type StoredVar = AnalysisVariable & { deleted_at: string | null };
interface StoredSetting {
  enabled: boolean;
  overrides: Record<string, unknown>;
  is_headline: boolean;
  headline_position: number | null;
}
type PendingRun = EvaluatorRun & { _final?: EvaluatorRun; _at?: number };
interface CustomVersion {
  version: number;
  judge_model: string | null;
  definition: Record<string, unknown>;
  created_at: string;
}

interface QualityStore {
  variables: StoredVar[];
  settings: Record<string, Record<string, StoredSetting>>;
  customs: (Evaluator & { versions: CustomVersion[] })[];
  runs: Record<string, PendingRun[]>;
  activeUntil: Record<string, number>;
  annotations: Record<string, Annotation[]>;
  analysis: Record<string, CallAnalysis & { _at?: number }>;
  seeded: Set<string>;
  labelsSeeded: boolean;
  trials: Record<string, TrialResult>;
}

function empty(): QualityStore {
  return {
    variables: [],
    settings: {},
    customs: [],
    runs: {},
    activeUntil: {},
    annotations: {},
    analysis: {},
    seeded: new Set(),
    labelsSeeded: false,
    trials: {},
  };
}

let q: QualityStore = seedStore(empty());

export function resetQualityMocks() {
  q = seedStore(empty());
}

export const qualityStore = () => q;

// Identity -------------------------------------------------------------------------------------

const TEAMMATE = { id: "usr_01MOCKTEAMMATE000000000001", display_name: "Priya Raman" };

function viewer(request: Request): { id: string; display_name: string } {
  const token = request.headers.get("authorization")?.replace(/^Bearer\s+/i, "") ?? "";
  const id = db().sessions[token];
  const user = db().users.find((u) => u.id === id);
  if (!user) return { id: "usr_01MOCKVIEWER00000000000001", display_name: "You" };
  const local = user.email.split("@")[0] ?? "you";
  return { id: user.id, display_name: local.charAt(0).toUpperCase() + local.slice(1) };
}

// Agents ---------------------------------------------------------------------------------------

function agentType(agentId: string): "single_prompt" | "flow" {
  const found = agentStore().agents.find((a) => a.id === agentId);
  if (found) return found.type;
  return agentId === MOCK_AGENTS[1]!.id ? "flow" : "single_prompt";
}

function agentExists(agentId: string): boolean {
  return MOCK_AGENTS.some((a) => a.id === agentId) || agentStore().agents.some((a) => a.id === agentId && !a.deleted_at);
}

function seedStore(s: QualityStore): QualityStore {
  const desk = MOCK_AGENTS[0]!;
  const clinic = MOCK_AGENTS[1]!;
  const v = (agent: string, name: string, type: AnalysisVariable["type"], description: string, position: number, choices: string[] | null = null) =>
    s.variables.push({
      id: `var_01MOCK${agent.slice(-4)}${String(position).padStart(16, "0")}`,
      agent_id: agent,
      name,
      type,
      description,
      choices,
      position,
      created_at: "2026-10-01T09:00:00Z",
      updated_at: "2026-10-01T09:00:00Z",
      deleted_at: null,
    });
  v(desk.id, "order_found", "boolean", "True if the agent found the caller's order in the system.", 0);
  v(desk.id, "issue_type", "choice", "What the caller needed help with.", 1, ["delivery", "refund", "damaged", "other"]);
  v(desk.id, "callback_requested", "boolean", "True if the caller asked to be called back later.", 2);
  v(clinic.id, "appointment_booked", "boolean", "True if a slot was confirmed with the caller.", 0);
  v(clinic.id, "preferred_day", "choice", "The weekday the caller asked for.", 1, ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]);
  const on = (agent: string, name: string, headline: number | null, overrides: Record<string, unknown> = {}) => {
    s.settings[agent] ??= {};
    s.settings[agent][`evl_builtin_${name}`] = { enabled: true, overrides, is_headline: headline !== null, headline_position: headline };
  };
  on(desk.id, "intent_fulfillment", 1, { sample_rate_pct: 75 });
  on(desk.id, "tool_call_correctness", null);
  on(desk.id, "latency_slo", 2);
  on(clinic.id, "intent_fulfillment", 1);
  on(clinic.id, "flow_completion", 2);
  return s;
}

// Settings ------------------------------------------------------------------------------------

function catalogFor(type: "single_prompt" | "flow"): Evaluator[] {
  return [...BUILTINS.filter((e) => e.agent_types.includes(type)), ...q.customs.filter((c) => !c.deleted_at)];
}

function evaluatorById(id: string): Evaluator | undefined {
  return BUILTINS.find((e) => e.id === id) ?? q.customs.find((c) => c.id === id);
}

function effective(e: Evaluator, overrides: Record<string, unknown>): { settings: Record<string, unknown>; adjusted: string[] } {
  const settings: Record<string, unknown> = {};
  const adjusted: string[] = [];
  for (const f of schemaFields(e.settings_schema)) {
    let value = f.key in overrides ? overrides[f.key] : f.default;
    if (typeof value === "number" && (f.type === "int" || f.type === "number")) {
      const clamped = Math.min(f.max ?? value, Math.max(f.min ?? value, value));
      if (clamped !== value) adjusted.push(f.key);
      value = clamped;
    }
    settings[f.key] = value;
  }
  return { settings, adjusted };
}

function settingFor(agentId: string, e: Evaluator): AgentEvalSetting {
  const row = q.settings[agentId]?.[e.id];
  const overrides = row?.overrides ?? {};
  const eff = effective(e, overrides);
  return {
    evaluator_id: e.id,
    name: e.name,
    display_name: e.display_name,
    description: e.description ?? null,
    kind: e.kind,
    scope: e.scope,
    cost_class: e.cost_class,
    output_kind: e.output_kind,
    enabled: row ? row.enabled : e.enabled_by_default,
    enabled_by_default: e.enabled_by_default,
    is_overridden: Boolean(row),
    adjusted_fields: eff.adjusted,
    is_headline: row?.is_headline ?? false,
    headline_position: row?.headline_position ?? null,
    overrides,
    effective_settings: eff.settings,
    settings_schema: e.settings_schema as Record<string, unknown>,
    current_version: e.current_version,
    est_cost_per_call_usd: e.cost_class === "llm_judge" ? 0.0012 : null,
  };
}

const byDisplayName = (a: { display_name: string }, b: { display_name: string }) => a.display_name.localeCompare(b.display_name);

function settingsList(agentId: string): AgentEvalSetting[] {
  return catalogFor(agentType(agentId))
    .map((e) => settingFor(agentId, e))
    .sort(byDisplayName);
}

// Runs ----------------------------------------------------------------------------------------

const indexOf = (callId: string) => {
  const m = /MOCKCALL(\d{4})/.exec(callId);
  return m ? Number(m[1]) : [...callId].reduce((h, ch) => (h * 31 + ch.charCodeAt(0)) % 997, 7);
};
const sec = (ms: number) => `${(ms / 1000).toFixed(1)} s`;
const clock = (ms: number) => `${Math.floor(ms / 60_000)}:${String(Math.floor((ms % 60_000) / 1000)).padStart(2, "0")}`;
const fmt = (n: number) => n.toLocaleString("en-US");

function fails(name: string, i: number, flow: boolean): boolean {
  const p = i % 7;
  if (p === 3) return true;
  if (p === 1) return name === "latency_slo" || name === "intent_fulfillment" || name === "flow_completion";
  if (p === 5) return name === "audio_silence";
  if (p === 6 && flow) return name === "stuck_loop_detector";
  return false;
}

const NODES = [
  { id: "node_greeting", label: "Greeting" },
  { id: "node_collect", label: "Collect details" },
  { id: "node_book", label: "Book slot" },
  { id: "node_wrap", label: "Wrap up" },
];

function judgeRationale(name: string, failed: boolean): { score: number; rationale: string; quote?: string; turns: number[] } {
  const table: Record<string, [string, string, string, string]> = {
    intent_fulfillment: [
      "The caller wanted the status of order A12 and the agent confirmed it ships on Thursday.",
      "Order A12 ships Thursday.",
      "The caller asked to change the delivery address; the agent never confirmed the change before the call ended.",
      "Let me try again.",
    ],
    tool_call_correctness: [
      "lookup_order was called once, with the order number the caller gave.",
      "lookup_order(id: A12)",
      "lookup_order timed out and the agent neither retried nor told the caller what happened.",
      "Sorry, let me try again",
    ],
    factual_consistency: [
      "Every reply matched the knowledge base passages the agent retrieved.",
      "Returns are free within 30 days.",
      "The agent quoted a 60 day return window; the retrieved policy says 30 days.",
      "You have 60 days to return it.",
    ],
    kb_relevance: [
      "Both searches returned the shipping policy the caller asked about.",
      "Shipping policy",
      "The search for warranty terms returned the returns page, which did not answer the question.",
      "Returns and exchanges",
    ],
    transition_correctness: [
      "Each transition matched what the caller said at that point.",
      "Book slot",
      "The caller asked for a callback but the flow moved to Book slot instead of Callback.",
      "Book slot",
    ],
  };
  const row = table[name] ?? ["The call met this check.", "", "The call did not meet this check.", ""];
  return failed
    ? { score: 0.22, rationale: row[2], quote: row[3], turns: [3] }
    : { score: 0.86, rationale: row[0], quote: row[1], turns: [2] };
}

function buildRun(call: CallListItem, e: Evaluator, settings: Record<string, unknown>, trigger: EvaluatorRun["trigger"], createdAt: string): EvaluatorRun {
  const i = indexOf(call.call_id);
  const flow = agentType(call.agent.id) === "flow";
  const failed = fails(e.name, i, flow);
  const base: EvaluatorRun = {
    id: nextId("evr"),
    evaluator_id: e.id,
    evaluator_name: e.name,
    evaluator_display_name: e.display_name,
    evaluator_version: e.current_version,
    scope: e.scope,
    trigger,
    status: "completed",
    skip_reason: null,
    error: null,
    verdict: "pass",
    score: null,
    rationale: null,
    settings_snapshot: settings,
    judge_model: e.cost_class === "llm_judge" ? String(settings.judge_model ?? DEFAULT_JUDGE) : null,
    cost_usd: e.cost_class === "llm_judge" ? 0.0012 : null,
    items: [],
    created_at: createdAt,
    completed_at: createdAt,
    superseded_at: null,
  };
  const finish = (items: ResultItem[], rationale: string, score: number | null): EvaluatorRun => {
    const applicable = items.filter((it) => it.verdict !== "not_applicable");
    const verdict: Verdict = applicable.length === 0 ? "not_applicable" : applicable.some((it) => it.verdict === "fail") ? "fail" : "pass";
    return { ...base, items, verdict, score, rationale };
  };

  if (e.name === "intent_fulfillment" && trigger === "pipeline" && i % 4 === 2 && !failed) {
    return { ...base, status: "skipped", skip_reason: "not_sampled", verdict: null, cost_usd: null, rationale: null };
  }
  if (e.kind === "custom") {
    const pass = i % 5 !== 3;
    return finish(
      [{ verdict: pass ? "pass" : "fail", score: pass ? 1 : 0, rationale: pass ? "No agent turn matched the pattern." : 'Turn 3: "approval is guaranteed".', evidence: { turn_indices: pass ? [] : [3] } }],
      pass ? "No agent turn matched the pattern." : 'The agent said "approval is guaranteed" in turn 3.',
      pass ? 1 : 0,
    );
  }
  switch (e.name) {
    case "latency_slo": {
      const threshold = Number(settings.threshold_ms ?? 3000);
      const turns = Array.from({ length: 6 }, (_, t) => (failed && t === 3 ? threshold + 400 + (i % 5) * 100 : 760 + ((i * 37 + t * 211) % 1400)));
      const slow = turns.map((ms, t) => ({ ms, t })).filter((x) => x.ms > threshold);
      const items: ResultItem[] = turns.map((ms, t) => ({
        turn_index: t + 1,
        verdict: ms > threshold ? "fail" : "pass",
        score: ms,
        rationale:
          ms > threshold
            ? `The agent took ${fmt(ms)} ms to start answering, over the ${fmt(threshold)} ms threshold.`
            : `Answered in ${fmt(ms)} ms, under the ${fmt(threshold)} ms threshold.`,
        evidence: { turn_indices: [t + 1] },
      }));
      const mean = Math.round(turns.reduce((a, b) => a + b, 0) / turns.length);
      return finish(
        items,
        slow.length
          ? `${slow.length} of ${turns.length} turns were slower than ${fmt(threshold)} ms (turn ${slow.map((s) => s.t + 1).join(", ")}, ${slow.map((s) => `${fmt(s.ms)} ms`).join(", ")}).`
          : `All ${turns.length} turns answered under ${fmt(threshold)} ms.`,
        mean,
      );
    }
    case "audio_silence": {
      if (!call.has_recording) {
        return finish([{ verdict: "not_applicable", score: null, rationale: "No recording." }], "No recording.", null);
      }
      const max = Number(settings.max_acceptable_silence_ms ?? 3000);
      const longest = failed ? 10_200 : 1_400 + (i % 6) * 200;
      const start = failed ? 65_000 : 42_000;
      const item: ResultItem = {
        verdict: longest > max ? "fail" : "pass",
        score: longest,
        start_ms: start,
        duration_ms: longest,
        rationale: `Longest silence ${sec(longest)} at ${clock(start)}; next longest 2.1 s at 0:18.`,
      };
      return finish(
        [item],
        longest > max
          ? `Silence of ${sec(longest)} at ${clock(start)} while the agent looked up the order, over the ${sec(max)} limit.`
          : `Longest silence ${sec(longest)} at ${clock(start)}, under the ${sec(max)} limit.`,
        longest,
      );
    }
    case "flow_completion": {
      const last = failed ? NODES[1]! : NODES[3]!;
      return finish(
        [
          {
            verdict: failed ? "fail" : "pass",
            score: failed ? 0 : 1,
            flow_node_id: last.id,
            flow_node_label: last.label,
            rationale: failed ? `Ended on ${last.label}, which is not an end or transfer node.` : `Ended on ${last.label}, an end node.`,
          },
        ],
        failed ? `The call stopped on ${last.label} before the flow finished.` : `The call reached ${last.label}.`,
        failed ? 0 : 1,
      );
    }
    case "node_dead_end": {
      const items: ResultItem[] = NODES.map((n, k) => {
        const bad = failed && k === 1;
        return {
          verdict: bad ? "fail" : "pass",
          score: bad ? 0 : 1,
          flow_node_id: n.id,
          flow_node_label: n.label,
          rationale: bad ? `The call ended on ${n.label} mid-flow.` : k === 3 ? `${n.label} is an end node.` : `The conversation moved on from ${n.label}.`,
        };
      });
      return finish(items, failed ? "The call ended on Collect details without an end or transfer." : "No node was a dead end.", failed ? 0.75 : 1);
    }
    case "stuck_loop_detector": {
      const max = Number(settings.max_visits_per_node ?? 3);
      const items: ResultItem[] = NODES.map((n, k) => {
        const visits = failed && k === 1 ? max + 2 : 1 + (k === 1 ? 1 : 0);
        return {
          verdict: visits > max ? "fail" : "pass",
          score: visits,
          flow_node_id: n.id,
          flow_node_label: n.label,
          rationale: `Visited ${visits} ${visits === 1 ? "time" : "times"} (limit ${max}).`,
        };
      });
      return finish(items, failed ? `Collect details was visited ${max + 2} times, over the limit of ${max}.` : "No node was revisited past the limit.", null);
    }
    case "process_reward": {
      const scores = [1, 1, failed ? -1 : 0, 1];
      const items: ResultItem[] = scores.map((s, t) => ({
        turn_index: t + 1,
        verdict: s === -1 ? "fail" : "pass",
        score: s,
        rationale: s === 1 ? "Moved the caller closer to their goal." : s === 0 ? "Neutral: confirmed details already given." : "Asked again for the order number the caller had already given.",
      }));
      return finish(items, failed ? "Turn 3 was a step back." : "Every turn kept the call moving.", scores.reduce((a, b) => a + b, 0) / scores.length);
    }
    case "anomaly_detection":
      return finish([{ verdict: "not_applicable", score: null, rationale: "Insufficient data, 12 comparable calls of 30 needed." }], "Insufficient data, 12 comparable calls of 30 needed.", null);
    default: {
      const r = judgeRationale(e.name, failed);
      return finish([{ verdict: failed ? "fail" : "pass", score: r.score, rationale: r.rationale, evidence: { turn_indices: r.turns, quote: r.quote ?? null } }], r.rationale, r.score);
    }
  }
}

function findCall(callId: string): CallListItem | undefined {
  return mockCalls().calls.find((c) => c.call_id === callId);
}

function enabledEvaluators(agentId: string): { e: Evaluator; settings: Record<string, unknown> }[] {
  return catalogFor(agentType(agentId))
    .map((e) => ({ e, s: settingFor(agentId, e) }))
    .filter((x) => x.s.enabled)
    .map((x) => ({ e: x.e, settings: x.s.effective_settings }));
}

function runsOf(call: CallListItem): PendingRun[] {
  if (!q.seeded.has(call.call_id)) {
    q.seeded.add(call.call_id);
    const list: PendingRun[] = [];
    if (call.status === "completed" || call.status === "voicemail") {
      for (const { e, settings } of enabledEvaluators(call.agent.id)) list.push(buildRun(call, e, settings, "pipeline", call.started_at));
    } else if (call.status === "processing") {
      for (const { e, settings } of enabledEvaluators(call.agent.id)) {
        const final = buildRun(call, e, settings, "pipeline", call.started_at);
        list.push({ ...final, status: "running", verdict: null, score: null, rationale: null, items: [], completed_at: null });
      }
    }
    q.runs[call.call_id] = list;
  }
  const now = Date.now();
  const list = q.runs[call.call_id]!;
  q.runs[call.call_id] = list.map((r) => (r._final && r._at !== undefined && r._at <= now ? r._final : r));
  return q.runs[call.call_id]!;
}

const current = (runs: EvaluatorRun[]) => runs.filter((r) => !r.superseded_at);

function evalStatus(runs: EvaluatorRun[]): "not_evaluated" | "running" | "passed" | "failed" | "error" {
  const cur = current(runs);
  if (!cur.length) return "not_evaluated";
  if (cur.some((r) => r.status === "pending" || r.status === "running")) return "running";
  if (cur.some((r) => r.status === "completed" && r.verdict === "fail")) return "failed";
  if (cur.some((r) => r.status === "completed")) return "passed";
  return "error";
}

function counts(runs: EvaluatorRun[]) {
  const done = current(runs).filter((r) => r.status === "completed");
  return { pass: done.filter((r) => r.verdict === "pass").length, fail: done.filter((r) => r.verdict === "fail").length };
}

const strip = (r: PendingRun): EvaluatorRun => {
  const { _final, _at, ...rest } = r;
  void _final;
  void _at;
  return rest;
};

// Labels --------------------------------------------------------------------------------------

function seedLabels(viewerUser: { id: string; display_name: string }) {
  if (q.labelsSeeded) return;
  q.labelsSeeded = true;
  for (const c of mockCalls().calls) {
    const i = indexOf(c.call_id);
    if (c.status !== "completed" || i < 18) continue;
    const runs = current(runsOf(c));
    const intent = runs.find((r) => r.evaluator_name === "intent_fulfillment" || r.evaluator_name === "flow_completion");
    const humanGood = intent?.verdict === "fail" ? i % 3 === 0 : i % 4 !== 1;
    const at = new Date(Date.parse(c.started_at) + 3_600_000).toISOString();
    const list: Annotation[] = [
      { id: nextId("ann"), call_id: c.call_id, user: viewerUser, label: humanGood ? "good" : "bad", note: i % 6 === 0 ? "Caller sounded satisfied at the end." : null, created_at: at, updated_at: at },
    ];
    if (i % 8 === 0) {
      list.push({ id: nextId("ann"), call_id: c.call_id, user: TEAMMATE, label: i % 16 === 0 ? (humanGood ? "bad" : "good") : humanGood ? "good" : "bad", note: "Checked against the recording.", created_at: at, updated_at: at });
    }
    q.annotations[c.call_id] = list;
  }
}

function annotationsOf(callId: string, request: Request) {
  seedLabels(viewer(request));
  return q.annotations[callId] ?? [];
}

function resolvedLabel(list: Annotation[]): "good" | "bad" | "conflict" | null {
  if (!list.length) return null;
  const good = list.filter((a) => a.label === "good").length;
  const bad = list.length - good;
  return good === bad ? "conflict" : good > bad ? "good" : "bad";
}

// Analysis ------------------------------------------------------------------------------------

function liveVariables(agentId: string): StoredVar[] {
  return q.variables.filter((v) => v.agent_id === agentId && !v.deleted_at).sort((a, b) => a.position - b.position);
}

function valueFor(v: StoredVar, i: number): boolean | string | number | null {
  if (i % 9 === 4) return null;
  if (v.type === "boolean") return v.name === "callback_requested" ? i % 5 === 0 : i % 7 !== 3;
  if (v.type === "choice") return v.choices?.[i % (v.choices?.length ?? 1)] ?? null;
  if (v.type === "number") return (i % 4) + 1;
  return "Asked about delivery times";
}

function buildAnalysis(call: CallListItem): CallAnalysis {
  const i = indexOf(call.call_id);
  if (call.status === "processing") return { call_id: call.call_id, status: "running", values: [] };
  if (call.status !== "completed" && call.status !== "voicemail") return { call_id: call.call_id, status: "skipped", skip_reason: null, values: [] };
  const vars = liveVariables(call.agent.id);
  const values: NonNullable<CallAnalysis["values"]> = vars.map((v) => ({ variable_id: v.id, name: v.name, type: v.type, value: valueFor(v, i), status: "current" }));
  if (i > 30 && agentType(call.agent.id) === "single_prompt") values.push({ variable_id: null, name: "order_status", type: "string", value: "shipped", status: "renamed" });
  const sentiment = i % 7 === 3 ? "negative" : i % 5 === 0 ? "neutral" : "positive";
  return {
    call_id: call.call_id,
    status: "completed",
    skip_reason: null,
    model: "openai/gpt-5-mini",
    summary:
      i % 7 === 3
        ? "The caller asked to change a delivery address. The order lookup timed out twice and the call ended without the change being made."
        : "The caller asked where order A12 was. The agent looked it up, confirmed it ships on Thursday and offered a tracking link by text.",
    sentiment,
    values,
    analyzed_at: call.started_at,
  };
}

function analysisOf(call: CallListItem): CallAnalysis {
  const stored = q.analysis[call.call_id];
  if (stored && stored._at !== undefined && stored._at <= Date.now()) {
    q.analysis[call.call_id] = { ...buildAnalysis(call), analyzed_at: nowIso() };
  }
  const out = q.analysis[call.call_id] ?? buildAnalysis(call);
  const { _at, ...rest } = out as CallAnalysis & { _at?: number };
  void _at;
  return rest;
}

// Calibration math (spec 007 R7) --------------------------------------------------------------

export function wilson(k: number, n: number, z = 1.96): { low: number; high: number } | null {
  if (n === 0) return null;
  const p = k / n;
  const denom = 1 + (z * z) / n;
  const centre = (p + (z * z) / (2 * n)) / denom;
  const half = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / denom;
  return { low: Math.max(0, centre - half), high: Math.min(1, centre + half) };
}

export function reading(m: { both_pass: number; both_fail: number; over_eager: number; missed: number; n: number }): CalibrationRow["reading"] {
  if (m.n < 5) return "insufficient";
  const a = (m.both_pass + m.both_fail) / m.n;
  if (a >= 0.85) return "strong";
  if (a < 0.5) return "low";
  if (m.over_eager > 0 && m.over_eager >= 2 * m.missed) return "over_eager";
  if (m.missed > 0 && m.missed >= 2 * m.over_eager) return "misses";
  return "partial";
}

function calibrationRows(request: Request, agentId: string | null): CalibrationRow[] {
  seedLabels(viewer(request));
  const rows = new Map<string, CalibrationRow>();
  for (const c of mockCalls().calls) {
    if (c.origin !== "live" || (agentId && c.agent.id !== agentId)) continue;
    const label = resolvedLabel(q.annotations[c.call_id] ?? []);
    if (label !== "good" && label !== "bad") continue;
    for (const r of current(runsOf(c))) {
      if (r.status !== "completed" || (r.verdict !== "pass" && r.verdict !== "fail")) continue;
      const e = evaluatorById(r.evaluator_id);
      if (!e) continue;
      const row =
        rows.get(e.id) ??
        ({
          evaluator_id: e.id,
          evaluator_name: e.name,
          display_name: e.display_name,
          scope: e.scope,
          cost_class: e.cost_class,
          evaluator_version: e.current_version,
          version_scope: "current",
          flow_node_id: null,
          flow_node_label: null,
          both_pass: 0,
          both_fail: 0,
          over_eager: 0,
          missed: 0,
          n: 0,
          agreement_rate: null,
          agreement_ci: null,
          under_min_sample: true,
          reading: "insufficient",
          current_threshold: null,
          best_threshold: null,
          best_threshold_agreement: null,
        } satisfies CalibrationRow);
      if (r.verdict === "pass" && label === "good") row.both_pass++;
      else if (r.verdict === "fail" && label === "bad") row.both_fail++;
      else if (r.verdict === "fail") row.over_eager++;
      else row.missed++;
      row.n++;
      rows.set(e.id, row);
    }
  }
  return [...rows.values()]
    .map((row) => ({
      ...row,
      agreement_rate: row.n ? (row.both_pass + row.both_fail) / row.n : null,
      agreement_ci: wilson(row.both_pass + row.both_fail, row.n),
      under_min_sample: row.n < 5,
      reading: reading(row),
    }))
    .sort((a, b) => Number(a.under_min_sample) - Number(b.under_min_sample) || a.display_name.localeCompare(b.display_name));
}

// Review queue --------------------------------------------------------------------------------

function hash(s: string): number {
  let h = 2166136261;
  for (const ch of s) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return h >>> 0;
}

function queueItems(request: Request, agentId: string | null): QueueItem[] {
  const me = viewer(request);
  seedLabels(me);
  return mockCalls()
    .calls.filter((c) => c.origin === "live" && c.status === "completed" && (!agentId || c.agent.id === agentId))
    .filter((c) => !(q.annotations[c.call_id] ?? []).some((a) => a.user.id === me.id))
    .map((c) => {
      const k = counts(runsOf(c));
      return {
        call_id: c.call_id,
        agent_id: c.agent.id,
        agent_name: c.agent.name,
        ended_at: new Date(Date.parse(c.started_at) + c.duration_s * 1000).toISOString(),
        duration_s: c.duration_s,
        sentiment: analysisOf(c).sentiment ?? null,
        eval_count: k.pass + k.fail,
        pass_count: k.pass,
        fail_count: k.fail,
      };
    });
}

function ordered(items: QueueItem[], strategy: string, userId: string): QueueItem[] {
  const recent = (a: QueueItem, b: QueueItem) => b.ended_at.localeCompare(a.ended_at);
  if (strategy === "failed") return items.filter((x) => x.fail_count >= 1).sort((a, b) => b.fail_count - a.fail_count || recent(a, b));
  if (strategy === "random") {
    const day = new Date().toISOString().slice(0, 10);
    return [...items].sort((a, b) => hash(a.call_id + userId + day) - hash(b.call_id + userId + day));
  }
  return items
    .filter((x) => x.pass_count >= 1 && x.fail_count >= 1)
    .sort((a, b) => Math.abs(a.pass_count - a.fail_count) - Math.abs(b.pass_count - b.fail_count) || recent(a, b));
}

// Custom checks -------------------------------------------------------------------------------

function phraseProblem(config: PhraseCheckConfig): string | null {
  if (!config.pattern?.trim()) return "Enter a phrase or pattern.";
  if (config.pattern.length > 500) return "Keep the pattern under 500 characters.";
  if (config.is_regex) {
    if (/\\[1-9]|\(\?[=!<]/.test(config.pattern)) return "Patterns cannot use backreferences or lookarounds; they must run in linear time.";
    try {
      new RegExp(config.pattern);
    } catch {
      return "This is not a valid pattern.";
    }
  }
  return null;
}

function validateCustom(type: string, config: CustomConfig | undefined): Response | null {
  if (!config) return invalid("/config", "Fill in the check.");
  if (type === "phrase_check") {
    const msg = phraseProblem(config as PhraseCheckConfig);
    return msg ? invalid("/config/pattern", msg) : null;
  }
  const judge = config as JudgeQuestionConfig;
  if (!judge.question || judge.question.trim().length < 5) return invalid("/config/question", "Write a yes or no question of at least 5 characters.");
  if (judge.question.length > 1000) return invalid("/config/question", "Keep the question under 1,000 characters.");
  if (judge.judge_model && !JUDGE_MODELS.some((m) => m.model_id === judge.judge_model)) return invalid("/config/judge_model", "Choose one of the listed judge models");
  return null;
}

const TRANSCRIPT_TURNS = [
  { role: "agent", text: "Hi, thanks for calling. How can I help?" },
  { role: "user", text: "I applied for the store card. Will it go through?" },
  { role: "agent", text: "Let me check your details." },
  { role: "agent", text: "Good news, approval is guaranteed for existing customers." },
  { role: "user", text: "Great, thanks." },
];

function trial(type: string, config: CustomConfig): TrialResult {
  if (type === "phrase_check") {
    const c = config as PhraseCheckConfig;
    const flags = c.case_sensitive ? "" : "i";
    const re = c.is_regex ? new RegExp(c.pattern, flags) : new RegExp(c.pattern.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), flags);
    const turns = TRANSCRIPT_TURNS.map((t, idx) => ({ ...t, idx })).filter((t) => c.target === "both" || (c.target === "user" ? t.role === "user" : t.role === "agent"));
    const hit = turns.find((t) => re.test(t.text));
    const pass = c.mode === "forbidden" ? !hit : Boolean(hit);
    return {
      verdict: pass ? "pass" : "fail",
      score: pass ? 1 : 0,
      rationale: hit
        ? `Turn ${hit.idx + 1} matched: "${hit.text}". ${c.mode === "forbidden" ? "The phrase is forbidden." : "The phrase was required and found."}`
        : `No ${c.target === "both" ? "" : c.target === "user" ? "caller " : "agent "}turn matched. ${c.mode === "forbidden" ? "Nothing forbidden was said." : "The required phrase was never said."}`.replace("  ", " "),
      evidence: { turn_indices: hit ? [hit.idx + 1] : [], quote: hit?.text ?? null },
      charged_usd: null,
    };
  }
  const c = config as JudgeQuestionConfig;
  const yes = !/never|refuse|forbid/i.test(c.question);
  const pass = (c.pass_when === "yes") === yes;
  return {
    verdict: pass ? "pass" : "fail",
    score: yes ? 0.9 : 0.1,
    rationale: `${yes ? "Yes" : "No"}. In turn 3 the agent said "Let me check your details." and then confirmed the account on file before answering.`,
    evidence: { turn_indices: [3], quote: "Let me check your details." },
    charged_usd: 0.0012,
  };
}

// Calls list hook -----------------------------------------------------------------------------

setQualitySummarizer((call, request) => {
  const me = viewer(request);
  seedLabels(me);
  const runs = runsOf(call);
  const k = counts(runs);
  const mine = (q.annotations[call.call_id] ?? []).find((a) => a.user.id === me.id);
  return { eval_status: evalStatus(runs), pass_count: k.pass, fail_count: k.fail, label: mine?.label ?? null };
});

// Handlers ------------------------------------------------------------------------------------

const variableError = (body: Partial<AnalysisVariable>, agentId: string, selfId?: string): Response | null => {
  if (body.name !== undefined && !MACHINE_NAME_RE.test(body.name)) return invalid("/name", "Use lowercase letters, digits and underscores, starting with a letter");
  if (body.description !== undefined && (!body.description.trim() || body.description.length > 500)) return invalid("/description", "Describe what to capture in 1 to 500 characters.");
  const type = body.type;
  if (type && type !== "choice" && body.choices) return invalid("/choices", "Choices apply only to the fixed set type.");
  if (type === "choice") {
    const ch = body.choices ?? [];
    if (ch.length < 2 || ch.length > 20) return invalid("/choices", "Add 2 to 20 choices.");
    if (new Set(ch).size !== ch.length) return invalid("/choices", "Each choice must be different.");
  }
  if (body.name && liveVariables(agentId).some((v) => v.name === body.name && v.id !== selfId)) {
    return problem(409, "conflict", "Name in use", `This agent already has a variable named ${body.name}.`);
  }
  return null;
};

export const qualityHandlers = [
  // Analysis variables
  http.get(url("/agents/:id/analysis-variables"), ({ params }) => {
    const id = String(params.id);
    if (!agentExists(id)) return problem(404, "not_found", "Not found", "No agent with that id.");
    return json({ items: liveVariables(id).map(({ deleted_at, ...v }) => (void deleted_at, v)) });
  }),
  http.post(url("/agents/:id/analysis-variables"), async ({ params, request }) => {
    const agentId = String(params.id);
    const body = (await request.json()) as Partial<AnalysisVariable>;
    if (!body.name || !body.type || body.description === undefined) return invalid("/name", "Name, type and description are required.");
    const err = variableError(body, agentId);
    if (err) return err;
    if (liveVariables(agentId).length >= 25) return problem(409, "limit_reached", "Limit reached", "An agent can have up to 25 analysis variables.");
    const row: StoredVar = {
      id: nextId("var"),
      agent_id: agentId,
      name: body.name,
      type: body.type,
      description: body.description,
      choices: body.type === "choice" ? (body.choices ?? null) : null,
      position: liveVariables(agentId).length,
      created_at: nowIso(),
      updated_at: nowIso(),
      deleted_at: null,
    };
    q.variables.push(row);
    const { deleted_at, ...out } = row;
    void deleted_at;
    return json(out, 201);
  }),
  http.put(url("/agents/:id/analysis-variables/order"), async ({ params, request }) => {
    const { variable_ids } = (await request.json()) as { variable_ids: string[] };
    const live = liveVariables(String(params.id));
    if (variable_ids.length !== live.length || !live.every((v) => variable_ids.includes(v.id))) return invalid("/variable_ids", "List every variable exactly once.");
    variable_ids.forEach((id, pos) => {
      const v = q.variables.find((x) => x.id === id);
      if (v) v.position = pos;
    });
    return new HttpResponse(null, { status: 204 });
  }),
  http.patch(url("/analysis-variables/:id"), async ({ params, request }) => {
    const v = q.variables.find((x) => x.id === params.id && !x.deleted_at);
    if (!v) return problem(404, "not_found", "Not found", "No variable with that id.");
    const body = (await request.json()) as Partial<AnalysisVariable>;
    const merged = { ...v, ...body };
    const err = variableError({ ...body, type: merged.type, choices: body.type && body.type !== "choice" && !("choices" in body) ? null : merged.choices }, v.agent_id, v.id);
    if (err) return err;
    Object.assign(v, body, { choices: merged.type === "choice" ? merged.choices : null, updated_at: nowIso() });
    const { deleted_at, ...out } = v;
    void deleted_at;
    return json(out);
  }),
  http.delete(url("/analysis-variables/:id"), ({ params }) => {
    const v = q.variables.find((x) => x.id === params.id && !x.deleted_at);
    if (!v) return problem(404, "not_found", "Not found", "No variable with that id.");
    v.deleted_at = nowIso();
    return new HttpResponse(null, { status: 204 });
  }),
  http.get(url("/calls/:id/analysis"), ({ params }) => {
    const call = findCall(String(params.id));
    return call ? json(analysisOf(call)) : problem(404, "not_found", "Not found", "No call with that id.");
  }),
  http.post(url("/calls/:id/analysis/rerun"), ({ params }) => {
    const call = findCall(String(params.id));
    if (!call) return problem(404, "not_found", "Not found", "No call with that id.");
    if (call.status !== "completed" && call.status !== "voicemail") return problem(409, "call_not_completed", "Not finished", "Analysis can run once the call has finished processing.");
    const pending = { call_id: call.call_id, status: "running" as const, values: [], _at: Date.now() + 1500 };
    q.analysis[call.call_id] = pending;
    return json({ call_id: call.call_id, status: "running", values: [] }, 202);
  }),

  // Catalog
  http.get(url("/evaluators/judge-models"), () => json({ items: JUDGE_MODELS })),
  http.get(url("/evaluators"), ({ request }) => {
    const sp = new URL(request.url).searchParams;
    const kind = sp.get("kind");
    const type = sp.get("agent_type");
    const all = [...BUILTINS, ...q.customs.filter((c) => sp.get("include_deleted") === "true" || !c.deleted_at)]
      .filter((e) => !kind || e.kind === kind)
      .filter((e) => !type || e.agent_types.includes(type as "flow"));
    return json({ items: all.map(({ ...e }) => ({ ...e, versions: undefined })).sort(byDisplayName) });
  }),
  http.post(url("/evaluators/trial"), async ({ request }) => {
    const key = request.headers.get("Idempotency-Key") ?? "";
    if (key.length < 8) return invalid("/Idempotency-Key", "Idempotency-Key is required.");
    if (q.trials[key]) return json(q.trials[key]);
    const body = (await request.json()) as { evaluator_type: string; config: CustomConfig; call_id: string };
    if (!findCall(body.call_id)) return problem(404, "not_found", "Not found", "No call with that id.");
    const err = validateCustom(body.evaluator_type, body.config);
    if (err) return err;
    q.trials[key] = trial(body.evaluator_type, body.config);
    return json(q.trials[key]);
  }),
  http.post(url("/evaluators"), async ({ request }) => {
    const body = (await request.json()) as { name?: string; display_name: string; description?: string | null; evaluator_type: "phrase_check" | "llm_judge_custom"; config: CustomConfig };
    const name = body.name ?? toVariableName(body.display_name ?? "");
    if (!name) return invalid("/display_name", "Use a name with at least one letter.");
    const err = validateCustom(body.evaluator_type, body.config);
    if (err) return err;
    if (q.customs.some((c) => !c.deleted_at && c.name === name)) return problem(409, "name_taken", "Name in use", `You already have a custom check named ${name}`);
    if (q.customs.filter((c) => !c.deleted_at).length >= 50) return problem(409, "limit_reached", "Limit reached", "A workspace can have up to 50 custom checks.");
    const judge = body.evaluator_type === "llm_judge_custom";
    const config = judge ? { judge_model: DEFAULT_JUDGE, ...(body.config as JudgeQuestionConfig) } : { ...(body.config as PhraseCheckConfig), is_regex: (body.config as PhraseCheckConfig).is_regex ?? false, case_sensitive: (body.config as PhraseCheckConfig).case_sensitive ?? false };
    const row: Evaluator & { versions: CustomVersion[] } = {
      id: nextId("evl"),
      kind: "custom",
      evaluator_type: body.evaluator_type,
      name,
      display_name: body.display_name,
      description: body.description?.trim() ? body.description : null,
      scope: "call",
      cost_class: judge ? "llm_judge" : "free",
      output_kind: "class",
      agent_types: ["single_prompt", "flow"],
      settings_schema: { fields: [] },
      score_range: { min: 0, max: 1 },
      current_version: 1,
      enabled_by_default: false,
      config,
      deleted_at: null,
      versions: [{ version: 1, judge_model: judge ? (config as JudgeQuestionConfig).judge_model! : null, definition: config as Record<string, unknown>, created_at: nowIso() }],
    };
    q.customs.push(row);
    const { versions, ...out } = row;
    void versions;
    return json(out, 201);
  }),
  http.get(url("/evaluators/:id"), ({ params }) => {
    const e = evaluatorById(String(params.id));
    if (!e) return problem(404, "not_found", "Not found", "No check with that id.");
    const custom = q.customs.find((c) => c.id === e.id);
    return json({ ...e, versions: custom?.versions ?? [{ version: e.current_version, judge_model: null, definition: {}, created_at: "2026-10-16T09:00:00Z" }] });
  }),
  http.patch(url("/evaluators/:id"), async ({ params, request }) => {
    if (BUILTINS.some((b) => b.id === params.id)) return problem(403, "forbidden", "Built-in", "Built-in checks cannot be edited.");
    const c = q.customs.find((x) => x.id === params.id && !x.deleted_at);
    if (!c) return problem(404, "not_found", "Not found", "No check with that id.");
    const body = (await request.json()) as { display_name?: string; description?: string | null; config?: CustomConfig };
    if (body.config) {
      const err = validateCustom(c.evaluator_type, body.config);
      if (err) return err;
      if (JSON.stringify(body.config) !== JSON.stringify(c.config)) {
        c.current_version += 1;
        c.config = body.config;
        c.versions.push({ version: c.current_version, judge_model: (body.config as JudgeQuestionConfig).judge_model ?? null, definition: body.config as Record<string, unknown>, created_at: nowIso() });
      }
    }
    if (body.display_name !== undefined) c.display_name = body.display_name;
    if (body.description !== undefined) c.description = body.description?.trim() ? body.description : null;
    const { versions, ...out } = c;
    void versions;
    return json(out);
  }),
  http.delete(url("/evaluators/:id"), ({ params }) => {
    if (BUILTINS.some((b) => b.id === params.id)) return problem(403, "forbidden", "Built-in", "Built-in checks cannot be deleted.");
    const c = q.customs.find((x) => x.id === params.id && !x.deleted_at);
    if (!c) return problem(404, "not_found", "Not found", "No check with that id.");
    c.deleted_at = nowIso();
    return new HttpResponse(null, { status: 204 });
  }),

  // Settings
  http.get(url("/agents/:id/eval-settings"), ({ params }) => {
    const id = String(params.id);
    if (!agentExists(id)) return problem(404, "not_found", "Not found", "No agent with that id.");
    return json({ items: settingsList(id) });
  }),
  http.put(url("/agents/:id/eval-settings/:evl"), async ({ params, request }) => {
    const agentId = String(params.id);
    const e = evaluatorById(String(params.evl));
    if (!agentExists(agentId) || !e || e.deleted_at) return problem(404, "not_found", "Not found", "No such check on this agent.");
    if (!e.agent_types.includes(agentType(agentId))) return invalid("/evaluator_id", "This check does not apply to this agent type.");
    const body = (await request.json()) as { enabled: boolean; overrides?: Record<string, unknown>; is_headline?: boolean };
    const fields = schemaFields(e.settings_schema);
    const errors: { pointer: string; code: string; message: string }[] = [];
    for (const [key, value] of Object.entries(body.overrides ?? {})) {
      const f = fields.find((x) => x.key === key);
      if (!f) errors.push({ pointer: `/overrides/${key}`, code: "unknown_setting", message: `${key} is not a setting of this check` });
      else {
        const msg = fieldError(f, value, JUDGE_MODELS);
        if (msg) errors.push({ pointer: `/overrides/${key}`, code: "out_of_range", message: msg });
      }
    }
    if (errors.length) return problem(422, "validation_failed", "Request failed validation", errors[0]!.message, errors);
    q.settings[agentId] ??= {};
    const rows = q.settings[agentId];
    const prev = rows[e.id];
    let position = prev?.headline_position ?? null;
    if (body.is_headline && !prev?.is_headline) {
      const taken = Object.entries(rows).filter(([id, r]) => id !== e.id && r.is_headline).map(([, r]) => r.headline_position);
      if (taken.length >= 4) return problem(409, "headline_limit", "Too many headline checks", "Up to 4 headline checks per agent");
      position = [1, 2, 3, 4].find((p) => !taken.includes(p)) ?? null;
    }
    rows[e.id] = { enabled: body.enabled, overrides: body.overrides ?? {}, is_headline: Boolean(body.is_headline), headline_position: body.is_headline ? position : null };
    return json(settingFor(agentId, e));
  }),

  // Runs
  http.get(url("/calls/:id/evaluations"), ({ params, request }) => {
    const call = findCall(String(params.id));
    if (!call) return problem(404, "not_found", "Not found", "No call with that id.");
    const runs = runsOf(call);
    const k = counts(runs);
    const withHistory = new URL(request.url).searchParams.get("include_history") === "true";
    return json({
      call_id: call.call_id,
      eval_status: evalStatus(runs),
      pass_count: k.pass,
      fail_count: k.fail,
      runs: current(runs).map(strip),
      ...(withHistory && { history: runs.filter((r) => r.superseded_at).map(strip) }),
    });
  }),
  http.post(url("/calls/:id/evaluations/rerun"), async ({ params, request }) => {
    const call = findCall(String(params.id));
    if (!call) return problem(404, "not_found", "Not found", "No call with that id.");
    if (call.status !== "completed" && call.status !== "voicemail") return problem(409, "call_not_completed", "Not finished", "Checks can run once the call has finished processing.");
    if ((q.activeUntil[call.call_id] ?? 0) > Date.now() || runsOf(call).some((r) => !r.superseded_at && (r.status === "running" || r.status === "pending"))) {
      return problem(409, "checks_running", "Checks are already running", "Checks are already running");
    }
    const body = (await request.json().catch(() => ({}))) as { evaluator_ids?: string[] };
    const enabled = enabledEvaluators(call.agent.id).filter((x) => !body.evaluator_ids?.length || body.evaluator_ids.includes(x.e.id));
    const stamp = nowIso();
    const at = Date.now() + 2500;
    const ids = new Set(enabled.map((x) => x.e.id));
    const runs = runsOf(call).map((r) => (!r.superseded_at && ids.has(r.evaluator_id) ? { ...r, superseded_at: stamp } : r));
    const fresh: PendingRun[] = enabled.map(({ e, settings }) => {
      const final = buildRun(call, e, settings, "rerun", stamp);
      return { ...final, status: "running", verdict: null, score: null, rationale: null, items: [], completed_at: null, _final: { ...final, completed_at: new Date(at).toISOString() }, _at: at };
    });
    q.runs[call.call_id] = [...fresh, ...runs];
    q.activeUntil[call.call_id] = at;
    return json({ run_group_id: nextId("evg"), runs: fresh.map(strip) }, 202);
  }),
  http.get(url("/evals/verdict-diff"), () => json({ items: [] })),

  // Labels
  http.get(url("/calls/:id/annotations"), ({ params, request }) => {
    if (!findCall(String(params.id))) return problem(404, "not_found", "Not found", "No call with that id.");
    const me = viewer(request);
    const list = annotationsOf(String(params.id), request);
    const mine = list.find((a) => a.user.id === me.id) ?? null;
    return json({ mine, items: [...(mine ? [mine] : []), ...list.filter((a) => a !== mine)] });
  }),
  http.put(url("/calls/:id/annotations/me"), async ({ params, request }) => {
    const callId = String(params.id);
    if (!findCall(callId)) return problem(404, "not_found", "Not found", "No call with that id.");
    const body = (await request.json()) as { label: "good" | "bad"; note?: string | null };
    if (body.note && body.note.length > 2000) return invalid("/note", "Keep the note under 2,000 characters.");
    const me = viewer(request);
    const list = annotationsOf(callId, request);
    const existing = list.find((a) => a.user.id === me.id);
    const at = nowIso();
    if (existing) Object.assign(existing, { label: body.label, note: body.note ?? null, updated_at: at });
    else list.push({ id: nextId("ann"), call_id: callId, user: me, label: body.label, note: body.note ?? null, created_at: at, updated_at: at });
    q.annotations[callId] = list;
    return json(list.find((a) => a.user.id === me.id));
  }),
  http.delete(url("/calls/:id/annotations/me"), ({ params, request }) => {
    const callId = String(params.id);
    if (!findCall(callId)) return problem(404, "not_found", "Not found", "No call with that id.");
    const me = viewer(request);
    q.annotations[callId] = annotationsOf(callId, request).filter((a) => a.user.id !== me.id);
    return new HttpResponse(null, { status: 204 });
  }),

  // Review queue
  http.get(url("/review/queue/summary"), ({ request }) => {
    const sp = new URL(request.url).searchParams;
    const me = viewer(request);
    const items = queueItems(request, sp.get("agent_id"));
    return json({ random: items.length, failed: ordered(items, "failed", me.id).length, disagreement: ordered(items, "disagreement", me.id).length });
  }),
  http.get(url("/review/queue"), ({ request }) => {
    const sp = new URL(request.url).searchParams;
    const strategy = sp.get("strategy") ?? "disagreement";
    const limit = Number(sp.get("limit") ?? 50);
    const me = viewer(request);
    return json({ strategy, items: ordered(queueItems(request, sp.get("agent_id")), strategy, me.id).slice(0, limit) });
  }),

  // Calibration
  http.get(url("/calibration/evaluators"), ({ request }) => {
    const sp = new URL(request.url).searchParams;
    const scope = sp.get("version_scope") === "all" ? "all" : "current";
    const rows = calibrationRows(request, sp.get("agent_id")).map((r) => ({ ...r, version_scope: scope, evaluator_version: scope === "current" ? r.evaluator_version : null }));
    return json({ min_sample_for_signal: 5, items: rows });
  }),
  http.get(url("/calibration/summary"), ({ request }) => {
    const sp = new URL(request.url).searchParams;
    const agentId = sp.get("agent_id");
    seedLabels(viewer(request));
    let annotated = 0;
    let evaluated = 0;
    let conflicting = 0;
    for (const c of mockCalls().calls) {
      if (c.origin !== "live" || (agentId && c.agent.id !== agentId)) continue;
      const list = q.annotations[c.call_id] ?? [];
      if (!list.length) continue;
      annotated++;
      const label = resolvedLabel(list);
      if (label === "conflict") conflicting++;
      else if (current(runsOf(c)).some((r) => r.verdict === "pass" || r.verdict === "fail")) evaluated++;
    }
    return json({ annotated_calls: annotated, annotated_and_evaluated_calls: evaluated, conflicting_label_calls: conflicting, min_sample_for_signal: 5 });
  }),
];
