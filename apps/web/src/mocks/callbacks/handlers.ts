/**
 * Mock API for spec 011 (scheduled callbacks), shaped by specs/011-callbacks/contracts. The store
 * is filled by `seedMockCallbacks(calls)`, which `seedMockCalls()` runs, so the seeded phone calls
 * carry the callbacks booked on them: the most recent phone call (mock call 1) has a scheduled
 * one, and the callback placed for call 13 is call 9, turned into an outbound call here.
 * `cancelled` records each cancel request so tests can check what reached the server.
 */
import { http, HttpResponse, type JsonBodyType } from "msw";
import type { Callback } from "../../api/callbacks";
import type { CallListItem } from "../../api/calls";
import { env } from "../../lib/env";

const url = (path: string) => `${env.apiBaseUrl}${path}`;
const json = <T>(body: T, status = 200) => HttpResponse.json(body as unknown as JsonBodyType, { status });
const problem = (status: number, code: string, detail: string) =>
  HttpResponse.json({ type: `https://callwright.dev/problems/${code.replace(/_/g, "-")}`, title: "Error", status, code, detail } as JsonBodyType, {
    status,
    headers: { "content-type": "application/problem+json" },
  });

interface Store {
  callbacks: Callback[];
  cancelled: string[];
}
let store: Store = { callbacks: [], cancelled: [] };

export const mockCallbacks = () => store;

export function resetMockCallbacks() {
  store = { callbacks: [], cancelled: [] };
}

export const mockCallbackId = (n: number) => `cbk_01MOCKCALLBACK${String(n).padStart(4, "0")}AAAAAAA`;

/** The workspace number the seeded phone calls came in on. */
const WORKSPACE_NUMBER = "+14155550100";

interface Seed {
  status: Callback["status"];
  /** Index of the seeded call it was booked on, or null when booked through the API. */
  source: number | null;
  /** Index of the seeded call that placed it. */
  placed: number | null;
  to?: string;
  agent?: { id: string; name: string };
  timezone: string;
  /** Recipient wall clock and its UTC offset in hours at that date. */
  local: string;
  offset: number;
  note: string;
  failure?: [string, string];
  cancelledAt?: string;
}

const API_AGENT = { id: "agt_01MOCKAGENTSCHEDULER000002", name: "Clinic scheduler" };

const SEEDS: Seed[] = [
  {
    status: "scheduled",
    source: 1,
    placed: null,
    timezone: "America/New_York",
    local: "2026-10-17T17:00:00",
    offset: -4,
    note: "Caller was heading into a meeting; continue rescheduling the cleaning appointment.",
  },
  {
    status: "scheduled",
    source: 4,
    placed: null,
    timezone: "America/Los_Angeles",
    local: "2026-10-18T09:30:00",
    offset: -7,
    note: "Wants to confirm the delivery address for order A12 before it ships.",
  },
  {
    status: "scheduled",
    source: null,
    placed: null,
    to: "+919820012345",
    agent: API_AGENT,
    timezone: "Asia/Kolkata",
    local: "2026-10-17T10:00:00",
    offset: 5.5,
    note: "Remind the patient about the root canal on Monday and the fasting instructions.",
  },
  {
    status: "placing",
    source: null,
    placed: null,
    to: "+919845011223",
    agent: API_AGENT,
    timezone: "Asia/Kolkata",
    local: "2026-10-16T17:30:00",
    offset: 5.5,
    note: "Follow up on the insurance pre-approval for the crown.",
  },
  {
    status: "placed",
    source: 13,
    placed: 9,
    timezone: "America/Los_Angeles",
    local: "2026-10-15T20:00:00",
    offset: -7,
    note: "Caller was driving; go over the two open Saturday slots for the hygiene visit.",
  },
  {
    status: "failed",
    source: 16,
    placed: null,
    timezone: "America/Los_Angeles",
    local: "2026-10-15T17:30:00",
    offset: -7,
    note: "Call back after work about the refund for the duplicate charge.",
    failure: ["dnc_listed", "The number was added to the do-not-call list after the callback was booked."],
  },
  {
    status: "failed",
    source: null,
    placed: null,
    to: "+442079460958",
    agent: { id: "agt_01MOCKAGENTORDERDESK0000001", name: "Order desk" },
    timezone: "Europe/London",
    local: "2026-10-16T09:00:00",
    offset: 1,
    note: "Confirm the replacement part arrived and close the ticket.",
    failure: ["insufficient_credit", "The workspace balance was below the minimum needed to place a call."],
  },
  {
    status: "cancelled",
    source: 19,
    placed: null,
    timezone: "America/Los_Angeles",
    local: "2026-10-16T14:00:00",
    offset: -7,
    note: "Caller will check with their partner about the Saturday slot and wants a call back.",
    cancelledAt: "2026-10-16T10:15:00Z",
  },
];

function utcOf(local: string, offset: number): string {
  const [d, t] = local.split("T") as [string, string];
  const [y, mo, da] = d.split("-").map(Number) as [number, number, number];
  const [h, mi] = t.split(":").map(Number) as [number, number];
  return new Date(Date.UTC(y, mo - 1, da, h, mi) - offset * 3_600_000).toISOString();
}

/**
 * Callbacks booked on the seeded calls (and a few through the API), in every status. Callbacks
 * whose calls were not seeded are left out, so a short seed (tests) keeps its links valid.
 */
export function seedMockCallbacks(calls: CallListItem[]) {
  const at = (i: number | null) => (i === null ? null : (calls[i] ?? undefined));
  store = {
    cancelled: [],
    callbacks: SEEDS.flatMap((s, n) => {
      const source = at(s.source);
      const placed = at(s.placed);
      if (source === undefined || placed === undefined) return [];
      const scheduledAt = utcOf(s.local, s.offset);
      const to = s.to ?? source?.from_number ?? "+14155550199";
      const agent = s.agent ?? source?.agent ?? API_AGENT;
      if (placed) {
        // The placed callback is an outbound call from the workspace number to the caller.
        Object.assign(placed, { channel: "sip_outbound", from_number: WORKSPACE_NUMBER, to_number: to, agent: { ...agent, deleted: false } });
      }
      const createdAt = source?.started_at ?? new Date(Date.parse(scheduledAt) - 20 * 3_600_000).toISOString();
      const cb: Callback = {
        id: mockCallbackId(n),
        status: s.status,
        scheduled_at: scheduledAt,
        timezone: s.timezone,
        local_time: s.local,
        to_number: to,
        from_number: WORKSPACE_NUMBER,
        phone_number_id: "pn_01MOCKNUMBER000000000000001",
        agent_id: agent.id,
        agent_name: agent.name,
        note: s.note,
        source_call_id: source?.call_id ?? null,
        call_id: placed?.call_id ?? null,
        created_via: source ? "agent" : "api",
        created_by_user_id: source ? null : "usr_01MOCKUSER00000000000000001",
        dynamic_variables: {},
        failure_reason: s.failure?.[0] ?? null,
        failure_detail: s.failure?.[1] ?? null,
        attempts: s.status === "scheduled" || s.status === "cancelled" ? 0 : 1,
        created_at: createdAt,
        updated_at: s.cancelledAt ?? createdAt,
        placed_at: placed ? new Date(Date.parse(scheduledAt) + 4_000).toISOString() : null,
        cancelled_at: s.cancelledAt ?? null,
      };
      return [cb];
    }),
  };
}

export const callbackHandlers = [
  http.get(url("/callbacks"), ({ request }) => {
    const q = new URL(request.url).searchParams;
    const status = q.get("status");
    const source = q.get("source_call_id");
    const rows = store.callbacks
      .filter((c) => (!status || c.status === status) && (!source || c.source_call_id === source))
      .sort((a, b) => (status === "scheduled" ? 1 : -1) * (Date.parse(a.scheduled_at) - Date.parse(b.scheduled_at)));
    const page = Number(q.get("page") ?? 1);
    const size = Number(q.get("page_size") ?? 50);
    return json({
      items: rows.slice((page - 1) * size, page * size),
      total: rows.length,
      page,
      page_size: size,
      total_pages: Math.ceil(rows.length / size),
    });
  }),
  http.get(url("/callbacks/:id"), ({ params }) => {
    const cb = store.callbacks.find((c) => c.id === params.id);
    return cb ? json(cb) : problem(404, "not_found", "No callback with that id exists in this workspace.");
  }),
  http.post(url("/callbacks/:id/cancel"), ({ params }) => {
    const cb = store.callbacks.find((c) => c.id === params.id);
    store.cancelled.push(String(params.id));
    if (!cb) return problem(404, "not_found", "No callback with that id exists in this workspace.");
    if (cb.status === "cancelled") return json(cb);
    if (cb.status !== "scheduled")
      return problem(409, "callback_not_scheduled", "This callback is already being placed, was placed or failed, so it cannot be cancelled.");
    const now = new Date().toISOString();
    Object.assign(cb, { status: "cancelled", cancelled_at: now, updated_at: now });
    return json(cb);
  }),
];
