/**
 * Mock API for spec 006 (calls read side, recordings, dashboard), shaped by
 * specs/006-calls-analytics/contracts. The store is empty until `seedMockCalls()` runs, so the
 * dashboard keeps its setup sequence for a new workspace; tests seed what they need.
 * `requests` records every call-list query string so tests can check what reached the server.
 * Seeding also books the 011 callbacks on these calls (mocks/callbacks/handlers.ts) and records
 * the 012 caller languages (mocks/callerLanguage/handlers.ts).
 */
import { http, HttpResponse } from "msw";
import type { CallDetail, CallListItem, DashboardStats, TranscriptItem, TurnLatency } from "../../api/calls";
import { seedMockCallbacks } from "../callbacks/handlers";
import { seedMockCallerLanguages } from "../callerLanguage/handlers";
import { json, page, problemDetail, url } from "../http";

export const MOCK_AGENTS = [
  { id: "agt_01HMCKAGENT0RDERDESK000001", name: "Order desk" },
  { id: "agt_01HMCKAGENTSCHEDVR00000002", name: "Clinic scheduler" },
];

interface Store {
  calls: CallListItem[];
  requests: string[];
}
let store: Store = { calls: [], requests: [] };

export const mockCalls = () => store;

/** 007 fills the list's quality cell (evaluation status, counts, the viewer's label). */
type QualityOf = (call: CallListItem, request: Request) => CallListItem["quality"];
let qualityOf: QualityOf | null = null;
export function setQualitySummarizer(fn: QualityOf) {
  qualityOf = fn;
}
const withQuality = (c: CallListItem, request: Request): CallListItem => (qualityOf ? { ...c, quality: qualityOf(c, request) } : c);

export function resetMockCalls() {
  store = { calls: [], requests: [] };
  liveScript = [];
}

/**
 * Calls on air for the mock API. Each scripted call rings, connects and ends on a clock relative
 * to when it was seeded, and its transcript grows a line every few seconds while it is live, so
 * the live card, badge, pinned rows and drawer can be watched changing. `?live=3` on any mock
 * page (or `seedMockLiveCalls(3)` from the console) turns them on; `?live=0` or nothing leaves the
 * workspace quiet.
 */
interface LiveScript {
  id: string;
  connectAt: number;
  endAt: number;
  /** Lines already spoken when the script starts (calls seeded mid-conversation). */
  heard: number;
  from: number;
}
let liveScript: LiveScript[] = [];

const LIVE_LINES: { role: "user" | "agent"; text: string }[] = [
  { role: "agent", text: "Thanks for calling, this is the order desk. How can I help?" },
  { role: "user", text: "Hi, I ordered a standing desk last week and it still says processing." },
  { role: "agent", text: "Sorry about the wait. Can I have the order number?" },
  { role: "user", text: "Sure, it's A as in apple, one two four nine." },
  { role: "agent", text: "Thanks. I can see order A1249, it left our warehouse this morning." },
  { role: "user", text: "Oh good. When will it arrive?" },
  { role: "agent", text: "It is due on Thursday between nine and one. Shall I text you the tracking link?" },
  { role: "user", text: "Yes please, to this number." },
  { role: "agent", text: "Done, the link is on its way. Anything else I can help with?" },
  { role: "user", text: "No, that's all, thanks." },
];
const LINE_EVERY_MS = 4_000;

export function seedMockLiveCalls(count = 3, now = Date.now()) {
  const plans = [
    {
      channel: "sip_inbound",
      direction: "inbound",
      from: "+14155550142",
      to: "+14155550100",
      agent: 0,
      origin: "live",
      connect: -134_000,
      end: 20 * 60_000,
      heard: 4,
    },
    { channel: "web", direction: "inbound", from: null, to: null, agent: 1, origin: "test", connect: -38_000, end: 15 * 60_000, heard: 2 },
    {
      channel: "sip_outbound",
      direction: "outbound",
      from: "+14155550100",
      to: "+14155550199",
      agent: 1,
      origin: "live",
      connect: 12_000,
      end: 25 * 60_000,
      heard: 0,
    },
    {
      channel: "whatsapp",
      direction: "inbound",
      from: "+447700900321",
      to: null,
      agent: 0,
      origin: "live",
      connect: -61_000,
      end: 18 * 60_000,
      heard: 3,
    },
  ] as const;
  store.calls = store.calls.filter((c) => !liveScript.some((l) => l.id === c.call_id));
  liveScript = [];
  const added: CallListItem[] = plans.slice(0, Math.max(0, count)).map((p, i) => {
    const id = `call_01MOCKLIVE${pad(i)}AAAAAAAAAAAAA`;
    liveScript.push({ id, connectAt: now + p.connect, endAt: now + p.end, heard: p.heard, from: Math.max(now, now + p.connect) });
    const agent = MOCK_AGENTS[p.agent]!;
    return {
      call_id: id,
      started_at: new Date(now + Math.min(p.connect, 0) - 6_000 - i * 1_000).toISOString(),
      agent: { ...agent, deleted: false },
      from_number: p.from,
      to_number: p.to,
      channel: p.channel,
      origin: p.origin,
      disconnect_reason: null,
      duration_s: 0,
      status: "ringing",
      connected_at: null,
      cost_usd: null,
      latency_avg_ms: null,
      has_recording: false,
      summary: null,
      sentiment: null,
      analysis_values: null,
      quality: { eval_status: "not_evaluated", pass_count: 0, fail_count: 0, label: null },
    } as CallListItem;
  });
  store.calls = [...added, ...store.calls];
  tickLive(now);
}

const directionOf = (c: CallListItem) => (c.channel === "sip_outbound" ? "outbound" : "inbound");

/** Moves scripted calls along their clock: ringing, then on air, then completed. */
function tickLive(now = Date.now()) {
  for (const l of liveScript) {
    const c = store.calls.find((x) => x.call_id === l.id);
    if (!c) continue;
    if (now < l.connectAt) {
      c.status = "ringing";
      c.connected_at = null;
    } else if (now < l.endAt) {
      c.status = "in_progress";
      c.connected_at = new Date(l.connectAt).toISOString();
    } else if (c.status !== "completed") {
      c.status = "completed";
      c.connected_at = new Date(l.connectAt).toISOString();
      c.duration_s = Math.round((l.endAt - l.connectAt) / 1000);
      c.disconnect_reason = "user_hangup";
      c.cost_usd = 0.1;
      c.latency_avg_ms = 860;
    }
  }
}

function liveLines(id: string, now = Date.now()): typeof LIVE_LINES {
  const l = liveScript.find((x) => x.id === id);
  if (!l || now < l.connectAt) return [];
  const heard = l.heard + Math.floor((Math.min(now, l.endAt) - l.from) / LINE_EVERY_MS) + (l.heard ? 0 : 1);
  return LIVE_LINES.slice(0, Math.min(LIVE_LINES.length, heard));
}

function liveTranscript(id: string): TranscriptItem[] {
  return liveLines(id).map((line, i) => ({
    id: `ti_${pad(i)}`,
    type: "message",
    role: line.role,
    text: line.text,
    interrupted: false,
    stt_confidence: line.role === "user" ? 0.94 : null,
    offset_ms: i * LINE_EVERY_MS + 400,
    turn_index: line.role === "agent" ? Math.floor(i / 2) : null,
  }));
}

const pad = (n: number) => String(n).padStart(4, "0");
export const mockCallId = (n: number) => `call_01MOCKCALL${pad(n)}AAAAAAAAAAAA`;

/** `count` calls, newest first, alternating agents and channels. */
export function seedMockCalls(count = 45) {
  const channels = ["web", "sip_inbound", "whatsapp"] as const;
  const statuses = ["completed", "completed", "failed", "processing"] as const;
  const now = Date.UTC(2026, 9, 16, 12);
  store.calls = Array.from({ length: count }, (_, i) => {
    const agent = MOCK_AGENTS[i % 2]!;
    const status = statuses[i % 4]!;
    return {
      call_id: mockCallId(i),
      started_at: new Date(now - i * 3_600_000).toISOString(),
      agent: { ...agent, deleted: false },
      from_number: i % 3 === 0 ? null : i === 1 ? "+15551234567" : `+1415555${pad(i)}`,
      to_number: i % 3 === 0 ? null : "+14155550100",
      channel: channels[i % 3]!,
      origin: "live",
      disconnect_reason: status === "failed" ? "error" : "user_hangup",
      diagnostic: status === "failed" ? "unsupported_vendor:stt/sarvam" : null,
      duration_s: status === "failed" ? 0 : 60 + i,
      status,
      connected_at: status === "failed" ? null : new Date(now - i * 3_600_000 + 3_000).toISOString(),
      cost_usd: status === "failed" ? null : 0.1 + i / 1000,
      latency_avg_ms: status === "failed" ? null : 800 + i,
      has_recording: i !== 2,
      summary: status === "completed" ? "Caller asked about an order." : null,
      sentiment: status === "completed" ? "positive" : null,
      analysis_values: status === "completed" ? { resolved: true } : null,
      quality: { eval_status: "not_evaluated", pass_count: 0, fail_count: 0, label: null },
    } as CallListItem;
  });
  // 011: callbacks booked on these calls (mock call 1 has a scheduled one).
  seedMockCallbacks(store.calls);
  // 012: languages of these calls (mock call 1 switched to Hindi and saved it).
  seedMockCallerLanguages(store.calls);
}

function matches(c: CallListItem, q: URLSearchParams): boolean {
  const labels = q.get("label")?.split(",").filter(Boolean) ?? [];
  if (labels.length && !labels.includes(c.quality.label ?? "unannotated")) return false;
  const evals = q.get("eval_status")?.split(",").filter(Boolean) ?? [];
  if (evals.length && !evals.includes(c.quality.eval_status)) return false;
  const list = (k: string) => q.get(k)?.split(",").filter(Boolean) ?? [];
  const origins = list("origin").length ? list("origin") : ["live", "test"];
  if (!origins.includes(c.origin)) return false;
  for (const [key, value] of [
    ["status", c.status],
    ["channel", c.channel],
    ["agent_id", c.agent.id],
    ["sentiment", c.sentiment ?? "unknown"],
  ] as const) {
    const wanted = list(key);
    if (wanted.length && !wanted.includes(value)) return false;
  }
  const from = (q.get("from_number") ?? "").replace(/\D/g, "");
  if (from && !(c.from_number ?? "").replace(/\D/g, "").startsWith(from)) return false;
  const id = q.get("call_id");
  if (id && !c.call_id.startsWith(id)) return false;
  return true;
}

function detail(c: CallListItem): CallDetail {
  return {
    ...c,
    agent_version_id: "agv_01MOCKVERSION00000000000001",
    agent_version_label: "v3",
    ended_at: c.status === "in_progress" || c.status === "ringing" ? null : c.started_at,
    latency: { avg_ms: c.latency_avg_ms ?? null, p50_ms: 900, p95_ms: 1400, turns_measured: 3 },
    cost: c.cost_usd
      ? {
          header: { duration_s: 271, billed_minutes: 4.516667, avg_rate_per_min_usd: 0.105609, total_usd: 0.477 },
          lines: [
            { component: "stt", provider: "deepgram", model: null, rate_per_min_usd: 0.0085, billed_minutes: 4.516667, cost_usd: 0.039 },
            { component: "llm", provider: "azure_openai", model: "gpt-5-mini", rate_per_min_usd: 0.0015, billed_minutes: 5.1174, cost_usd: 0.008 },
            {
              component: "tts",
              provider: "elevenlabs",
              model: "eleven_flash_v2_5",
              rate_per_min_usd: 0.045,
              billed_minutes: 4.516667,
              cost_usd: 0.204,
            },
            { component: "platform", provider: "callwright", model: null, rate_per_min_usd: 0.05, billed_minutes: 4.516667, cost_usd: 0.226 },
          ],
          surcharges: [{ component: "llm", label: "Model token surcharge", surcharge_usd: 0.000924, multiplier: 1.13 }],
          catalog_version: "1",
        }
      : null,
    processing_state: c.status === "processing" ? "pending" : "done",
  };
}

const TRANSCRIPT: TranscriptItem[] = [
  {
    id: "ti_0000",
    type: "message",
    role: "agent",
    text: "Hi, how can I help?",
    interrupted: false,
    stt_confidence: null,
    offset_ms: 400,
    turn_index: 0,
  },
  {
    id: "ti_0001",
    type: "message",
    role: "user",
    text: "Where is my order?",
    interrupted: false,
    stt_confidence: 0.92,
    offset_ms: 2100,
    turn_index: null,
  },
  { id: "ti_0002", type: "tool_call", tool_name: "lookup_order", arguments: { id: "A12" }, offset_ms: 3000, turn_index: null },
  {
    id: "ti_0003",
    type: "tool_result",
    tool_call_id: "ti_0002",
    tool_name: "lookup_order",
    output: "timeout",
    is_error: true,
    duration_ms: 3004,
    offset_ms: 6000,
  },
  {
    id: "ti_0004",
    type: "message",
    role: "agent",
    text: "Sorry, let me try again",
    interrupted: true,
    stt_confidence: null,
    offset_ms: 6500,
    turn_index: 1,
  },
];
const TURNS: TurnLatency[] = [
  { turn_index: 0, stt_final_ms: null, llm_ttft_ms: 700, tts_ttfb_ms: 200, e2e_ms: 950 },
  { turn_index: 1, stt_final_ms: 210, llm_ttft_ms: 640, tts_ttfb_ms: null, e2e_ms: 1100 },
];

export function mockStats(total: number): DashboardStats {
  const days = 7;
  return {
    window: { from: "2026-10-10T00:00:00Z", to: "2026-10-17T00:00:00Z" },
    bucket: "day",
    kpis: {
      total_calls: total,
      daily_avg_calls: Math.round((total / days) * 100) / 100,
      total_duration_s: total * 120,
      peak_day: total ? { date: "2026-10-14", total_calls: 4 } : null,
      total_cost_usd: total * 0.2,
      cost_per_call_usd: total ? 0.2 : 0,
      avg_duration_s: 120,
      median_turn_latency_ms: 900,
      p95_turn_latency_ms: 1400,
    },
    sparklines: { calls: [1, 2, 0, 3, 4, 0, 0], duration_s: [], cost_usd: [], avg_duration_s: [] },
    series: Array.from({ length: days }, (_, i) => ({
      bucket_start: `2026-10-${10 + i}`,
      total_calls: i % 3,
      total_duration_s: 60 * i,
      avg_duration_s: 60,
    })),
    disconnect_reasons: { user_hangup: total },
    sentiment: { positive: total, neutral: 0, negative: 0, unknown: 0 },
    channels: { web: total, sip_inbound: 0, sip_outbound: 0, whatsapp: 0 },
    leaderboard: total
      ? [{ agent_id: MOCK_AGENTS[0]!.id, agent_name: "Order desk", total_calls: total, positive_calls: total, negative_calls: 0 }]
      : [],
    distribution: total ? [{ agent_id: MOCK_AGENTS[0]!.id, agent_name: "Order desk", total_calls: total, share: 1 }] : [],
  };
}

const find = (id: string) => store.calls.find((c) => c.call_id === id);

export const callHandlers = [
  http.get(url("/calls"), ({ request }) => {
    tickLive();
    const q = new URL(request.url).searchParams;
    store.requests.push(new URL(request.url).search);
    const rows = store.calls.map((c) => withQuality(c, request)).filter((c) => matches(c, q));
    return json(page(rows, q));
  }),
  http.get(url("/calls/live"), () => {
    tickLive();
    const items = store.calls
      .filter((c) => (c.status === "queued" || c.status === "ringing" || c.status === "in_progress") && c.origin !== "simulation")
      .sort((a, b) => b.started_at.localeCompare(a.started_at))
      .map((c) => {
        const last = c.status === "in_progress" ? liveLines(c.call_id).at(-1) : undefined;
        return {
          call_id: c.call_id,
          status: c.status,
          channel: c.channel,
          direction: directionOf(c),
          origin: c.origin,
          agent: c.agent,
          from_number: c.from_number ?? null,
          to_number: c.to_number ?? null,
          started_at: c.started_at,
          ringing_at: c.started_at,
          connected_at: c.connected_at ?? null,
          last_message: last ? { role: last.role, text: last.text } : null,
        };
      });
    return json({ items: items.slice(0, 50), count: items.length, server_time: new Date().toISOString() });
  }),
  http.get(
    url("/calls/export"),
    () =>
      new HttpResponse("Call ID\n", {
        headers: { "content-type": "text/csv", "content-disposition": 'attachment; filename="calls-2026-10-16.csv"' },
      }),
  ),
  http.get(url("/calls/:id"), ({ params, request }) => {
    tickLive();
    const c = find(String(params.id));
    return c ? json(detail(withQuality(c, request))) : problemDetail(404, "not_found", "No call with that id exists in this workspace.");
  }),
  http.get(url("/calls/:id/transcript"), ({ params }) => {
    const id = String(params.id);
    if (!find(id)) return problemDetail(404, "not_found", "No call.");
    return json({ call_id: id, items: liveScript.some((l) => l.id === id) ? liveTranscript(id) : TRANSCRIPT });
  }),
  http.get(url("/calls/:id/turn-latencies"), ({ params }) => {
    const c = find(String(params.id));
    return c ? json({ call_id: c.call_id, summary: detail(c).latency, turns: TURNS }) : problemDetail(404, "not_found", "No call.");
  }),
  http.get(url("/calls/:id/flow-transitions"), ({ params }) =>
    find(String(params.id)) ? json({ items: [] }) : problemDetail(404, "not_found", "No call."),
  ),
  http.get(url("/calls/:id/recording"), ({ params }) => {
    const c = find(String(params.id));
    if (!c) return problemDetail(404, "not_found", "No call.");
    if (c.call_id === mockCallId(4)) return problemDetail(410, "recording_deleted", "Recording deleted under your retention policy.");
    if (!c.has_recording) return problemDetail(404, "not_recorded", "This call has no recording.");
    return json({
      url: "https://storage.test/rec.ogg",
      expires_at: new Date(Date.now() + 600_000).toISOString(),
      content_type: "audio/ogg",
      filename: `${c.call_id}.ogg`,
    });
  }),
  http.get(url("/calls/:id/compare"), ({ params, request }) => {
    const other = new URL(request.url).searchParams.get("with_call_id") ?? "";
    const a = find(String(params.id));
    const b = find(other);
    if (!a || !b) return problemDetail(404, "not_found", "Call not found.");
    return json({
      left: detail(a),
      right: detail(b),
      right_kind: "call",
      simulation_run_id: null,
      alignment: [{ turn_index: 0, left_item_ids: ["ti_0000"], right_item_ids: ["ti_0000"] }],
      flow_diff: [],
      verdict_diffs: [],
    });
  }),
  http.get(url("/analytics/catalog"), () =>
    json({
      metrics: [{ name: "call_count", label: "Calls", unit: "count" }],
      group_by: ["day", "agent"],
      filters: ["agent_ids"],
      periods: ["this_month"],
      suggested_questions: ["Cost by agent this month", "Busiest day last week"],
    }),
  ),
  http.post(url("/analytics/chat"), async ({ request }) => {
    const body = (await request.json()) as { messages: { content: string }[] };
    const q = body.messages.at(-1)?.content ?? "";
    store.requests.push(`chat:${request.headers.get("Idempotency-Key")}`);
    if (q.includes("#402")) return problemDetail(402, "insufficient_credit", "Add funds to ask about your data.");
    if (q.includes("#429")) return problemDetail(429, "rate_limited", "Too many questions.");
    if (q.includes("#503")) return problemDetail(503, "assistant_unavailable", "The assistant could not answer right now.");
    if (/churn/i.test(q))
      return json({
        outcome: "declined",
        content: "I can't answer that one from your call data. I can answer questions about specific calls and totals or trends of your calls.",
        chart: null,
        table: null,
        truncated: false,
        computed_with: [],
        suggestions: ["What did my last call cost?", "How many calls this week?", "Cost by agent this month"],
      });
    if (/last call/i.test(q)) {
      const latest = store.calls[0] ?? {
        call_id: mockCallId(0),
        started_at: new Date(Date.UTC(2026, 9, 16, 12)).toISOString(),
        agent: { ...MOCK_AGENTS[0]!, deleted: false },
      };
      return json({
        outcome: "answered",
        content: latest
          ? `Your last call was a test call with ${latest.agent.name}: cost $0.100, duration 2:31, status completed.`
          : "I couldn't find any live or test calls. Make a test call from an agent's page and ask again.",
        chart: null,
        table: {
          columns: [
            { key: "call_id", label: "Call", type: "call" },
            { key: "started_at", label: "Started", type: "datetime" },
            { key: "agent_name", label: "Agent", type: "string" },
            { key: "origin", label: "Type", type: "string" },
            { key: "status", label: "Status", type: "string" },
            { key: "duration_s", label: "Duration", type: "seconds" },
            { key: "cost_usd", label: "Cost", type: "usd" },
            { key: "avg_latency_ms", label: "Avg latency", type: "ms" },
          ],
          rows: latest
            ? [
                {
                  call_id: latest.call_id,
                  started_at: latest.started_at,
                  agent_name: latest.agent.name,
                  origin: "test",
                  channel: "web",
                  status: "completed",
                  duration_s: 151,
                  cost_usd: 0.1,
                  avg_latency_ms: 812,
                },
              ]
            : [],
        },
        truncated: false,
        computed_with: [{ kind: "calls", order: "recent", direction: "desc", origins: ["live", "test"], limit: 1 }],
        suggestions: ["Show my last 5 calls", "What was my most expensive call this month?"],
        charged_usd: 0.0012,
      });
    }
    return json({
      outcome: "answered",
      content: "Total cost by agent: Order desk $1.200, Clinic scheduler $0.800.",
      chart: {
        chart_type: "bar",
        x_key: "agent_name",
        series: [{ key: "total_cost_usd", label: "Total cost" }],
        data: [
          { agent_name: "Order desk", total_cost_usd: 1.2 },
          { agent_name: "Clinic scheduler", total_cost_usd: 0.8 },
        ],
      },
      table: {
        columns: [
          { key: "agent_name", label: "Agent", type: "string" },
          { key: "total_cost_usd", label: "Total cost", type: "usd" },
        ],
        rows: [
          { agent_name: "Order desk", total_cost_usd: 1.2 },
          { agent_name: "Clinic scheduler", total_cost_usd: 0.8 },
        ],
      },
      truncated: false,
      computed_with: [{ metrics: ["total_cost_usd"], group_by: ["agent"], period: { preset: "this_month" } }],
      charged_usd: 0.0012,
    });
  }),
  http.post(url("/voice-commands/stream-token"), () =>
    problemDetail(503, "stt_not_configured", "Speech transcription is not configured on this server. Type the command instead."),
  ),
  http.post(url("/voice-commands/interpret"), async ({ request }) => {
    const body = (await request.json()) as { transcript: string };
    if (/failed calls/.test(body.transcript))
      return json({ action: "navigate", target: "/calls", params: { status: ["failed"], date_range: "yesterday" }, speak: null });
    return json({ action: "decline", speak: "I can't do that here.", fallback_suggestion: "Try going to billing." });
  }),
  http.get(url("/dashboard/stats"), () => json(mockStats(store.calls.length))),
  http.get(url("/dashboard/quality"), () =>
    json({ window: mockStats(0).window, prior_window: mockStats(0).window, total_calls_evaluated: 0, per_evaluator: [], per_evaluator_prior: [] }),
  ),
  http.get(url("/dashboard/agent-health"), () => json({ window: mockStats(0).window, prior_window: mockStats(0).window, items: [] })),
];
