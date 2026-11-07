/**
 * Mock API for spec 009 (issues and auto-fix), shaped by specs/009-issues-autofix/contracts.
 * Seeded data lives in ./store.ts.
 *
 * Behaviour for manual testing:
 * - Detect, AI drafting, validate and draft-and-validate need an Idempotency-Key and answer 402
 *   when the balance is at or below zero. A second detect while one runs answers 409.
 * - Detection finishes about 2.5 s after it starts; an agent without issues reports none found.
 * - A validation finishes about 5 s after it starts. Prompt edits fail on a regression of another
 *   check; every other kind passes.
 * - Apply answers 409 with the first blocker; dismiss checks the reason rules.
 */
import { http } from "msw";
import type {
  ApplyBlocker,
  ApplyResult,
  DetectedIssue,
  Detection,
  DismissReason,
  FixKind,
  FixPayload,
  IssueSummary,
  ValidationAttempt,
  ValidationEstimate,
} from "../../api/issues";
import { env } from "../../lib/env";
import { balanceOf, db } from "../db";
import {
  DAY,
  EVALUATORS,
  draftPayload,
  finishedAttempt,
  iso,
  issueMockId,
  issuesMock,
  makeRevision,
  type StoredDetection,
  type StoredIssue,
} from "./store";
import { invalid, json, problem, url } from "../http";

const notFound = () => problem(404, "not_found", "Not found", "No issue with that ID.");
const VALIDATION_MS = 5_000;
const DETECTION_MS = 2_500;

function log(request: Request) {
  const u = new URL(request.url);
  issuesMock().requests.push(`${request.method} ${u.pathname.replace(env.apiBaseUrl.replace(/^https?:\/\/[^/]+/, ""), "")}${u.search}`);
}

function workspaceId(request: Request): string | null {
  const token = request.headers.get("authorization")?.replace(/^Bearer\s+/i, "") ?? "";
  const id = db().sessions[token];
  return db().users.find((u) => u.id === id)?.workspace_id ?? null;
}

function paidGate(request: Request) {
  if (!request.headers.get("idempotency-key")) return problem(400, "idempotency_key_required", "Idempotency-Key header required");
  const ws = workspaceId(request);
  if (ws && balanceOf(db(), ws) <= 0n)
    return problem(402, "insufficient_credit", "Balance at or below zero", "Your balance is at or below zero. Add funds to find and fix issues.");
  return null;
}

function remembered<T>(request: Request, make: () => T): T {
  const key = `${new URL(request.url).pathname} ${request.headers.get("idempotency-key")}`;
  const s = issuesMock();
  if (!(key in s.idem)) s.idem[key] = make();
  return s.idem[key] as T;
}

/** Finish detections and validations whose time has come. */
function settle() {
  const s = issuesMock();
  const now = Date.now();
  for (const d of Object.values(s.detections)) {
    if (d.status !== "running" || (d._finishAt ?? 0) > now) continue;
    const mine = s.issues.filter((i) => i.agent_id === d.agent_id && i.status !== "dismissed");
    Object.assign(d, {
      status: "completed",
      calls_scanned: mine.length ? 142 : 37,
      failures_scanned: mine.reduce((n, i) => n + i.affected_call_count, 0) + (mine.length ? 4 : 2),
      issues_created: 0,
      issues_updated: mine.length,
      cost_usd: 0.0123,
      finished_at: iso(d._finishAt ?? now),
    });
    delete d._finishAt;
  }
  for (const issue of s.issues) {
    for (const a of issue.attempts) {
      if (a.status !== "running" || (a._finishAt ?? 0) > now) continue;
      const done = finishedAttempt(issue, evaluatorOf(issue), a.attempt, a.fix_revision, Boolean(a._passes), Date.parse(a.started_at), a.auto);
      Object.assign(a, { ...done, control_experiment_id: a.control_experiment_id, treatment_experiment_id: a.treatment_experiment_id });
      delete a._finishAt;
      const fix = issue.fixes[a.fix_revision - 1];
      if (fix) fix.status = a.decision === "passed" ? "passed" : (a.decision ?? "failed");
      if (issue.status === "validating") issue.status = a.decision === "passed" ? "validated" : "open";
    }
  }
}

function evaluatorOf(issue: StoredIssue) {
  return Object.values(EVALUATORS).find((e) => e.id === issue.evaluator_id) ?? EVALUATORS.factual;
}

const currentFix = (i: StoredIssue) => i.fixes.find((f) => f.is_current) ?? null;

function blockersOf(i: StoredIssue): ApplyBlocker[] {
  const fix = currentFix(i);
  const out: ApplyBlocker[] = [];
  if (i.status !== "validated") out.push("wrong_status");
  if (fix?.status === "advisory") out.push("advisory_fix");
  const latest = i.attempts.filter((a) => a.fix_revision === fix?.revision).at(-1);
  if (!fix || latest?.decision !== "passed") out.push("no_passing_validation");
  else if (latest.base_agent_version_id !== (issuesMock().published[i.agent_id] ?? latest.base_agent_version_id)) out.push("base_version_changed");
  return out;
}

function summary(i: StoredIssue): IssueSummary {
  return {
    issue_id: i.issue_id,
    agent_id: i.agent_id,
    agent_type: i.agent_type,
    title: i.title,
    evaluator_id: i.evaluator_id,
    evaluator_name: i.evaluator_name,
    evaluator_display_name: i.evaluator_display_name,
    flow_node_id: i.flow_node_id,
    flow_node_label: i.flow_node_label,
    status: i.status,
    origin: i.origin,
    affected_call_count: i.affected_call_count,
    current_version_call_count: i.current_version_call_count,
    calibration_warning: i.calibration_warning,
    current_fix_kind: currentFix(i)?.kind ?? null,
    recurrence_of: i.recurrence_of,
    first_seen_at: i.first_seen_at,
    last_seen_at: i.last_seen_at,
  };
}

function strip<T extends object>(o: T): T {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(o)) if (!k.startsWith("_")) out[k] = v;
  return out as T;
}

function detail(i: StoredIssue): DetectedIssue {
  const { fixes: _f, attempts, samples, workspace_agent_version: _v, ...rest } = i;
  const blockers = i.status === "applied" || i.status === "dismissed" ? [] : blockersOf(i);
  const latest = attempts.at(-1);
  return {
    ...rest,
    ...summary(i),
    current_fix: currentFix(i),
    latest_validation: latest ? strip(latest) : null,
    can_apply: i.status === "validated" && blockers.length === 0,
    apply_blockers: blockers,
    sample_preview: samples.slice(0, 5),
  };
}

function find(id: string) {
  return issuesMock().issues.find((i) => i.issue_id === id);
}

function addRevision(issue: StoredIssue, kind: FixKind, payload: FixPayload, rationale: string, source: "ai" | "manual", guidance: string | null) {
  for (const f of issue.fixes) {
    if (!f.is_current) continue;
    f.is_current = false;
    if (!["failed", "inconclusive", "applied"].includes(f.status)) f.status = "superseded";
  }
  const rev = makeRevision(issue, kind, payload, rationale, source, Date.now(), guidance);
  issue.fixes.push(rev);
  if (issue.status === "validated") issue.status = "open";
  return rev;
}

function startAttempt(issue: StoredIssue, body: Record<string, unknown>, auto: boolean): ValidationAttempt {
  const fix = currentFix(issue)!;
  fix.status = "validating";
  issue.status = "validating";
  const attempt = {
    attempt: issue.attempts.length + 1,
    fix_revision: fix.revision,
    auto,
    mode: (body.mode as "persona" | "replay") ?? "persona",
    status: "running" as const,
    decision: null,
    reasons: [],
    thresholds: {
      min_improvement_pp: Number(body.min_improvement_pp ?? 10),
      max_regression_pp: Number(body.max_regression_pp ?? 5),
      min_sample: Number(body.min_sample ?? 5),
    },
    base_agent_version_id: issue.workspace_agent_version,
    base_config_hash: fix.base_config_hash ?? "",
    variant_config_hash: fix.variant_config_hash ?? "",
    affected_call_ids: issue.samples.slice(0, 20).map((s) => s.call_id),
    guard_call_ids: [],
    control_experiment_id: issueMockId("exp"),
    treatment_experiment_id: issueMockId("exp"),
    headline: null,
    evaluator_results: [],
    estimated_cost_usd: 0.41,
    cost_usd: null,
    started_at: iso(Date.now()),
    finished_at: null,
    _finishAt: Date.now() + VALIDATION_MS,
    _passes: fix.kind !== "prompt_edit",
  };
  issue.attempts.push(attempt);
  return strip(attempt);
}

const ESTIMATE = (issue: StoredIssue): ValidationEstimate => {
  const affected = Math.min(20, issue.samples.length);
  return {
    affected_calls: affected,
    guard_calls: 10,
    simulations: 2 * (affected + 10),
    estimated_cost_usd: Math.round((affected + 10) * 2 * 0.0137 * 10_000) / 10_000,
    tools_missing_mock: [],
    warnings: issue.origin !== "real" ? ["Simulated samples are replaced by the calls they started from."] : [],
  };
};

function runningConflict(issue: StoredIssue) {
  if (issue.status === "applied" || issue.status === "dismissed")
    return problem(409, "wrong_status", "Issue closed", "This issue is closed. Reopen work on a new issue instead.");
  if (issue.status === "validating")
    return problem(409, "validation_running", "Validation running", "Wait for the validation to finish or cancel it.");
  return null;
}

export const issueHandlers = [
  http.post(url("/issues/detect"), async ({ request }) => {
    log(request);
    const gate = paidGate(request);
    if (gate) return gate;
    const body = (await request.json()) as { agent_id?: string; window_days?: number; include_simulated?: boolean };
    issuesMock().bodies.push({ path: "/issues/detect", body });
    if (!body.agent_id) return invalid("/agent_id", "Choose an agent.", "required");
    settle();
    const s = issuesMock();
    const existing = s.detections[body.agent_id];
    if (existing?.status === "running") {
      const replay = s.idem[`/issues/detect ${request.headers.get("idempotency-key")}`];
      if (replay) return json(replay, 202);
      return problem(409, "detection_running", "Detection running", "A detection is already running for this agent. Wait for it to finish.");
    }
    const det = remembered(request, () => {
      const now = Date.now();
      const windowDays = body.window_days ?? 14;
      const d: StoredDetection = {
        agent_id: body.agent_id!,
        status: "running",
        window_days: windowDays,
        include_simulated: Boolean(body.include_simulated),
        window_start: iso(now - windowDays * DAY),
        window_end: iso(now),
        calls_scanned: 0,
        failures_scanned: 0,
        issues_created: 0,
        issues_updated: 0,
        cost_usd: null,
        error_message: null,
        started_at: iso(now),
        finished_at: null,
        _finishAt: now + DETECTION_MS,
      };
      s.detections[body.agent_id!] = d;
      return d;
    });
    return json(strip(det), 202);
  }),

  http.get(url("/issues/detection"), ({ request }) => {
    log(request);
    settle();
    const agent = new URL(request.url).searchParams.get("agent_id") ?? "";
    const d = issuesMock().detections[agent];
    return json<Detection | null>(d ? strip(d) : null);
  }),

  http.get(url("/issues"), ({ request }) => {
    log(request);
    settle();
    const q = new URL(request.url).searchParams;
    const agent = q.get("agent_id");
    const status = q.get("status") ?? "all";
    const scope = q.get("scope") ?? "real";
    const windowDays = Number(q.get("window_days") ?? 0);
    const appliedVersion = q.get("applied_agent_version_id");
    const since = windowDays ? Date.now() - windowDays * DAY : 0;
    const rows = issuesMock()
      .issues.filter((i) => !agent || i.agent_id === agent)
      .filter((i) => (status === "all" ? i.status !== "dismissed" : i.status === status))
      .filter((i) => scope === "real_and_simulated" || i.origin !== "simulated")
      .filter((i) => Date.parse(i.last_seen_at) >= since)
      .filter((i) => !appliedVersion || i.applied_agent_version_id === appliedVersion)
      .sort((a, b) => b.affected_call_count - a.affected_call_count || b.last_seen_at.localeCompare(a.last_seen_at));
    const page = Math.max(1, Number(q.get("page") ?? 1));
    const size = Math.min(100, Math.max(1, Number(q.get("page_size") ?? 20)));
    return json({
      items: rows.slice((page - 1) * size, page * size).map(summary),
      total: rows.length,
      page,
      page_size: size,
      total_pages: Math.max(1, Math.ceil(rows.length / size)),
    });
  }),

  http.get(url("/issues/:id"), ({ request, params }) => {
    log(request);
    settle();
    const issue = find(String(params.id));
    return issue ? json(detail(issue)) : notFound();
  }),

  http.get(url("/issues/:id/samples"), ({ request, params }) => {
    log(request);
    const issue = find(String(params.id));
    if (!issue) return notFound();
    const q = new URL(request.url).searchParams;
    const page = Math.max(1, Number(q.get("page") ?? 1));
    const size = Math.min(100, Math.max(1, Number(q.get("page_size") ?? 20)));
    return json({
      items: issue.samples.slice((page - 1) * size, page * size),
      total: issue.samples.length,
      page,
      page_size: size,
      total_pages: Math.max(1, Math.ceil(issue.samples.length / size)),
    });
  }),

  http.get(url("/issues/:id/fixes"), ({ request, params }) => {
    log(request);
    settle();
    const issue = find(String(params.id));
    return issue ? json({ items: [...issue.fixes].reverse() }) : notFound();
  }),

  http.post(url("/issues/:id/fixes"), async ({ request, params }) => {
    log(request);
    const issue = find(String(params.id));
    if (!issue) return notFound();
    const body = (await request.json()) as { mode: "ai" | "manual"; kind?: FixKind; guidance?: string | null; payload?: FixPayload };
    issuesMock().bodies.push({ path: `/issues/${issue.issue_id}/fixes`, body });
    settle();
    const conflict = runningConflict(issue);
    if (conflict) return conflict;
    if (body.kind && !issue.allowed_fix_kinds.includes(body.kind))
      return invalid("/kind", "This kind of fix does not suit this issue. Choose one from the list.");
    if (body.mode === "manual") {
      if (!body.kind || !body.payload) return invalid("/payload", "Send the kind and the full fix.", "required");
      return json(addRevision(issue, body.kind, body.payload, "Edited by hand.", "manual", null), 201);
    }
    const gate = paidGate(request);
    if (gate) return gate;
    const rev = remembered(request, () => {
      const kind = body.kind ?? issue.recommended_fix_kind;
      const draft = draftPayload(kind, issue, body.guidance);
      return addRevision(issue, kind, draft.payload, draft.rationale, "ai", body.guidance ?? null);
    });
    return json(rev, 201);
  }),

  http.post(url("/issues/:id/validate"), async ({ request, params }) => {
    log(request);
    const issue = find(String(params.id));
    if (!issue) return notFound();
    const gate = paidGate(request);
    if (gate) return gate;
    const body = ((await request.json().catch(() => ({}))) ?? {}) as Record<string, unknown>;
    issuesMock().bodies.push({ path: `/issues/${issue.issue_id}/validate`, body });
    settle();
    if (body.dry_run) return json(ESTIMATE(issue));
    const conflict = runningConflict(issue);
    if (conflict) return conflict;
    const fix = currentFix(issue);
    if (!fix) return problem(409, "no_current_fix", "No fix to validate", "Draft a fix first, then validate it.");
    if (fix.status === "advisory")
      return problem(409, "advisory_fix", "Fix is advice only", "Advice-only fixes cannot be validated. Draft another kind of fix.");
    return json(
      remembered(request, () => startAttempt(issue, body, false)),
      202,
    );
  }),

  http.post(url("/issues/:id/draft-and-validate"), async ({ request, params }) => {
    log(request);
    const issue = find(String(params.id));
    if (!issue) return notFound();
    const gate = paidGate(request);
    if (gate) return gate;
    const body = ((await request.json().catch(() => ({}))) ?? {}) as Record<string, unknown> & { kind?: FixKind; guidance?: string | null };
    issuesMock().bodies.push({ path: `/issues/${issue.issue_id}/draft-and-validate`, body });
    settle();
    const conflict = runningConflict(issue);
    if (conflict) return conflict;
    const result = remembered(request, () => {
      const kind = body.kind ?? issue.recommended_fix_kind;
      const draft = draftPayload(kind, issue, body.guidance);
      const fix = addRevision(issue, kind, draft.payload, draft.rationale, "ai", body.guidance ?? null);
      return { fix, validation: startAttempt(issue, body, true) };
    });
    return json(result, 202);
  }),

  http.get(url("/issues/:id/validations"), ({ request, params }) => {
    log(request);
    settle();
    const issue = find(String(params.id));
    return issue ? json({ items: [...issue.attempts].reverse().map(strip) }) : notFound();
  }),

  http.post(url("/issues/:id/validation/cancel"), ({ request, params }) => {
    log(request);
    settle();
    const issue = find(String(params.id));
    if (!issue) return notFound();
    const running = issue.attempts.find((a) => a.status === "running");
    if (!running) return problem(409, "no_validation_running", "Nothing to cancel", "No validation is running for this issue.");
    Object.assign(running, { status: "cancelled", finished_at: iso(Date.now()) });
    delete running._finishAt;
    const fix = issue.fixes[running.fix_revision - 1];
    if (fix) fix.status = "draft";
    issue.status = "open";
    return json(detail(issue));
  }),

  http.post(url("/issues/:id/apply"), async ({ request, params }) => {
    log(request);
    settle();
    const issue = find(String(params.id));
    if (!issue) return notFound();
    const body = ((await request.json().catch(() => ({}))) ?? {}) as { publish?: boolean; release_notes_extra?: string | null };
    issuesMock().bodies.push({ path: `/issues/${issue.issue_id}/apply`, body });
    const blockers = issue.status === "applied" || issue.status === "dismissed" ? (["wrong_status"] as ApplyBlocker[]) : blockersOf(issue);
    const first = blockers.find((b) => b !== "wrong_status") ?? blockers[0];
    if (first) {
      const text: Record<ApplyBlocker, string> = {
        no_passing_validation: "This fix has no passing validation",
        base_version_changed: "The published version changed since validation. Validate again against the current version.",
        draft_changed: "The draft changed since validation. Validate again against the current version.",
        wrong_status: "Only a validated issue can be applied.",
        advisory_fix: "Advice-only fixes cannot be applied.",
      };
      return problem(409, first, "Fix not applied", text[first]);
    }
    const version = issueMockId("agv");
    const fix = currentFix(issue)!;
    fix.status = "applied";
    Object.assign(issue, {
      status: "applied",
      applied_agent_version_id: version,
      applied_at: iso(Date.now()),
      post_apply: {
        ready: false,
        before: { agent_version_id: issue.workspace_agent_version, n: 24, passes: 15, rate: 15 / 24 },
        after: { agent_version_id: version, n: 0, passes: 0, rate: null },
        delta_pp: null,
      },
    });
    const publish = body.publish !== false;
    if (publish) issuesMock().published[issue.agent_id] = version;
    const notes = `Fix for ${issue.issue_id}: ${issue.title}`;
    return json<ApplyResult>({
      issue: detail(issue),
      agent_version_id: version,
      published: publish,
      release_notes: body.release_notes_extra ? `${notes}\n\n${body.release_notes_extra}` : notes,
      tool_copies:
        fix.kind === "tool_description_edit" ? [{ original_tool_id: "tool_01MOCKTOOLPRICES00000000001", copy_tool_id: issueMockId("tool") }] : [],
      draft_updated: true,
    });
  }),

  http.post(url("/issues/:id/dismiss"), async ({ request, params }) => {
    log(request);
    settle();
    const issue = find(String(params.id));
    if (!issue) return notFound();
    const body = (await request.json()) as { reason?: DismissReason; note?: string | null; duplicate_of?: string };
    issuesMock().bodies.push({ path: `/issues/${issue.issue_id}/dismiss`, body });
    if (issue.status === "applied" || issue.status === "dismissed")
      return problem(409, "wrong_status", "Issue closed", "This issue is already closed.");
    if (!body.reason) return invalid("/reason", "Choose a reason.", "required");
    if (body.reason === "other" && !body.note?.trim()) return invalid("/note", "Say why you dismiss this issue.", "required");
    if (body.reason === "duplicate") {
      const target = body.duplicate_of ? find(body.duplicate_of) : undefined;
      if (!target || target.agent_id !== issue.agent_id || target.issue_id === issue.issue_id)
        return invalid("/duplicate_of", "Choose another issue of the same agent.", "required");
    }
    const running = issue.attempts.find((a) => a.status === "running");
    if (running) {
      Object.assign(running, { status: "cancelled", finished_at: iso(Date.now()) });
      delete running._finishAt;
    }
    Object.assign(issue, {
      status: "dismissed",
      dismiss_reason: body.reason,
      dismiss_note: body.note?.trim() || null,
      duplicate_of: body.reason === "duplicate" ? body.duplicate_of : null,
      dismissed_at: iso(Date.now()),
    });
    return json(detail(issue));
  }),
];
