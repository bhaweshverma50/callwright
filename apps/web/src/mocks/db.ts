/**
 * In-memory state behind the mock API. In the browser it is persisted to localStorage so a
 * reload keeps what you did (settings saves, top-ups); in tests it resets after every test.
 * Shapes are the contract types, so the mock cannot drift from the specs silently.
 */
import type { Transaction, TransactionType, Workspace, CostBreakdown } from "../api/types";
import { priceQuote } from "../lib/pricing";
import { microsToDecimal, toMicros } from "../lib/money";
import { catalogV1 } from "./catalog";

const ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
let counter = 0;
/** Deterministic ULID-shaped id: prefix + 26 Crockford base32 chars. */
export function mockId(prefix: string): string {
  counter = (counter + 1) % 65536;
  let n = BigInt(Date.now()) * 65536n + BigInt(counter);
  let s = "";
  for (let i = 0; i < 26; i++) {
    s = ALPHABET[Number(n % 32n)] + s;
    n /= 32n;
  }
  return `${prefix}_${s}`;
}

export interface MockUser {
  id: string;
  email: string;
  password: string;
  email_verified: boolean;
  is_admin: boolean;
  workspace_id: string | null;
}
export interface UsageEvent {
  workspace_id: string;
  feature_key: string;
  at: string;
  raw: string;
  billable: string;
}
export interface PendingTopUp {
  workspace_id: string;
  amount: string;
  credit_at: number;
}
export interface MockState {
  users: MockUser[];
  workspaces: Workspace[];
  transactions: (Transaction & { workspace_id: string })[];
  pending: PendingTopUp[];
  usage: UsageEvent[];
  sessions: Record<string, string>; // token -> user id (access and refresh)
  failures: Record<string, { count: number; first: number }>;
  verifyTokens: Record<string, string>; // token_hash -> email
  resetTokens: Record<string, { email: string; used: boolean; expires: number }>;
}

export const DEMO_EMAIL = "ops@halcyon-dental.com";
export const DEMO_PASSWORD = "correct-horse-9";

const DAY = 86_400_000;

function iso(ms: number) {
  return new Date(ms).toISOString();
}

function seed(): MockState {
  const now = Date.now();
  const ws: Workspace = {
    id: mockId("ws"),
    name: "Halcyon Dental Group",
    concurrency_limit: 5,
    recording_default: true,
    created_at: iso(now - 41 * DAY),
  };
  const user: MockUser = {
    id: mockId("usr"),
    email: DEMO_EMAIL,
    password: DEMO_PASSWORD,
    email_verified: true,
    is_admin: false,
    workspace_id: ws.id,
  };
  const state: MockState = {
    users: [user],
    workspaces: [ws],
    transactions: [],
    pending: [],
    usage: [],
    sessions: {},
    failures: {},
    verifyTokens: {},
    resetTokens: {},
  };

  const post = (type: TransactionType, amount: string, at: number, description: string, extra: Partial<Transaction> = {}) =>
    appendTransaction(state, ws.id, type, amount, description, at, extra);

  post("trial_grant", "5.000000", now - 41 * DAY, "Trial credit");
  post("top_up", "100.000000", now - 38 * DAY, "Top-up via card ending 4242");

  // A month of calls with realistic, uneven usage. Some calls run past the LLM bundle.
  const durations = [271, 94, 412, 33, 188, 156, 61, 523, 247, 12, 305, 199, 77, 390, 141, 228, 88, 466, 174, 59, 312, 205];
  durations.forEach((sec, i) => {
    const at = now - (36 - i * 1.6) * DAY - (i % 5) * 3_600_000;
    const heavy = i % 4 === 0;
    const usage = {
      duration_ms: sec * 1000 + (i % 3) * 350,
      llm_input_tokens: Math.round(sec * (heavy ? 378 : 211)),
      llm_output_tokens: Math.round(sec * 2.6),
      tts_chars: Math.round(sec * 9.4),
    };
    const quote = priceQuote(
      catalogV1,
      {
        stt: { provider: "deepgram", model: "nova-3" },
        llm: { provider: i % 3 === 0 ? "openai" : "azure_openai", model: i % 6 === 0 ? "gpt-5.1" : "gpt-5-mini" },
        tts: { provider: i % 2 ? "cartesia" : "elevenlabs", model: i % 2 ? "sonic-3" : "eleven_flash_v2_5" },
        nc: i % 3 === 1 ? { provider: "sanas", model: "vi" } : null,
      },
      usage,
    );
    const call_id = mockId("call");
    const breakdown: CostBreakdown = { ...quote.call!, call_id };
    const total = breakdown.total_usd;
    post("call_charge", `-${total}`, at, `Call ${formatDuration(sec)} with Front desk agent`, {
      call_id,
      cost_breakdown: breakdown,
    });
    state.usage.push({ workspace_id: ws.id, feature_key: "calls", at: iso(at), raw: total, billable: total });
    if (i % 3 === 0) {
      const evalAt = at + 120_000;
      post("feature_charge", "-0.004000", evalAt, "Evaluator: intent fulfillment", { feature_key: "eval.intent_fulfillment" });
      state.usage.push({ workspace_id: ws.id, feature_key: "eval.intent_fulfillment", at: iso(evalAt), raw: "0.003100", billable: "0.004000" });
    }
  });
  post("feature_charge", "-0.020000", now - 9 * DAY, "Prompt generation", { feature_key: "prompt_generation" });
  state.usage.push({ workspace_id: ws.id, feature_key: "prompt_generation", at: iso(now - 9 * DAY), raw: "0.014000", billable: "0.020000" });
  post("adjustment", "-1.250000", now - 5 * DAY, "Dispute on top-up, card ending 4242");
  // Internal zero-amount charge: usage row only, no ledger row (FR-023).
  state.usage.push({ workspace_id: ws.id, feature_key: "post_call_analysis", at: iso(now - 4 * DAY), raw: "0.000000", billable: "0.000000" });
  return state;
}

function formatDuration(sec: number) {
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}

export function balanceOf(state: MockState, workspaceId: string): bigint {
  return state.transactions
    .filter((t) => t.workspace_id === workspaceId)
    .reduce((s, t) => s + (toMicros(t.amount_usd) ?? 0n), 0n);
}

export function appendTransaction(
  state: MockState,
  workspaceId: string,
  type: TransactionType,
  amount: string,
  description: string,
  at = Date.now(),
  extra: Partial<Transaction> = {},
): Transaction {
  const after = balanceOf(state, workspaceId) + (toMicros(amount) ?? 0n);
  const txn: Transaction & { workspace_id: string } = {
    id: mockId("txn"),
    type,
    amount_usd: microsToDecimal(toMicros(amount) ?? 0n, 6),
    balance_after_usd: microsToDecimal(after, 6),
    call_id: null,
    feature_key: null,
    description,
    created_at: iso(at),
    cost_breakdown: null,
    ...extra,
    workspace_id: workspaceId,
  };
  state.transactions.push(txn);
  return txn;
}

// --- persistence -----------------------------------------------------------

const STORAGE_KEY = "cw.mockdb.v1";
let persist = false;
let state: MockState = seed();

export function enablePersistence() {
  persist = true;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) state = JSON.parse(raw) as MockState;
    else save();
  } catch {
    /* storage blocked: keep the in-memory seed */
  }
}

export function db(): MockState {
  return state;
}

export function save() {
  if (!persist) return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* ignore */
  }
}

export function resetMockDb() {
  state = seed();
  save();
}
