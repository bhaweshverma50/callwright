/**
 * Mock API for spec 001, built from the contracts: every response body is typed with the
 * generated schema types, status codes follow the contract files, and errors are RFC 9457
 * problems. Enabled with VITE_API_MOCKS=true (pnpm dev:mock) and always in Vitest.
 *
 * Demo account: DEMO_EMAIL / DEMO_PASSWORD (demoAccount.ts; verified, seeded ledger). The
 * behaviour switches for manual testing are the constants below.
 */
import { delay, http, HttpResponse } from "msw";
import type {
  Balance,
  Catalog,
  CheckoutSession,
  FieldError,
  Me,
  OnboardingStatus,
  Preferences,
  Quote,
  QuoteRequest,
  Session,
  Transaction,
  UsageReport,
  UsageRow,
  Workspace,
  FeatureFamily,
} from "../api/types";
import { checkTopUpAmount, microsToDecimal, toMicros } from "../lib/money";
import { priceQuote } from "./pricing/engine";
import { catalogCurrent } from "./pricing/catalog";
import { appendTransaction, balanceOf, db, mockId, save, type MockUser } from "./db";
import { json, page, problem, unauthorized, url, validation } from "./http";
import { mockResetToken, mockVerifyToken } from "./demoAccount";

/** Sign-in with an email containing this returns 403 email_unverified. */
const UNVERIFIED_MARKER = "unverified";
/** A verify-email or password-reset token with this value is expired (400 link_invalid). */
const EXPIRED_TOKEN = "expired";
/** Mock "Continue with Google": the state prefix the mock accepts and the account it signs in. */
const MOCK_GOOGLE_STATE = "mock-google-";
const MOCK_GOOGLE_EMAIL = "google.user@example.com";
/** The API's per-account sign-in throttle (auth/service.py): 5 failures in 15 minutes, then 429. */
const MAX_FAILED_SIGN_INS = 5;
const FAILED_SIGN_IN_WINDOW_MS = 15 * 60_000;
/** GET /billing/transactions/<this id> answers 500 with a trace id, to show the server-error state. */
const FAILING_TRANSACTION_ID = "txn_00000000000000000000000500";
/** Usage windows cover at most this many days, both ends included (usage/service.py MAX_DAYS). */
const MAX_USAGE_DAYS = 366;

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

const ONBOARDING_STATUSES: OnboardingStatus[] = ["not_started", "in_progress", "skipped", "completed"];

/** Saved preferences, or the defaults a user who never saved anything gets. */
function preferencesOf(userId: string): Preferences {
  return db().preferences?.[userId] ?? { onboarding: { status: "not_started", step: null, updated_at: null } };
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

/** Test checkout sessions (mirror of services/api/app/dev/router.py TEST_CARDS). */
const TEST_CARDS = [
  { number: "4242424242424242", brand: "visa", label: "Payment succeeds", outcome: "succeeded" },
  { number: "5555555555554444", brand: "mastercard", label: "Payment succeeds", outcome: "succeeded" },
  { number: "4000000000000002", brand: "visa", label: "Card declined", outcome: "card_declined" },
  { number: "4000000000009995", brand: "visa", label: "Insufficient funds", outcome: "insufficient_funds" },
  { number: "4000000000000069", brand: "visa", label: "Expired card", outcome: "expired_card" },
  { number: "4000000000000127", brand: "visa", label: "Incorrect CVC", outcome: "incorrect_cvc" },
  { number: "4000000000000119", brand: "visa", label: "Processing error", outcome: "processing_error" },
];
const DECLINES: Record<string, string> = {
  card_declined: "Your card was declined.",
  insufficient_funds: "Your card has insufficient funds.",
  expired_card: "Your card has expired.",
  incorrect_cvc: "Your card's security code is incorrect.",
  processing_error: "An error occurred while processing your card. Try again in a little bit.",
};
type MockCheckout = { workspace_id: string; amount: string; status: "pending" | "completed" };
// Checkout is a full page load away from Billing, so sessions live in localStorage like the mock db.
const CHECKOUTS_KEY = "cw.mock.checkouts";
const checkouts = {
  all(): Record<string, MockCheckout> {
    try {
      return JSON.parse(globalThis.localStorage?.getItem(CHECKOUTS_KEY) ?? "{}") as Record<string, MockCheckout>;
    } catch {
      return {};
    }
  },
  get(id: string): MockCheckout | undefined {
    return this.all()[id];
  },
  set(id: string, value: MockCheckout) {
    try {
      globalThis.localStorage?.setItem(CHECKOUTS_KEY, JSON.stringify({ ...this.all(), [id]: value }));
    } catch {
      /* private mode: the session is lost on reload */
    }
  },
};

export const handlers = [
  http.get(url("/health"), () => json({ status: "ok", version: "mock" })),

  // auth
  http.post(url("/auth/register"), async ({ request }) => {
    const body = (await request.json()) as { email?: string; password?: string };
    const errors: FieldError[] = [];
    if (!body.email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(body.email))
      errors.push({ pointer: "/email", code: "invalid_format", message: "Enter a valid email address." });
    if (!body.password || body.password.length < 10) errors.push({ pointer: "/password", code: "too_short", message: "Use at least 10 characters." });
    if (errors.length) return validation(errors);
    const email = body.email!.toLowerCase();
    if (!db().users.some((u) => u.email === email)) {
      db().users.push({ id: mockId("usr"), email, password: body.password!, email_verified: false, is_admin: false, workspace_id: null });
    }
    db().verifyTokens[mockVerifyToken(email)] = email;
    save();
    await delay(250);
    return json({ status: "verification_sent" }, 202);
  }),

  http.post(url("/auth/verify-email"), async ({ request }) => {
    const { token_hash } = (await request.json()) as { token_hash: string };
    const email = db().verifyTokens[token_hash];
    const user = db().users.find((u) => u.email === email);
    if (!email || !user || token_hash === EXPIRED_TOKEN) return problem(400, "link_invalid", "Link invalid, used or expired");
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
    if (f && f.count >= MAX_FAILED_SIGN_INS && Date.now() - f.first < FAILED_SIGN_IN_WINDOW_MS) {
      return problem(429, "too_many_attempts", "Too many sign-in attempts", {
        retry_after_s: Math.ceil((f.first + FAILED_SIGN_IN_WINDOW_MS - Date.now()) / 1000),
      });
    }
    if (key.includes(UNVERIFIED_MARKER)) return problem(403, "email_unverified", "Email not verified");
    const user = db().users.find((u) => u.email === key);
    if (!user || user.password !== password) {
      const prev = f && Date.now() - f.first < FAILED_SIGN_IN_WINDOW_MS ? f : { count: 0, first: Date.now() };
      db().failures[key] = { count: prev.count + 1, first: prev.first };
      save();
      return problem(401, "invalid_credentials", "Wrong email or password");
    }
    if (!user.email_verified) return problem(403, "email_unverified", "Email not verified");
    delete db().failures[key];
    return json<Session>(issueSession(user));
  }),

  // "Continue with Google": the mock skips Google and sends the browser straight to the callback.
  // The state is stateless (a page load between start and complete would lose module memory).
  http.get(url("/auth/config"), () => json({ google_signin: true })),

  http.post(url("/auth/google/start"), () => {
    const callback = new URL("/auth/google/callback", globalThis.location?.origin ?? "http://localhost");
    callback.search = new URLSearchParams({ code: "mock-google-code", state: `${MOCK_GOOGLE_STATE}${mockId("st")}` }).toString();
    return json({ authorization_url: callback.toString() });
  }),

  http.post(url("/auth/google/complete"), async ({ request }) => {
    const { code = "", state = "" } = (await request.json()) as { code?: string; state?: string };
    await delay(300);
    if (!state.startsWith(MOCK_GOOGLE_STATE) || code !== "mock-google-code") {
      return problem(400, "oauth_state_invalid", "Google sign-in expired");
    }
    let user = db().users.find((u) => u.email === MOCK_GOOGLE_EMAIL);
    if (!user) {
      user = { id: mockId("usr"), email: MOCK_GOOGLE_EMAIL, password: mockId("pw"), email_verified: true, is_admin: false, workspace_id: null };
      db().users.push(user);
    }
    user.email_verified = true;
    bootstrapWorkspace(user);
    save();
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
      db().resetTokens[mockResetToken(key)] = { email: key, used: false, expires: Date.now() + 3_600_000 };
      save();
    }
    await delay(250);
    return new HttpResponse(null, { status: 202 });
  }),

  http.post(url("/auth/password-reset/confirm"), async ({ request }) => {
    const { token_hash, new_password = "" } = (await request.json()) as { token_hash: string; new_password?: string };
    const t = db().resetTokens[token_hash];
    if (!t || t.used || t.expires < Date.now() || token_hash === EXPIRED_TOKEN) return problem(400, "link_invalid", "Link invalid, used or expired");
    if (new_password.length < 10) return validation([{ pointer: "/new_password", code: "too_short", message: "Use at least 10 characters." }]);
    const user = db().users.find((u) => u.email === t.email);
    if (user) user.password = new_password;
    t.used = true;
    save();
    return new HttpResponse(null, { status: 204 });
  }),

  // workspaces
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
      else if (body.name.length > 80) errors.push({ pointer: "/name", code: "too_long", message: "Keep the name to 80 characters or fewer." });
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

  // preferences (013)
  http.get(url("/me/preferences"), ({ request }) => {
    const user = currentUser(request);
    if (!user?.workspace_id) return unauthorized();
    return json<Preferences>(preferencesOf(user.id));
  }),

  http.patch(url("/me/preferences"), async ({ request }) => {
    const user = currentUser(request);
    if (!user?.workspace_id) return unauthorized();
    const body = (await request.json()) as { onboarding?: { status?: unknown; step?: unknown } } | null;
    const o = body?.onboarding;
    const errors: FieldError[] = [];
    if (!o || typeof o !== "object" || (!("status" in o) && !("step" in o)))
      errors.push({ pointer: "/onboarding", code: "required", message: "Send status, step or both." });
    else {
      if ("status" in o && !ONBOARDING_STATUSES.includes(o.status as OnboardingStatus))
        errors.push({ pointer: "/onboarding/status", code: "invalid_choice", message: "Choose a known status." });
      if ("step" in o && o.step !== null && (typeof o.step !== "string" || !/^[a-z][a-z0-9_-]{0,39}$/.test(o.step)))
        errors.push({ pointer: "/onboarding/step", code: "invalid_format", message: "Use a step id." });
    }
    if (errors.length) return validation(errors);
    const current = preferencesOf(user.id).onboarding;
    const next: Preferences = {
      onboarding: {
        status: "status" in o! ? (o!.status as OnboardingStatus) : current.status,
        step: "step" in o! ? (o!.step as string | null) : current.step,
        updated_at: new Date().toISOString(),
      },
    };
    (db().preferences ??= {})[user.id] = next;
    save();
    return json<Preferences>(next);
  }),

  // billing
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
    await delay(400);
    const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost:5180";
    const id = `cs_test_fake_mock${Date.now().toString(36)}`;
    checkouts.set(id, { workspace_id: user.workspace_id, amount: check.normalized, status: "pending" });
    return json<CheckoutSession>({ checkout_url: `${origin}/checkout/${id}`, expires_at: new Date(Date.now() + 30 * 60_000).toISOString() }, 201);
  }),

  // --- test checkout (the API's /dev/fake-checkout in STRIPE_MODE=fake) ----
  http.get(url("/dev/fake-checkout/:id"), ({ params }) => {
    const c = checkouts.get(String(params.id));
    if (!c) return json({ type: "about:blank", title: "Not found", status: 404, code: "not_found" }, 404);
    const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost:5180";
    return json({
      id: params.id,
      amount_usd: Number(c.amount).toFixed(2),
      status: c.status,
      workspace_name: "Halcyon Dental Group",
      success_url: `${origin}/billing?checkout=success`,
      cancel_url: `${origin}/billing?checkout=canceled`,
      test_cards: TEST_CARDS,
    });
  }),

  http.post(url("/dev/fake-checkout/:id/pay"), async ({ params, request }) => {
    const c = checkouts.get(String(params.id));
    if (!c) return json({ type: "about:blank", title: "Not found", status: 404, code: "not_found" }, 404);
    const { card_number = "" } = (await request.json()) as { card_number?: string };
    await delay(900);
    const outcome = TEST_CARDS.find((t) => t.number === card_number)?.outcome ?? "card_declined";
    if (outcome !== "succeeded") {
      const detail = `${DECLINES[outcome]}${TEST_CARDS.some((t) => t.number === card_number) ? "" : " This is a test checkout: use one of the test cards."}`;
      return json({ type: "about:blank", title: "Payment declined", status: 402, code: outcome, detail }, 402);
    }
    if (c.status === "pending") {
      checkouts.set(String(params.id), { ...c, status: "completed" });
      db().pending.push({ workspace_id: c.workspace_id, amount: c.amount, credit_at: Date.now() + 1500 });
      save();
    }
    const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost:5180";
    return json({ status: "paid", redirect_url: `${origin}/billing?checkout=success` });
  }),

  http.post(url("/dev/fake-checkout/:id/cancel"), () => {
    const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost:5180";
    return json({ status: "canceled", redirect_url: `${origin}/billing?checkout=canceled` });
  }),

  http.get(url("/billing/transactions"), async ({ request }) => {
    const user = currentUser(request);
    if (!user?.workspace_id) return unauthorized();
    settlePending();
    const q = new URL(request.url).searchParams;
    const type = q.get("type");
    const rows = db()
      .transactions.filter((t) => t.workspace_id === user.workspace_id && (!type || t.type === type))
      .slice()
      .reverse();
    await delay(180);
    return json(
      page(
        rows.map(({ workspace_id: _ws, ...t }): Transaction => t),
        q,
      ),
    );
  }),

  http.get(url("/billing/transactions/:transaction_id"), ({ request, params }) => {
    const user = currentUser(request);
    if (!user?.workspace_id) return unauthorized();
    const id = String(params.transaction_id);
    if (id === FAILING_TRANSACTION_ID) return problem(500, "internal", "Something went wrong", { trace_id: "4f1c9e0a7b2d4e83a6c15d0f9b7e2a41" });
    if (!/^txn_[0-9A-HJKMNP-TV-Z]{26}$/.test(id)) return problem(404, "not_found", "Not found");
    const t = db().transactions.find((x) => x.id === id && x.workspace_id === user.workspace_id);
    if (!t) return problem(404, "not_found", "Not found");
    const { workspace_id: _ws, ...rest } = t;
    return json<Transaction>(rest);
  }),

  // --- home page playground (the call itself uses the scripted mock driver) ---
  http.get(url("/public/demo"), () => json({ agents: ["clinic", "roadside", "loan"] })),

  // pricing
  http.get(url("/pricing/catalog"), () => json(catalogCurrent satisfies Catalog, 200, { "cache-control": "public, max-age=300" })),

  http.post(url("/pricing/quote"), async ({ request }) => {
    const body = (await request.json()) as QuoteRequest;
    if (!body?.components?.stt || !body.components.llm || !body.components.tts)
      return validation([{ pointer: "/components", code: "required", message: "Choose speech-to-text, model and voice." }]);
    await delay(60);
    const q = priceQuote(catalogCurrent as Parameters<typeof priceQuote>[0], body.components, body.usage);
    return json<Quote>(q as Quote);
  }),

  // usage
  http.get(url("/usage"), async ({ request }) => {
    const user = currentUser(request);
    if (!user?.workspace_id) return unauthorized();
    const q = new URL(request.url).searchParams;
    const to = q.get("to") ?? today();
    const from = q.get("from") ?? addDays(to, -30);
    if (from > to) return validation([{ pointer: "/to", code: "out_of_range", message: "The end date must be on or after the start date." }]);
    const days = (Date.parse(to) - Date.parse(from)) / 86_400_000 + 1;
    if (days > MAX_USAGE_DAYS)
      return validation([{ pointer: "/from", code: "out_of_range", message: `The window can cover at most ${MAX_USAGE_DAYS} days.` }]);
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
