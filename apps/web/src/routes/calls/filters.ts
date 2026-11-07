/**
 * Call History URL state (FR-005, FR-036 to FR-038): sort, filters, page and page size live in the
 * address so a view can be shared. Unknown values are dropped (with a notice), every applied
 * filter is one chip, and "Any" is the absence of a filter. The API query is built with
 * URLSearchParams so a leading plus or a space reaches the server unchanged.
 */
import type { CallOrigin, CallStatus, Channel, DisconnectReason, EvalStatus, Sentiment } from "../../api/calls";
import { isAgentId } from "../../lib/paths";

export const STATUS_LABELS: Record<CallStatus, string> = {
  queued: "Queued",
  ringing: "Ringing",
  in_progress: "In progress",
  ended: "Ended",
  processing: "Processing",
  completed: "Completed",
  failed: "Failed",
  no_answer: "No answer",
  busy: "Busy",
  voicemail: "Voicemail",
};
export const CHANNEL_LABELS: Record<Channel, string> = {
  web: "Web",
  sip_inbound: "Inbound phone",
  sip_outbound: "Outbound phone",
  whatsapp: "WhatsApp",
};
export const REASON_LABELS: Record<DisconnectReason, string> = {
  user_hangup: "Caller hung up",
  agent_hangup: "Agent ended",
  call_transfer: "Transferred",
  voicemail_reached: "Voicemail reached",
  inactivity: "Silence timeout",
  max_duration_reached: "Max duration",
  error: "Error",
  concurrency_limit: "Concurrency limit",
  insufficient_credit: "Out of credit",
};
export const SENTIMENT_LABELS: Record<Sentiment, string> = {
  positive: "Positive",
  neutral: "Neutral",
  negative: "Negative",
  unknown: "Unknown",
};
export const ORIGIN_LABELS: Record<CallOrigin, string> = { live: "Live", test: "Test", simulation: "Simulated" };
export const LABEL_LABELS = { good: "Good", bad: "Bad", unannotated: "Unannotated" } as const;
export const EVAL_LABELS: Record<EvalStatus, string> = {
  not_evaluated: "Not evaluated",
  running: "Running",
  passed: "Passed",
  failed: "Failed",
  error: "Error",
};

export type OwnLabel = keyof typeof LABEL_LABELS;
export type SortKey = "started_at" | "duration_s" | "cost_usd" | "latency_avg_ms";
export const SORTS: SortKey[] = ["started_at", "duration_s", "cost_usd", "latency_avg_ms"];
export const PAGE_SIZES = [10, 20, 50, 100] as const;
export const DEFAULT_ORIGINS: CallOrigin[] = ["live", "test"];

export interface CallFilters {
  status: CallStatus[];
  channel: Channel[];
  disconnect_reason: DisconnectReason[];
  sentiment: Sentiment[];
  agent_id: string[];
  label: OwnLabel[];
  eval_status: EvalStatus[];
  origin: CallOrigin[];
  call_id: string;
  from_number: string;
  to_number: string;
  start_date: string;
  end_date: string;
}

export interface ListState {
  filters: CallFilters;
  sort: SortKey;
  order: "asc" | "desc";
  page: number;
  pageSize: number;
}

export const MULTI_KEYS = ["status", "channel", "disconnect_reason", "sentiment", "agent_id", "label", "eval_status", "origin"] as const;
export const TEXT_KEYS = ["call_id", "from_number", "to_number", "start_date", "end_date"] as const;
export type MultiKey = (typeof MULTI_KEYS)[number];
export type TextKey = (typeof TEXT_KEYS)[number];

const ALLOWED: Record<Exclude<MultiKey, "agent_id">, readonly string[]> = {
  status: Object.keys(STATUS_LABELS),
  channel: Object.keys(CHANNEL_LABELS),
  disconnect_reason: Object.keys(REASON_LABELS),
  sentiment: Object.keys(SENTIMENT_LABELS),
  label: Object.keys(LABEL_LABELS),
  eval_status: Object.keys(EVAL_LABELS),
  origin: Object.keys(ORIGIN_LABELS),
};
const DATE = /^\d{4}-\d{2}-\d{2}$/;

export const emptyFilters = (): CallFilters => ({
  status: [],
  channel: [],
  disconnect_reason: [],
  sentiment: [],
  agent_id: [],
  label: [],
  eval_status: [],
  origin: [...DEFAULT_ORIGINS],
  call_id: "",
  from_number: "",
  to_number: "",
  start_date: "",
  end_date: "",
});

/** Reads the address. `dropped` lists values that were ignored because they are not known. */
export function parseListState(params: URLSearchParams): { state: ListState; dropped: string[] } {
  const filters = emptyFilters();
  const dropped: string[] = [];
  for (const key of MULTI_KEYS) {
    const raw = params.get(key);
    if (raw === null) continue;
    const values = raw
      .split(",")
      .map((v) => v.trim())
      .filter(Boolean);
    const ok = values.filter((v) => (key === "agent_id" ? isAgentId(v) : ALLOWED[key].includes(v)));
    dropped.push(...values.filter((v) => !ok.includes(v)));
    const unique = [...new Set(ok)];
    if (key === "origin") filters.origin = unique.length ? (unique as CallOrigin[]) : [...DEFAULT_ORIGINS];
    else (filters[key] as string[]) = unique;
  }
  for (const key of TEXT_KEYS) {
    const raw = (params.get(key) ?? "").trim();
    if (!raw) continue;
    if ((key === "start_date" || key === "end_date") && !DATE.test(raw)) {
      dropped.push(raw);
      continue;
    }
    filters[key] = raw;
  }
  const sortRaw = params.get("sort");
  const sort = SORTS.includes(sortRaw as SortKey) ? (sortRaw as SortKey) : "started_at";
  const order = params.get("order") === "asc" ? "asc" : "desc";
  const page = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);
  const sizeRaw = Number.parseInt(params.get("page_size") ?? "20", 10);
  const pageSize = (PAGE_SIZES as readonly number[]).includes(sizeRaw) ? sizeRaw : 20;
  return { state: { filters, sort, order, page, pageSize }, dropped };
}

const sameOrigins = (o: CallOrigin[]) => o.length === DEFAULT_ORIGINS.length && DEFAULT_ORIGINS.every((d) => o.includes(d));

/** The address for a state: defaults are left out so the plain view stays `/calls`. */
export function toSearchParams(state: ListState, keep?: URLSearchParams): URLSearchParams {
  const out = new URLSearchParams();
  const call = keep?.get("call");
  if (call) out.set("call", call);
  const f = state.filters;
  for (const key of MULTI_KEYS) {
    if (key === "origin") {
      if (!sameOrigins(f.origin)) out.set("origin", f.origin.join(","));
    } else if (f[key].length) out.set(key, f[key].join(","));
  }
  for (const key of TEXT_KEYS) if (f[key]) out.set(key, f[key]);
  if (state.sort !== "started_at") out.set("sort", state.sort);
  if (state.order !== "desc") out.set("order", state.order);
  if (state.page > 1) out.set("page", String(state.page));
  if (state.pageSize !== 20) out.set("page_size", String(state.pageSize));
  return out;
}

/** The API query for the list (dates go as calendar dates plus the viewer's timezone). */
export function toApiQuery(state: ListState, tz: string): URLSearchParams {
  const q = new URLSearchParams();
  q.set("page", String(state.page));
  q.set("page_size", String(state.pageSize));
  q.set("sort", state.sort);
  q.set("order", state.order);
  const f = state.filters;
  for (const key of MULTI_KEYS) if (f[key].length) q.set(key, f[key].join(","));
  if (f.call_id.length >= 8) q.set("call_id", f.call_id);
  if (f.from_number) q.set("from_number", f.from_number);
  if (f.to_number) q.set("to_number", f.to_number);
  if (f.start_date) q.set("start_date", f.start_date);
  if (f.end_date) q.set("end_date", f.end_date);
  if (f.start_date || f.end_date) q.set("tz", tz);
  return q;
}

export interface FilterChip {
  key: string;
  label: string;
  remove: (f: CallFilters) => CallFilters;
}

function listLabel(values: string[], names: (v: string) => string): string {
  if (values.length <= 2) return values.map(names).join(" or ");
  return `${names(values[0]!)} and ${values.length - 1} more`;
}

/** One chip per applied filter (FR-036); the filter badge equals the chip count. */
export function filterChips(f: CallFilters, agentName: (id: string) => string): FilterChip[] {
  const chips: FilterChip[] = [];
  const multi: [MultiKey, string, (v: string) => string][] = [
    ["status", "Status", (v) => STATUS_LABELS[v as CallStatus] ?? v],
    ["channel", "Channel", (v) => CHANNEL_LABELS[v as Channel] ?? v],
    ["disconnect_reason", "Ended by", (v) => REASON_LABELS[v as DisconnectReason] ?? v],
    ["sentiment", "Sentiment", (v) => SENTIMENT_LABELS[v as Sentiment] ?? v],
    ["agent_id", "Agent", agentName],
    ["label", "Your label", (v) => LABEL_LABELS[v as OwnLabel] ?? v],
    ["eval_status", "Evaluation", (v) => EVAL_LABELS[v as EvalStatus] ?? v],
  ];
  for (const [key, title, names] of multi) {
    const values = f[key] as string[];
    if (values.length) chips.push({ key, label: `${title}: ${listLabel(values, names)}`, remove: (x) => ({ ...x, [key]: [] }) });
  }
  if (!sameOrigins(f.origin)) {
    chips.push({
      key: "origin",
      label: `Origin: ${listLabel(f.origin, (v) => ORIGIN_LABELS[v as CallOrigin])}`,
      remove: (x) => ({ ...x, origin: [...DEFAULT_ORIGINS] }),
    });
  }
  if (f.call_id) chips.push({ key: "call_id", label: `Call ID starts ${f.call_id}`, remove: (x) => ({ ...x, call_id: "" }) });
  if (f.from_number) chips.push({ key: "from_number", label: `From ${f.from_number}`, remove: (x) => ({ ...x, from_number: "" }) });
  if (f.to_number) chips.push({ key: "to_number", label: `To ${f.to_number}`, remove: (x) => ({ ...x, to_number: "" }) });
  if (f.start_date || f.end_date) {
    const label =
      f.start_date && f.end_date
        ? f.start_date === f.end_date
          ? `On ${f.start_date}`
          : `${f.start_date} to ${f.end_date}`
        : f.start_date
          ? `From ${f.start_date}`
          : `Until ${f.end_date}`;
    chips.push({ key: "dates", label, remove: (x) => ({ ...x, start_date: "", end_date: "" }) });
  }
  return chips;
}

export function viewerTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}
