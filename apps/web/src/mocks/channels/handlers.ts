/**
 * Mock API for spec 010 (phone numbers, outbound calls and compliance, WhatsApp), shaped by
 * specs/010-channels/contracts. In memory, empty until something is created, so the dashboard
 * keeps its setup sequence. Behaviour switches for manual testing:
 * - a termination address containing "fail" saves the number in `error`
 * - a WhatsApp access token containing "invalid" is rejected
 * - an outbound call to a number on the do-not-call list is blocked with `dnc_listed`
 */
import { http, HttpResponse } from "msw";
import type { components } from "../../api/schema";
import { db } from "../db";
import { invalid, json, page, problemDetail, unauthorized, url } from "../http";

type S = components["schemas"];
type PhoneNumber = S["PhoneNumber"];
type WhatsAppChannel = S["WhatsAppChannel"];
type CallerRoute = S["CallerRoute"];
type DncEntry = S["DncEntry"];
type PolicyDecision = S["PolicyDecision"];
type WeeklyWindows = S["WeeklyWindows"];

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
const DEFAULT_WINDOWS = Object.fromEntries(DAYS.map((d) => [d, { start: "09:00", end: "21:00" }])) as WeeklyWindows;

interface Store {
  numbers: PhoneNumber[];
  channels: WhatsAppChannel[];
  routes: CallerRoute[];
  dnc: DncEntry[];
  hours: { windows: WeeklyWindows; updated_at: string | null };
  decisions: PolicyDecision[];
}
const empty = (): Store => ({ numbers: [], channels: [], routes: [], dnc: [], hours: { windows: DEFAULT_WINDOWS, updated_at: null }, decisions: [] });
let store: Store = empty();

export const mockChannels = () => store;
export function resetMockChannels() {
  store = empty();
}

let seq = 0;
const id = (prefix: string) => `${prefix}_01MOCK${String(++seq).padStart(4, "0")}${"A".repeat(16)}`;
const now = () => new Date().toISOString();
const signedIn = (request: Request) => {
  const token = request.headers.get("authorization")?.replace(/^Bearer\s+/i, "");
  return !!token && !!db().sessions[token];
};
const E164 = /^\+[1-9]\d{6,14}$/;

export function seedMockChannels() {
  store.numbers.push({
    id: id("num"),
    e164: "+14155550100",
    label: "Main office line",
    termination_address: "trunk.example-carrier.com:5060",
    transport: "auto",
    auth_username: "acme",
    has_auth_password: true,
    inbound_allowed_cidrs: [],
    inbound_agent_id: null,
    outbound_agent_id: null,
    inbound_webhook_url: null,
    direct_uri: "sip:+14155550100@sip.callwright.example",
    status: "active",
    status_detail: null,
    active_call_count: 0,
    created_at: now(),
    updated_at: now(),
  });
}

export const channelHandlers = [
  // Phone numbers -----------------------------------------------------------------------------
  http.get(url("/phone-numbers/sip-settings"), ({ request }) =>
    signedIn(request)
      ? json({
          origination_uri: "sip:sip.callwright.example",
          direct_uri_template: "sip:{e164}@sip.callwright.example",
          transports: ["udp", "tcp", "tls"],
          telephony_enabled: true,
        })
      : unauthorized(),
  ),
  http.get(url("/phone-numbers"), ({ request }) => (signedIn(request) ? json(page(store.numbers, request)) : unauthorized())),
  http.post(url("/phone-numbers"), async ({ request }) => {
    if (!signedIn(request)) return unauthorized();
    const b = (await request.json()) as S["PhoneNumberImport"];
    if (!E164.test(b.e164 ?? "")) return invalid("/e164", "Enter the number in E.164 form, for example +14155550123.", "invalid_format");
    if (/[@;/?]/.test(b.termination_address ?? "")) return invalid("/termination_address", "Enter only a host and optional port.", "invalid_format");
    if (store.numbers.some((n) => n.e164 === b.e164)) return problemDetail(409, "number_already_registered", "This number is already connected.");
    const failed = (b.termination_address ?? "").includes("fail");
    const n: PhoneNumber = {
      id: id("num"),
      e164: b.e164,
      label: b.label,
      termination_address: b.termination_address.replace(/^sips?:/i, ""),
      transport: b.transport ?? "auto",
      auth_username: b.auth_username ?? null,
      has_auth_password: !!b.auth_password,
      inbound_allowed_cidrs: b.inbound_allowed_cidrs ?? [],
      inbound_agent_id: b.inbound_agent_id ?? null,
      outbound_agent_id: b.outbound_agent_id ?? null,
      inbound_webhook_url: b.inbound_webhook_url ?? null,
      direct_uri: `sip:${b.e164}@sip.callwright.example`,
      status: failed ? "error" : "active",
      status_detail: failed ? "The SIP service refused outbound trunk creation (simulated)." : null,
      active_call_count: 0,
      created_at: now(),
      updated_at: now(),
    };
    store.numbers.unshift(n);
    return json(n, 201);
  }),
  http.get(url("/phone-numbers/:id"), ({ params }) => {
    const n = store.numbers.find((x) => x.id === params.id);
    return n ? json(n) : problemDetail(404, "not_found", "No phone number");
  }),
  http.patch(url("/phone-numbers/:id"), async ({ params, request }) => {
    const n = store.numbers.find((x) => x.id === params.id);
    if (!n) return problemDetail(404, "not_found", "No phone number");
    const b = (await request.json()) as S["PhoneNumberUpdate"] & Record<string, unknown>;
    if (b.auth_password) n.has_auth_password = true;
    if (b.remove_auth_password) n.has_auth_password = false;
    const { auth_password: _p, remove_auth_password: _r, ...rest } = b;
    Object.assign(n, rest, { updated_at: now() });
    return json(n);
  }),
  http.delete(url("/phone-numbers/:id"), ({ params, request }) => {
    const n = store.numbers.find((x) => x.id === params.id);
    if (!n) return problemDetail(404, "not_found", "No phone number");
    const whenIdle = new URL(request.url).searchParams.get("when_idle") === "true";
    if (n.active_call_count > 0) {
      if (!whenIdle) return problemDetail(409, "number_has_active_calls", "Calls are active", { active_call_count: n.active_call_count });
      n.status = "draining";
      return json(n, 202);
    }
    store.numbers = store.numbers.filter((x) => x.id !== n.id);
    return new HttpResponse(null, { status: 204 });
  }),
  http.post(url("/phone-numbers/:id/retry-provisioning"), ({ params }) => {
    const n = store.numbers.find((x) => x.id === params.id);
    if (!n) return problemDetail(404, "not_found", "No phone number");
    Object.assign(n, { status: "active", status_detail: null });
    return json(n);
  }),
  http.post(url("/webhooks/test"), () => json({ n: 1, at: now(), status_code: 200, duration_ms: 84, error: null, response_excerpt: "ok" })),

  // Outbound and compliance ---------------------------------------------------------------------
  http.post(url("/outbound-calls"), async ({ request }) => {
    const b = (await request.json()) as S["OutboundCallRequest"];
    const entry = store.dnc.find((d) => d.number === b.to_number);
    const n = store.numbers.find((x) => x.e164 === b.from_number);
    if (entry) {
      store.decisions.unshift({
        id: store.decisions.length + 1,
        decided_at: now(),
        reason: "dnc_listed",
        to_number: b.to_number,
        from_number: b.from_number,
        requested_by: "usr_mock",
        dnc_entry_id: entry.id,
        dnc_number: entry.number,
      });
      return problemDetail(422, "outbound_policy", "This number is on the do-not-call list.", {
        reason: "dnc_listed",
        to_number: b.to_number,
        dnc_entry_id: entry.id,
      });
    }
    return json(
      {
        call_id: id("call"),
        status: "queued",
        to_number: b.to_number,
        from_number: b.from_number,
        agent_id: b.agent_id ?? n?.outbound_agent_id ?? "",
        agent_version_id: "agv_01MOCKVERSION000000000000001",
        phone_number_id: n?.id ?? "",
        missing_variables: [],
        idempotent_replay: false,
        recipient_timezones: [b.recipient_timezone ?? "America/Los_Angeles"],
        timezone_source: b.recipient_timezone ? "override" : "number_region",
      },
      202,
    );
  }),
  http.get(url("/dnc-entries"), ({ request }) => {
    const q = new URL(request.url).searchParams.get("number")?.replace(/\D/g, "") ?? "";
    return json(
      page(
        store.dnc.filter((d) => d.number.includes(q)),
        request,
      ),
    );
  }),
  http.post(url("/dnc-entries"), async ({ request }) => {
    const b = (await request.json()) as S["DncEntryCreate"];
    const digits = b.number.replace(/\D/g, "");
    const number = b.number.trim().startsWith("+") ? `+${digits}` : b.default_region === "US" ? `+1${digits}` : "";
    if (!E164.test(number)) return problemDetail(422, "invalid_number", "Not a phone number");
    if (store.dnc.some((d) => d.number === number)) return problemDetail(409, "dnc_entry_exists", "Already listed");
    const e: DncEntry = { id: id("dnc"), number, note: b.note ?? null, source: "manual", created_by_user_id: "usr_mock", created_at: now() };
    store.dnc.unshift(e);
    return json(e, 201);
  }),
  http.delete(url("/dnc-entries/:id"), ({ params }) => {
    store.dnc = store.dnc.filter((d) => d.id !== params.id);
    return new HttpResponse(null, { status: 204 });
  }),
  http.post(url("/dnc-entries/import"), () =>
    json({ rows: 3, imported: 2, duplicates: 0, invalid_count: 1, invalid: [{ row: 3, value: "nope", error: "This is not a phone number." }] }),
  ),
  http.get(url("/outbound-calling-hours"), () =>
    json({
      windows: store.hours.windows,
      is_default: JSON.stringify(store.hours.windows) === JSON.stringify(DEFAULT_WINDOWS),
      updated_by_user_id: null,
      updated_at: store.hours.updated_at,
    }),
  ),
  http.put(url("/outbound-calling-hours"), async ({ request }) => {
    const b = (await request.json()) as { windows: WeeklyWindows };
    store.hours = { windows: b.windows, updated_at: now() };
    return json({
      windows: b.windows,
      is_default: JSON.stringify(b.windows) === JSON.stringify(DEFAULT_WINDOWS),
      updated_by_user_id: "usr_mock",
      updated_at: now(),
    });
  }),
  http.get(url("/outbound-policy-decisions"), ({ request }) => json(page(store.decisions, request, 50))),

  // WhatsApp ------------------------------------------------------------------------------------
  http.get(url("/whatsapp/settings"), () =>
    json({ callback_url: "https://api.callwright.example/v1/whatsapp/webhook", default_graph_api_version: "v23.0", telephony_enabled: true }),
  ),
  http.get(url("/whatsapp/channels"), ({ request }) => (signedIn(request) ? json(page(store.channels, request, 100)) : unauthorized())),
  http.post(url("/whatsapp/channels"), async ({ request }) => {
    const b = (await request.json()) as S["WhatsAppChannelCreate"];
    if (!/^\d{5,32}$/.test(b.meta_phone_number_id)) return invalid("/meta_phone_number_id", "Digits only.", "invalid_format");
    if (b.access_token.includes("invalid"))
      return problemDetail(422, "whatsapp_token_rejected", "WhatsApp said: Error validating access token: Session has expired.");
    const c: WhatsAppChannel = {
      id: id("wa"),
      meta_phone_number_id: b.meta_phone_number_id,
      e164: b.e164,
      label: b.label,
      access_token_last4: b.access_token.slice(-4),
      verify_token_last4: b.verify_token.slice(-4),
      has_app_secret: true,
      graph_api_version: b.graph_api_version ?? "v23.0",
      inbound_agent_id: b.inbound_agent_id ?? null,
      inbound_webhook_url: b.inbound_webhook_url ?? null,
      caller_route_count: 0,
      status: "setup_incomplete",
      status_detail: null,
      credentials_verified_at: now(),
      calling_enabled_at: now(),
      webhook_verified_at: null,
      last_webhook_at: null,
      active_call_count: 0,
      created_at: now(),
      updated_at: now(),
    };
    store.channels.unshift(c);
    return json(c, 201);
  }),
  http.get(url("/whatsapp/channels/:id"), ({ params }) => {
    const c = store.channels.find((x) => x.id === params.id);
    return c ? json(c) : problemDetail(404, "not_found", "No channel");
  }),
  http.patch(url("/whatsapp/channels/:id"), async ({ params, request }) => {
    const c = store.channels.find((x) => x.id === params.id);
    if (!c) return problemDetail(404, "not_found", "No channel");
    const b = (await request.json()) as S["WhatsAppChannelUpdate"];
    const { access_token, verify_token, app_secret: _s, ...rest } = b;
    if (access_token) c.access_token_last4 = access_token.slice(-4);
    if (verify_token) Object.assign(c, { verify_token_last4: verify_token.slice(-4), webhook_verified_at: null, status: "setup_incomplete" });
    Object.assign(c, rest, { updated_at: now() });
    return json(c);
  }),
  http.delete(url("/whatsapp/channels/:id"), ({ params }) => {
    store.channels = store.channels.filter((x) => x.id !== params.id);
    return new HttpResponse(null, { status: 204 });
  }),
  http.post(url("/whatsapp/channels/:id/retry-setup"), ({ params }) => {
    const c = store.channels.find((x) => x.id === params.id);
    return c ? json(c) : problemDetail(404, "not_found", "No channel");
  }),
  http.get(url("/whatsapp/channels/:id/caller-routes"), ({ params, request }) =>
    json(
      page(
        store.routes.filter((r) => r.channel_id === params.id),
        request,
        50,
      ),
    ),
  ),
  http.post(url("/whatsapp/channels/:id/caller-routes"), async ({ params, request }) => {
    const b = (await request.json()) as { caller_number: string; agent_id: string };
    const caller = b.caller_number.startsWith("+") ? b.caller_number : `+${b.caller_number}`;
    if (!E164.test(caller)) return invalid("/caller_number", "Enter the number in E.164 form.", "invalid_format");
    if (store.routes.some((r) => r.channel_id === params.id && r.caller_number === caller))
      return problemDetail(409, "duplicate_caller_route", "Duplicate");
    const r: CallerRoute = {
      id: id("wcr"),
      channel_id: String(params.id),
      caller_number: caller,
      agent_id: b.agent_id,
      agent_published: true,
      created_at: now(),
    };
    store.routes.unshift(r);
    const c = store.channels.find((x) => x.id === params.id);
    if (c) c.caller_route_count = (c.caller_route_count ?? 0) + 1;
    return json(r, 201);
  }),
  http.patch(url("/whatsapp/channels/:id/caller-routes/:route"), async ({ params, request }) => {
    const r = store.routes.find((x) => x.id === params.route);
    if (!r) return problemDetail(404, "not_found", "No route");
    r.agent_id = ((await request.json()) as { agent_id: string }).agent_id;
    return json(r);
  }),
  http.delete(url("/whatsapp/channels/:id/caller-routes/:route"), ({ params }) => {
    store.routes = store.routes.filter((x) => x.id !== params.route);
    const c = store.channels.find((x) => x.id === params.id);
    if (c) c.caller_route_count = Math.max(0, (c.caller_route_count ?? 1) - 1);
    return new HttpResponse(null, { status: 204 });
  }),
];
