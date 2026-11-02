/**
 * In-memory state behind the spec 009 mock API (issues, fixes, validations, detection), seeded on
 * first use against the demo agents: a validated issue with a failed and a passed attempt, an open
 * issue whose check disagrees with human labels, an applied issue with post-apply figures and a
 * recurrence of it, a dismissed issue seen 20 days ago, a mostly simulated issue and a flow node
 * issue with a drafted node fix. Running detection and validation settle with the clock.
 */
import type { Detection, DetectedIssue, EvaluatorEvidence, FixKind, FixPayload, FixRevision, IssueSample, ValidationAttempt } from "../../api/issues";
import { store as agentStore } from "../agents/store";
import { MOCK_AGENTS } from "../calls/handlers";

const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;
const iso = (ms: number) => new Date(ms).toISOString();

let seq = 0;
export function issueMockId(prefix: string): string {
  seq += 1;
  return `${prefix}_01MOCKISS${String(seq).padStart(17, "0")}`;
}
const callId = (n: number) => `call_01MOCKISSUECALL${String(n).padStart(10, "0")}`;

export const EVALUATORS = {
  factual: { id: "evl_01MOCKEVALFACTUAL0000000001", name: "factual_consistency", display: "Factual consistency" },
  intent: { id: "evl_01MOCKEVALINTENT00000000002", name: "intent_fulfillment", display: "Intent fulfilment" },
  tools: { id: "evl_01MOCKEVALTOOLS000000000003", name: "tool_call_correctness", display: "Tool call correctness" },
  transition: { id: "evl_01MOCKEVALTRANSITION0000004", name: "transition_correctness", display: "Transition correctness" },
} as const;
type Ev = (typeof EVALUATORS)[keyof typeof EVALUATORS];

export interface StoredIssue extends Omit<DetectedIssue, "current_fix" | "latest_validation" | "can_apply" | "apply_blockers" | "sample_preview"> {
  workspace_agent_version: string;
  fixes: FixRevision[];
  attempts: (ValidationAttempt & { _finishAt?: number; _passes?: boolean })[];
  samples: IssueSample[];
}

export interface StoredDetection extends Detection {
  _finishAt?: number;
}

export interface IssueStore {
  agents: { desk: string; billing: string; triage: string; recall: string };
  /** Published version id per agent (apply checks the base version against it). */
  published: Record<string, string>;
  issues: StoredIssue[];
  detections: Record<string, StoredDetection>;
  idem: Record<string, unknown>;
  requests: string[];
  bodies: { path: string; body: unknown }[];
}

let state: IssueStore | null = null;

export function issuesMock(): IssueStore {
  state ??= seed();
  return state;
}

export function resetIssueMocks() {
  state = null;
  seq = 0;
}

export const ALLOWED: Record<"single_prompt" | "flow_node" | "flow", FixKind[]> = {
  single_prompt: ["prompt_edit", "add_guardrail", "tool_description_edit", "kb_attach"],
  flow_node: [
    "node_prompt_edit",
    "add_guardrail",
    "transition_condition_edit",
    "add_transition",
    "node_tool_attachment",
    "tool_description_edit",
    "kb_attach",
  ],
  flow: ["add_guardrail", "tool_description_edit", "kb_attach"],
};

export function allowedFor(i: Pick<StoredIssue, "agent_type" | "flow_node_id">): FixKind[] {
  if (i.agent_type !== "flow") return ALLOWED.single_prompt;
  return i.flow_node_id ? ALLOWED.flow_node : ALLOWED.flow;
}

const DESK_PROMPT = [
  "You are the front desk agent for Halcyon Dental.",
  "Greet the caller, find out why they are calling and help them book, move or cancel appointments.",
  "Quote prices from the price list when asked.",
  "Confirm the date and time back to the caller before you book.",
  "Keep answers short and warm.",
].join("\n");

/** A plausible draft for each kind (the mock "AI"). */
export function draftPayload(kind: FixKind, issue: StoredIssue, guidance?: string | null): { payload: FixPayload; rationale: string } {
  const tail = guidance ? ` Guidance followed: ${guidance}` : "";
  switch (kind) {
    case "prompt_edit":
      return {
        payload: {
          current_prompt: DESK_PROMPT,
          proposed_prompt: DESK_PROMPT.replace(
            "Quote prices from the price list when asked.",
            "Quote prices only from the price list. If a price is not listed, say you will confirm it by text.",
          ),
        },
        rationale: `In every sample the agent named a price that is not in the price list. The prompt asks for prices but never says what to do when one is missing.${tail}`,
      };
    case "add_guardrail":
      return {
        payload: {
          placement: issue.agent_type === "flow" ? "all_agent_nodes" : "agent_prompt",
          rule_text: "Only quote prices listed in the price list. If a price is not listed, say you will confirm it by text.",
        },
        rationale: `A single rule covers the failure without touching the rest of the prompt.${tail}`,
      };
    case "node_prompt_edit":
      return {
        payload: {
          node_id: issue.flow_node_id ?? "n_collect01",
          node_label: issue.flow_node_label ?? "Collect address",
          current_instructions: "Ask for the street address and postcode.",
          proposed_instructions:
            "Ask for the street address and postcode.\nRead the full address back and wait for the caller to confirm it before moving on.",
        },
        rationale: `The node moves on as soon as it hears a postcode, so callers never get to correct a misheard street.${tail}`,
      };
    case "tool_description_edit":
      return {
        payload: {
          tool_id: "tool_01MOCKTOOLPRICES00000000001",
          tool_name: "lookup_price",
          current_description: "Looks up a price.",
          proposed_description: "Returns the listed price for one treatment. Call it before quoting any price; if it returns nothing, do not guess.",
        },
        rationale: `The model skipped the tool because its description did not say when to use it.${tail}`,
      };
    case "transition_condition_edit":
      return {
        payload: {
          edge_id: "e_confirm001",
          edge_label: "address_confirmed",
          source_node_id: issue.flow_node_id ?? "n_collect01",
          current_condition: "The caller gave an address.",
          proposed_condition: "The caller confirmed the address after hearing it read back.",
        },
        rationale: `The transition fires before confirmation.${tail}`,
      };
    case "add_transition":
      return {
        payload: {
          source_node_id: issue.flow_node_id ?? "n_collect01",
          target_node_id: "n_confirm01",
          edge_label: "needs_confirmation",
          handoff_condition: "The caller has given an address that has not been read back yet.",
        },
        rationale: `A confirm step exists but nothing leads to it from here.${tail}`,
      };
    case "node_tool_attachment":
      return {
        payload: { node_id: issue.flow_node_id ?? "n_collect01", tools_to_attach: ["tool_01MOCKTOOLADDRESS000000001"], tools_to_detach: [] },
        rationale: `Attaching the address lookup lets the node check what it heard.${tail}`,
      };
    case "kb_attach":
      return {
        payload: { kb_ids_to_attach: [], uncovered_topics: ["Whitening prices", "Payment plans for implants"] },
        rationale: `No knowledge base covers these topics, so the agent improvises. Add documents that cover them, then draft another fix.${tail}`,
      };
  }
}

/** Display diff entries for a payload. */
export function diffOf(kind: FixKind, p: FixPayload): FixRevision["diff"] {
  const q = p as Record<string, unknown>;
  switch (kind) {
    case "prompt_edit":
      return [{ op: "replace", path: "/prompt", old: q.current_prompt, value: q.proposed_prompt }];
    case "node_prompt_edit":
      return [
        {
          op: "replace",
          path: `/flow/graph/nodes/${String(q.node_id)}/config/instructions`,
          old: q.current_instructions,
          value: q.proposed_instructions,
        },
      ];
    case "add_guardrail":
      return [{ op: "add", path: "/prompt", value: q.rule_text }];
    case "tool_description_edit":
      return [{ op: "replace", path: `/tools/${String(q.tool_id)}/description`, old: q.current_description, value: q.proposed_description }];
    case "transition_condition_edit":
      return [{ op: "replace", path: `/flow/graph/edges/${String(q.edge_id)}/condition`, old: q.current_condition, value: q.proposed_condition }];
    case "add_transition":
      return [{ op: "add", path: "/flow/graph/edges/-", value: p }];
    case "node_tool_attachment":
      return [{ op: "replace", path: `/flow/graph/nodes/${String(q.node_id)}/config/tool_ids`, value: q.tools_to_attach }];
    case "kb_attach":
      return [{ op: "add", path: "/kb_ids", value: q.kb_ids_to_attach }];
  }
}

export function makeRevision(
  issue: StoredIssue,
  kind: FixKind,
  payload: FixPayload,
  rationale: string,
  source: "ai" | "manual",
  at: number,
  guidance: string | null = null,
): FixRevision {
  const advisory = kind === "kb_attach" && (payload as { kb_ids_to_attach: string[] }).kb_ids_to_attach.length === 0;
  return {
    revision: issue.fixes.length + 1,
    kind,
    payload,
    rationale,
    source,
    guidance,
    status: advisory ? "advisory" : "draft",
    is_current: true,
    base_agent_version_id: issue.workspace_agent_version,
    base_config_hash: "9f2c4a1b7d3e6f80a1b2c3d4e5f60718293a4b5c6d7e8f9012a3b4c5d6e7f8091",
    variant_config_hash: advisory
      ? null
      : `${(issue.fixes.length + 1).toString(16).padStart(2, "0")}${"5e8d7c6b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e9d8c7b6a5f4e3d2c1b0a9f8e7d".slice(2)}`,
    diff: diffOf(kind, payload),
    cost_usd: source === "ai" ? 0.0042 : null,
    created_at: iso(at),
  };
}

/** Evidence rows for a finished attempt. */
export function evidence(
  head: Ev,
  passes: boolean,
): { headline: EvaluatorEvidence; rows: EvaluatorEvidence[]; reasons: ValidationAttempt["reasons"] } {
  const row = (
    ev: Ev,
    set: EvaluatorEvidence["set"],
    n: number,
    c: number,
    t: number,
    extra: Partial<EvaluatorEvidence> = {},
  ): EvaluatorEvidence => ({
    evaluator_id: ev.id,
    evaluator_name: ev.display,
    evaluator_version: 2,
    set,
    n,
    control_passes: c,
    treatment_passes: t,
    control_rate: n ? c / n : null,
    treatment_rate: n ? t / n : null,
    delta_pp: n ? ((t - c) / n) * 100 : null,
    blocking: false,
    insufficient_data: false,
    version_mismatch: 0,
    ...extra,
  });
  const other = head.id === EVALUATORS.intent.id ? EVALUATORS.factual : EVALUATORS.intent;
  if (passes) {
    const headline = row(head, "affected", 8, 2, 6);
    return {
      headline,
      rows: [
        headline,
        row(head, "guard", 10, 10, 10),
        row(EVALUATORS.tools, "combined", 18, 15, 15),
        row(other, "combined", 18, 16, 17, { version_mismatch: 1 }),
        row(EVALUATORS.tools, "guard", 3, 3, 2, { insufficient_data: false }),
      ].slice(0, 4),
      reasons: [],
    };
  }
  const headline = row(head, "affected", 8, 2, 6);
  const tools = row(EVALUATORS.tools, "combined", 12, 11, 10, { blocking: false });
  const regress = row(other, "combined", 18, 17, 14, { blocking: true, delta_pp: -16.666666 });
  return {
    headline,
    rows: [headline, row(head, "guard", 10, 10, 10), regress, tools, row(EVALUATORS.transition, "combined", 4, 4, 3, { insufficient_data: true })],
    reasons: [
      { code: "regression", evaluator_id: other.id, set: "combined", delta_pp: -16.7, n: 18 },
      { code: "insufficient_data", evaluator_id: EVALUATORS.transition.id, set: "combined", n: 4 },
    ],
  };
}

export function finishedAttempt(
  issue: StoredIssue,
  head: Ev,
  attempt: number,
  revision: number,
  passes: boolean,
  startedAt: number,
  auto = false,
): ValidationAttempt {
  const ev = evidence(head, passes);
  return {
    attempt,
    fix_revision: revision,
    auto,
    mode: "persona",
    status: "completed",
    decision: passes ? "passed" : "failed",
    reasons: ev.reasons,
    thresholds: { min_improvement_pp: 10, max_regression_pp: 5, min_sample: 5 },
    base_agent_version_id: issue.workspace_agent_version,
    base_config_hash: "9f2c4a1b7d3e6f80a1b2c3d4e5f60718293a4b5c6d7e8f9012a3b4c5d6e7f8091",
    variant_config_hash: issue.fixes[revision - 1]?.variant_config_hash ?? "",
    affected_call_ids: issue.samples.slice(0, 8).map((s) => s.call_id),
    guard_call_ids: Array.from({ length: 10 }, (_, i) => callId(900 + i)),
    control_experiment_id: issueMockId("exp"),
    treatment_experiment_id: issueMockId("exp"),
    headline: ev.headline,
    evaluator_results: ev.rows,
    treatment_runs_total: 18,
    treatment_runs_failed: passes ? 0 : 1,
    estimated_cost_usd: 0.41,
    cost_usd: 0.38,
    started_at: iso(startedAt),
    finished_at: iso(startedAt + 6 * MIN),
  };
}

const REASONS: Record<string, string[]> = {
  price: [
    "The agent quoted $120 for whitening, which is not in the price list.",
    "Said a crown costs about $900; the price list has no crown price.",
    "Gave a price for implants that the knowledge base does not contain.",
    "Quoted $45 for a consultation; the listed price is $60.",
  ],
  date: ["Booked Tuesday without repeating the date back.", "Moved the appointment without confirming the new time."],
  billing: [
    "Transferred a balance question to the billing team instead of reading the balance.",
    "Sent the caller to billing for a question it could answer.",
  ],
  greeting: ["Repeated the full greeting after a two second pause."],
  insurance: ["Confused the caller's PPO plan with an HMO plan."],
  address: ["Moved on without reading the address back.", "Did not confirm the postcode before booking the visit."],
};

function samples(kind: keyof typeof REASONS, count: number, versionId: string, now: number, from: number, simulated = 0): IssueSample[] {
  const lines = REASONS[kind]!;
  return Array.from({ length: count }, (_, i) => ({
    call_id: callId(from + i),
    reason_excerpt: lines[i % lines.length]!,
    evaluator_result_ids: [issueMockId("evr")],
    agent_version_id: versionId,
    call_origin: i < simulated ? "simulation" : "live",
    base_call_id: i < simulated ? callId(500 + from + i) : null,
    failed_at: iso(now - (i + 1) * 5 * HOUR),
  }));
}

function base(
  s: IssueStore,
  agentId: string,
  agentType: "single_prompt" | "flow",
  ev: Ev,
  title: string,
  description: string,
  now: number,
  patch: Partial<StoredIssue> = {},
): StoredIssue {
  const version = s.published[agentId] ?? "agv_01MOCKISSUEVERSION000000001";
  const issue: StoredIssue = {
    issue_id: issueMockId("iss"),
    agent_id: agentId,
    agent_type: agentType,
    title,
    description,
    suspected_cause: null,
    evaluator_id: ev.id,
    evaluator_name: ev.name,
    evaluator_display_name: ev.display,
    evaluator_version: 2,
    flow_node_id: null,
    flow_node_label: null,
    status: "open",
    origin: "real",
    affected_call_count: 0,
    current_version_call_count: 0,
    calibration_warning: false,
    current_fix_kind: null,
    recurrence_of: null,
    first_seen_at: iso(now - 12 * DAY),
    last_seen_at: iso(now - 3 * HOUR),
    window_days: 14,
    allowed_fix_kinds: [],
    recommended_fix_kind: "prompt_edit",
    applied_agent_version_id: null,
    applied_at: null,
    post_apply: null,
    dismiss_reason: null,
    dismiss_note: null,
    duplicate_of: null,
    dismissed_at: null,
    workspace_agent_version: version,
    fixes: [],
    attempts: [],
    samples: [],
    ...patch,
  };
  issue.allowed_fix_kinds = allowedFor(issue);
  issue.recommended_fix_kind =
    issue.allowed_fix_kinds[0] === "prompt_edit" ? "prompt_edit" : issue.flow_node_id ? "node_prompt_edit" : "add_guardrail";
  s.issues.push(issue);
  return issue;
}

function seed(): IssueStore {
  const agents = agentStore().agents;
  const byName = (name: string, fallback: string) => agents.find((a) => a.name === name && !a.deleted_at)?.id ?? fallback;
  const pinned = (id: string) => agents.find((a) => a.id === id)?.pinned_version_id ?? "agv_01MOCKISSUEVERSION000000001";
  const desk = byName("Front desk agent", MOCK_AGENTS[0]!.id);
  const recall = byName("Recall reminders", MOCK_AGENTS[1]!.id);
  const s: IssueStore = {
    agents: { desk, billing: byName("Billing line", MOCK_AGENTS[0]!.id), triage: byName("After-hours triage", MOCK_AGENTS[0]!.id), recall },
    published: { [desk]: pinned(desk), [recall]: pinned(recall) },
    issues: [],
    detections: {},
    idem: {},
    requests: [],
    bodies: [],
  };
  const now = Date.now();
  const v = s.published[desk]!;

  // 1. Validated: revision 1 (AI prompt edit) failed, revision 2 (manual guardrail) passed.
  const prices = base(
    s,
    desk,
    "single_prompt",
    EVALUATORS.factual,
    "Agent quotes prices that are not in the price list",
    "When callers ask about treatments the price list does not cover, the agent names a price instead of offering to confirm it.",
    now,
    {
      status: "validated",
      affected_call_count: 8,
      current_version_call_count: 6,
      suspected_cause: "The prompt asks the agent to quote prices but never says what to do when a price is missing.",
      current_fix_kind: "add_guardrail",
    },
  );
  prices.samples = samples("price", 8, v, now, 1);
  const r1 = draftPayload("prompt_edit", prices);
  prices.fixes.push({ ...makeRevision(prices, "prompt_edit", r1.payload, r1.rationale, "ai", now - 2 * DAY), status: "failed", is_current: false });
  const r2 = draftPayload("add_guardrail", prices);
  prices.fixes.push({
    ...makeRevision(
      prices,
      "add_guardrail",
      r2.payload,
      "Kept the prompt as it is and added one rule, so the greeting and booking steps stay unchanged.",
      "manual",
      now - DAY,
    ),
    status: "passed",
  });
  prices.attempts.push(finishedAttempt(prices, EVALUATORS.factual, 1, 1, false, now - 2 * DAY + HOUR));
  prices.attempts.push(finishedAttempt(prices, EVALUATORS.factual, 2, 2, true, now - DAY + HOUR));

  // 2. Open, check disagrees with human labels.
  const dates = base(
    s,
    desk,
    "single_prompt",
    EVALUATORS.intent,
    "Agent books appointments without confirming the date",
    "The agent books or moves an appointment without reading the date and time back to the caller.",
    now,
    { affected_call_count: 5, current_version_call_count: 5, calibration_warning: true, last_seen_at: iso(now - 9 * HOUR) },
  );
  dates.samples = samples("date", 5, v, now, 20);

  // 3. Applied with post-apply figures.
  const billing = base(
    s,
    desk,
    "single_prompt",
    EVALUATORS.tools,
    "Agent transfers billing questions instead of answering",
    "Callers asking about their balance are transferred to the billing team, although the balance tool can answer.",
    now,
    {
      status: "applied",
      affected_call_count: 11,
      current_version_call_count: 0,
      first_seen_at: iso(now - 13 * DAY),
      last_seen_at: iso(now - 6 * DAY),
      applied_agent_version_id: "agv_01MOCKISSUEAPPLIED000000001",
      applied_at: iso(now - 5 * DAY),
      current_fix_kind: "tool_description_edit",
      post_apply: {
        ready: true,
        before: { agent_version_id: v, n: 31, passes: 19, rate: 19 / 31 },
        after: { agent_version_id: "agv_01MOCKISSUEAPPLIED000000001", n: 12, passes: 11, rate: 11 / 12 },
        delta_pp: (11 / 12 - 19 / 31) * 100,
      },
    },
  );
  billing.samples = samples("billing", 11, v, now - 5 * DAY, 40);
  const r3 = draftPayload("tool_description_edit", billing);
  billing.fixes.push({ ...makeRevision(billing, "tool_description_edit", r3.payload, r3.rationale, "ai", now - 6 * DAY), status: "applied" });
  billing.attempts.push(finishedAttempt(billing, EVALUATORS.tools, 1, 1, true, now - 6 * DAY + HOUR));

  // 4. Recurrence of 3 on the new version.
  base(
    s,
    desk,
    "single_prompt",
    EVALUATORS.tools,
    "Agent still transfers some balance questions",
    "On the new version the agent answers most balance questions but still transfers callers who ask about a payment plan.",
    now,
    { affected_call_count: 3, current_version_call_count: 3, recurrence_of: billing.issue_id, first_seen_at: iso(now - 2 * DAY) },
  ).samples = samples("billing", 3, "agv_01MOCKISSUEAPPLIED000000001", now, 60);

  // 5. Dismissed, last seen 20 days ago (only in the 30 and 90 day windows).
  base(
    s,
    desk,
    "single_prompt",
    EVALUATORS.intent,
    "Agent repeats the greeting after a pause",
    "After a short silence the agent starts the greeting again.",
    now,
    {
      status: "dismissed",
      affected_call_count: 4,
      current_version_call_count: 0,
      first_seen_at: iso(now - 26 * DAY),
      last_seen_at: iso(now - 20 * DAY),
      dismiss_reason: "evaluator_wrong",
      dismiss_note: "The check counts the silence check-in as a repeated greeting.",
      dismissed_at: iso(now - 18 * DAY),
    },
  ).samples = samples("greeting", 4, v, now - 20 * DAY, 70);

  // 6. Mostly simulated (hidden with source "Real calls").
  base(
    s,
    desk,
    "single_prompt",
    EVALUATORS.factual,
    "Agent misreads the caller's insurance plan",
    "In persona simulations the agent mixes up PPO and HMO plans.",
    now,
    {
      origin: "simulated",
      affected_call_count: 6,
      current_version_call_count: 6,
      last_seen_at: iso(now - 30 * MIN),
    },
  ).samples = samples("insurance", 6, v, now, 80, 5);

  // 7. Flow node issue with a drafted node fix.
  const address = base(
    s,
    recall,
    "flow",
    EVALUATORS.transition,
    "Agent skips the confirm step in Collect address",
    "The flow leaves Collect address as soon as it hears a postcode, before the caller confirms the address.",
    now,
    {
      flow_node_id: "n_collect01",
      flow_node_label: "Collect address",
      affected_call_count: 7,
      current_version_call_count: 4,
      origin: "mixed",
      current_fix_kind: "node_prompt_edit",
    },
  );
  address.samples = samples("address", 7, s.published[recall] ?? v, now, 100, 2);
  const r7 = draftPayload("node_prompt_edit", address);
  address.fixes.push(makeRevision(address, "node_prompt_edit", r7.payload, r7.rationale, "ai", now - 4 * HOUR));

  return s;
}

export { DAY, HOUR, MIN, iso };
