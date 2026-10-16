/**
 * Mock API for spec 001, built from the contracts: every response body is typed with the
 * generated schema types, status codes follow the contract files, and errors are RFC 9457
 * problems. Enabled with VITE_API_MOCKS=true (pnpm dev:mock) and always in Vitest.
 *
 * Demo account: ops@halcyon-dental.com / correct-horse-9 (verified, seeded ledger).
 * Behaviour switches for manual testing:
 * - sign-in with any email containing "unverified" returns 403 email_unverified
 * - 5 wrong passwords within 15 minutes return 429 with retry_after_s
 * - verify-email / password-reset tokens "expired" return 400
 * - GET /billing/transactions/txn_00000000000000000000000500 returns a 500 with trace_id
 */
import { delay, http, HttpResponse, type JsonBodyType } from "msw";
import type {
  Balance,
  Catalog,
  CheckoutSession,
  FieldError,
  Me,
  Problem,
  Quote,
  QuoteRequest,
  Session,
  Transaction,
  TransactionPage,
  UsageReport,
  UsageRow,
  Workspace,
  FeatureFamily,
} from "../api/types";
import { env } from "../lib/env";
import { checkTopUpAmount, microsToDecimal, toMicros } from "../lib/money";
import { priceQuote } from "../lib/pricing";
import { catalogV1 } from "./catalog";
import { appendTransaction, balanceOf, db, mockId, save, type MockUser } from "./db";

const base = env.apiBaseUrl;
const url = (path: string) => `${base}${path}`;

function problem(status: number, code: string, title: string, extra: Partial<Problem> = {}) {
  const body: Problem = { type: `https://callwright.dev/problems/${code.replace(/_/g, "-")}`, title, status, code, ...extra };
  const headers: Record<string, string> = { "content-type": "application/problem+json" };
  if (extra.retry_after_s) headers["retry-after"] = String(extra.retry_after_s);
  return HttpResponse.json(body as unknown as JsonBodyType, { status, headers });
}

function validation(errors: FieldError[]) {
  return problem(422, "validation_failed", "Request failed validation", { errors });
}

const json = <T,>(body: T, status = 200) => HttpResponse.json(body as unknown as JsonBodyType, { status });

function issueSession(user: MockUser): Session {
  const access = `mock-access.${user.id}.${mockId("tok")}`;
  const refresh = `mock-refresh.${user.id}.${mockId("tok")}`;
  db().sessions[access] = user.id;
  db().sessions[refresh] = user.id;
  save();
  return { access_token: access, refresh_token: refresh, token_type: "bearer", expires_in: 3600 };
}

function currentUser(request: Request): MockUser | null {
  const token = request.headers.get("authorization")?.replace(/^Bearer\s+/i, "");
  if (!token || !token.startsWith("mock-access.")) return null;
  const id = db().sessions[token];
  return db().users.find((u) => u.id === id) ?? null;
}

function workspaceOf(user: MockUser): Workspace | undefined {
  return db().workspaces.find((w) => w.id === user.workspace_id);
}

/** Pending mock checkouts become top-ups a few seconds later, like a Stripe webhook would. */
function settlePending() {
  const now = Date.now();
  const due = db().pending.filter((p) => p.credit_at <= now);
  if (!due.length) return;
  db().pending = db().pending.filter((p) => p.credit_at > now);
  for (const p of due) appendTransaction(db(), p.workspace_id, "top_up", p.amount, "Top-up via card ending 4242");
  save();
}

const unauthorized = () => problem(401, "unauthorized", "Sign in required");

function bootstrapWorkspace(user: MockUser) {
  if (user.workspace_id) return;
  const local = user.email.split("@")[0] ?? "My";
  const ws: Workspace = {
    id: mockId("ws"),
    name: `${local.charAt(0).toUpperCase()}${local.slice(1)}'s workspace`,
    concurrency_limit: 5,
    recording_default: true,
    created_at: new Date().toISOString(),
  };
  db().workspaces.push(ws);
  user.workspace_id = ws.id;
  appendTransaction(db(), ws.id, "trial_grant", "5.000000", "Trial credit");
}

const FAMILIES: FeatureFamily[] = [
  "calls",
  "evaluations",
  "simulations",
  "testing",
  "analytics_chat",
  "prompt_generation",
  "post_call_analysis",
  "flow_assistant",
  "voice_copilot",
  "issues",
  "knowledge_ingestion",
  "embedding",
];

/** usage.yaml FeatureFamily: the key prefix before the first dot; eval and simulator are renamed. */
function familyOf(featureKey: string): FeatureFamily | undefined {
  const prefix = featureKey.split(".")[0] ?? "";
  const name = prefix === "eval" ? "evaluations" : prefix === "simulator" ? "simulations" : prefix;
  return FAMILIES.find((f) => f === name);
}

const today = () => new Date().toISOString().slice(0, 10);
function addDays(date: string, days: number) {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export const handlers = [
  http.get(url("/health"), () => json({ status: "ok", version: "mock" })),

  // --- auth ----------------------------------------------------------------
  http.post(url("/auth/register"), async ({ request }) => {
    const body = (await request.json()) as { email?: string; password?: string };
    const errors: FieldError[] = [];
    if (!body.email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(body.email))
      errors.push({ pointer: "/email", code: "invalid_format", message: "Enter a valid email address." });
    if (!body.password || body.password.length < 10)
      errors.push({ pointer: "/password", code: "too_short", message: "Use at least 10 characters." });
    if (errors.length) return validation(errors);
    const email = body.email!.toLowerCase();
    if (!db().users.some((u) => u.email === email)) {
      db().users.push({ id: mockId("usr"), email, password: body.password!, email_verified: false, is_admin: false, workspace_id: null });
    }
    db().verifyTokens[`verify-${email}`] = email;
    save();
    await delay(250);
    return json({ status: "verification_sent" }, 202);
  }),

  http.post(url("/auth/verify-email"), async ({ request }) => {
    const { token_hash } = (await request.json()) as { token_hash: string };
    const email = db().verifyTokens[token_hash];
    const user = db().users.find((u) => u.email === email);
    if (!email || !user || token_hash === "expired") return problem(400, "link_invalid", "Link invalid, used or expired");
    user.email_verified = true;
    bootstrapWorkspace(user);
    delete db().verifyTokens[token_hash];
    save();
    return json<Session>(issueSession(user));
  }),

  http.post(url("/auth/verify-email/resend"), async () => {
    await delay(200);
    return new HttpResponse(null, { status: 202 });
  }),

  http.post(url("/auth/sign-in"), async ({ request }) => {
    const { email = "", password = "" } = (await request.json()) as { email?: string; password?: string };
    await delay(300);
    const key = email.toLowerCase();
    const f = db().failures[key];
    const windowMs = 15 * 60_000;
    if (f && f.count >= 5 && Date.now() - f.first < windowMs) {
      return problem(429, "too_many_attempts", "Too many sign-in attempts", {
        retry_after_s: Math.ceil((f.first + windowMs - Date.now()) / 1000),
      });
    }
    if (key.includes("unverified")) return problem(403, "email_unverified", "Email not verified");
    const user = db().users.find((u) => u.email === key);
    if (!user || user.password !== password) {
      const prev = f && Date.now() - f.first < windowMs ? f : { count: 0, first: Date.now() };
      db().failures[key] = { count: prev.count + 1, first: prev.first };
      save();
      return problem(401, "invalid_credentials", "Wrong email or password");
    }
    if (!user.email_verified) return problem(403, "email_unverified", "Email not verified");
    delete db().failures[key];
    return json<Session>(issueSession(user));
  }),

  http.post(url("/auth/refresh"), async ({ request }) => {
    const { refresh_token } = (await request.json()) as { refresh_token: string };
    const id = db().sessions[refresh_token];
    const user = db().users.find((u) => u.id === id);
    if (!user) return unauthorized();
    delete db().sessions[refresh_token];
    return json<Session>(issueSession(user));
  }),

  http.post(url("/auth/sign-out"), ({ request }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    for (const [t, id] of Object.entries(db().sessions)) if (id === user.id) delete db().sessions[t];
    save();
    return new HttpResponse(null, { status: 204 });
  }),

  http.post(url("/auth/password-reset"), async ({ request }) => {
    const { email = "" } = (await request.json()) as { email?: string };
    const key = email.toLowerCase();
    if (db().users.some((u) => u.email === key)) {
      db().resetTokens[`reset-${key}`] = { email: key, used: false, expires: Date.now() + 3_600_000 };
      save();
    }
    await delay(250);
    return new HttpResponse(null, { status: 202 });
  }),

  http.post(url("/auth/password-reset/confirm"), async ({ request }) => {
    const { token_hash, new_password = "" } = (await request.json()) as { token_hash: string; new_password?: string };
    const t = db().resetTokens[token_hash];
    if (!t || t.used || t.expires < Date.now() || token_hash === "expired")
      return problem(400, "link_invalid", "Link invalid, used or expired");
    if (new_password.length < 10)
      return validation([{ pointer: "/new_password", code: "too_short", message: "Use at least 10 characters." }]);
    const user = db().users.find((u) => u.email === t.email);
    if (user) user.password = new_password;
    t.used = true;
    save();
    return new HttpResponse(null, { status: 204 });
  }),

  // --- workspaces ----------------------------------------------------------
  http.get(url("/me"), ({ request }) => {
    const user = currentUser(request);
    const ws = user && workspaceOf(user);
    if (!user || !ws) return unauthorized();
    settlePending();
    const me: Me = {
      user: { id: user.id, email: user.email, email_verified: user.email_verified, is_admin: user.is_admin },
      workspace: ws,
      balance_usd: microsToDecimal(balanceOf(db(), ws.id), 6),
    };
    return json(me);
  }),

  http.patch(url("/workspaces/current"), async ({ request }) => {
    const user = currentUser(request);
    const ws = user && workspaceOf(user);
    if (!user || !ws) return unauthorized();
    const body = (await request.json()) as { name?: unknown; recording_default?: unknown };
    const errors: FieldError[] = [];
    if (body.name !== undefined) {
      if (typeof body.name !== "string" || body.name.trim().length === 0)
        errors.push({ pointer: "/name", code: "required", message: "Enter a workspace name." });
      else if (body.name.length > 80)
        errors.push({ pointer: "/name", code: "too_long", message: "Keep the name to 80 characters or fewer." });
    }
    if (body.recording_default !== undefined && typeof body.recording_default !== "boolean")
      errors.push({ pointer: "/recording_default", code: "invalid_format", message: "Choose on or off." });
    if (body.name === undefined && body.recording_default === undefined)
      errors.push({ pointer: "", code: "required", message: "Nothing to update." });
    if (errors.length) return validation(errors);
    await delay(350);
    if (typeof body.name === "string") ws.name = body.name.trim();
    if (typeof body.recording_default === "boolean") ws.recording_default = body.recording_default;
    save();
    return json<Workspace>(ws);
  }),

  // --- billing -------------------------------------------------------------
  http.get(url("/billing/balance"), ({ request }) => {
    const user = currentUser(request);
    if (!user?.workspace_id) return unauthorized();
    settlePending();
    const rows = db().transactions.filter((t) => t.workspace_id === user.workspace_id);
    return json<Balance>({ balance_usd: microsToDecimal(balanceOf(db(), user.workspace_id), 6), as_of_seq: rows.length });
  }),

  http.post(url("/billing/checkout-sessions"), async ({ request }) => {
    const user = currentUser(request);
    if (!user?.workspace_id) return unauthorized();
    const { amount_usd = "" } = (await request.json()) as { amount_usd?: string };
    const check = checkTopUpAmount(String(amount_usd));
    if (!check.ok) return validation([{ pointer: "/amount_usd", code: "out_of_range", message: check.reason }]);
    db().pending.push({ workspace_id: user.workspace_id, amount: check.normalized, credit_at: Date.now() + 3000 });
    save();
    await delay(400);
    const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost:5180";
    return json<CheckoutSession>(
      { checkout_url: `${origin}/billing?checkout=success`, expires_at: new Date(Date.now() + 30 * 60_000).toISOString() },
      201,
    );
  }),

  http.get(url("/billing/transactions"), async ({ request }) => {
    const user = currentUser(request);
    if (!user?.workspace_id) return unauthorized();
    settlePending();
    const q = new URL(request.url).searchParams;
    const page = Math.max(1, Number(q.get("page") ?? 1));
    const pageSize = Math.min(100, Math.max(1, Number(q.get("page_size") ?? 20)));
    const type = q.get("type");
    const rows = db()
      .transactions.filter((t) => t.workspace_id === user.workspace_id && (!type || t.type === type))
      .slice()
      .reverse();
    await delay(180);
    const items: Transaction[] = rows
      .slice((page - 1) * pageSize, page * pageSize)
      .map(({ workspace_id: _ws, ...t }) => t);
    return json<TransactionPage>({
      items,
      total: rows.length,
      page,
      page_size: pageSize,
      total_pages: Math.ceil(rows.length / pageSize),
    });
  }),

  http.get(url("/billing/transactions/:transaction_id"), ({ request, params }) => {
    const user = currentUser(request);
    if (!user?.workspace_id) return unauthorized();
    const id = String(params.transaction_id);
    if (id === "txn_00000000000000000000000500")
      return problem(500, "internal", "Something went wrong", { trace_id: "4f1c9e0a7b2d4e83a6c15d0f9b7e2a41" });
    if (!/^txn_[0-9A-HJKMNP-TV-Z]{26}$/.test(id)) return problem(404, "not_found", "Not found");
    const t = db().transactions.find((x) => x.id === id && x.workspace_id === user.workspace_id);
    if (!t) return problem(404, "not_found", "Not found");
    const { workspace_id: _ws, ...rest } = t;
    return json<Transaction>(rest);
  }),

  // --- pricing -------------------------------------------------------------
  http.get(url("/pricing/catalog"), () =>
    HttpResponse.json(catalogV1 satisfies Catalog as unknown as JsonBodyType, { headers: { "cache-control": "public, max-age=300" } }),
  ),

  http.post(url("/pricing/quote"), async ({ request }) => {
    const body = (await request.json()) as QuoteRequest;
    if (!body?.components?.stt || !body.components.llm || !body.components.tts)
      return validation([{ pointer: "/components", code: "required", message: "Choose speech-to-text, model and voice." }]);
    await delay(60);
    const q = priceQuote(catalogV1 as Parameters<typeof priceQuote>[0], body.components, body.usage);
    return json<Quote>(q as Quote);
  }),

  // --- usage ---------------------------------------------------------------
  http.get(url("/usage"), async ({ request }) => {
    const user = currentUser(request);
    if (!user?.workspace_id) return unauthorized();
    const q = new URL(request.url).searchParams;
    const to = q.get("to") ?? today();
    const from = q.get("from") ?? addDays(to, -30);
    if (from > to) return validation([{ pointer: "/to", code: "out_of_range", message: "The end date must be on or after the start date." }]);
    const span = (Date.parse(to) - Date.parse(from)) / 86_400_000;
    if (span > 366) return validation([{ pointer: "/from", code: "out_of_range", message: "Pick a window of 366 days or less." }]);
    await delay(200);
    const inWindow = db().usage.filter((u) => u.workspace_id === user.workspace_id && u.at.slice(0, 10) >= from && u.at.slice(0, 10) <= to);
    const rows = new Map<FeatureFamily, UsageRow>();
    let totalRaw = 0n;
    let totalBill = 0n;
    for (const ev of inWindow) {
      const family = familyOf(ev.feature_key);
      if (!family) continue;
      const row = rows.get(family) ?? { feature: family, event_count: 0, raw_cost_usd: "0.000000", billable_cost_usd: "0.000000", details: [] };
      const raw = toMicros(ev.raw) ?? 0n;
      const bill = toMicros(ev.billable) ?? 0n;
      row.event_count += 1;
      row.raw_cost_usd = microsToDecimal((toMicros(row.raw_cost_usd) ?? 0n) + raw, 6);
      row.billable_cost_usd = microsToDecimal((toMicros(row.billable_cost_usd) ?? 0n) + bill, 6);
      let d = row.details.find((x) => x.feature_key === ev.feature_key);
      if (!d) {
        d = { feature_key: ev.feature_key, event_count: 0, raw_cost_usd: "0.000000", billable_cost_usd: "0.000000" };
        row.details.push(d);
      }
      d.event_count += 1;
      d.raw_cost_usd = microsToDecimal((toMicros(d.raw_cost_usd) ?? 0n) + raw, 6);
      d.billable_cost_usd = microsToDecimal((toMicros(d.billable_cost_usd) ?? 0n) + bill, 6);
      rows.set(family, row);
      totalRaw += raw;
      totalBill += bill;
    }
    return json<UsageReport>({
      window: { from, to },
      rows: [...rows.values()],
      total_raw_cost_usd: microsToDecimal(totalRaw, 6),
      total_billable_cost_usd: microsToDecimal(totalBill, 6),
    });
  }),
];
