/** Display helpers shared by the call list, the call drawer, compare and the dashboard. */
import type { CallStatus, CostView, Sentiment } from "../../api/calls";
import type { CostBreakdown } from "../../api/types";
import type { Tone } from "../../components";
import { formatUsd } from "../../lib/money";

/** 271 -> "4:31"; 3725 -> "1:02:05". */
export function mss(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${rest}` : `${m}:${rest}`;
}

/** Talk time for KPIs: "12h 04m", "38m 10s", "45s". */
export function talkTime(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${s}s`;
}

/** Dollars from a JSON number (the calls contract sends numbers): 0.477 -> "$0.477". */
export function usd(value: number | null | undefined, places = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  return formatUsd(value.toFixed(6), { places });
}

export function ms(value: number | null | undefined): string {
  return value === null || value === undefined ? "n/a" : `${Math.round(value).toLocaleString()} ms`;
}

/** Turn latency tone: under a second reads well on the phone, over 1.6 s feels slow. */
export function latencyTone(value: number | null | undefined): Tone {
  if (value === null || value === undefined) return "neutral";
  if (value <= 1000) return "success";
  if (value <= 1600) return "warning";
  return "danger";
}

export const STATUS_TONES: Record<CallStatus, Tone> = {
  queued: "neutral",
  ringing: "accent",
  in_progress: "accent",
  ended: "neutral",
  processing: "accent",
  completed: "success",
  failed: "danger",
  no_answer: "warning",
  busy: "warning",
  voicemail: "neutral",
};

export const SENTIMENT_TONES: Record<Sentiment, Tone> = {
  positive: "success",
  neutral: "neutral",
  negative: "danger",
  unknown: "neutral",
};

const dateTime = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const dateTimeLong = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

export const when = (iso: string) => dateTime.format(new Date(iso));
export const whenLong = (iso: string) => dateTimeLong.format(new Date(iso));

/** "2 min ago", "3 h ago", else the date. */
export function relative(iso: string, now = Date.now()): string {
  const diff = Math.max(0, now - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return when(iso);
}

/** "+1 555 123 4567" style spacing for display only; filters always send what was typed. */
export function phone(value: string | null | undefined): string {
  if (!value) return "";
  const m = /^\+1(\d{3})(\d{3})(\d{4})$/.exec(value);
  return m ? `+1 ${m[1]} ${m[2]} ${m[3]}` : value;
}

/**
 * The 006 cost view in the shape of 001's receipt (`CostBreakdownCard`): money as decimal
 * strings, the surcharge and its multiplier on the line it belongs to. Meters are not part of the
 * call view, so the receipt shows the multiplier without the meter detail.
 */
export function costViewToBreakdown(view: CostView): CostBreakdown {
  const surcharges = new Map(view.surcharges.map((s) => [s.component, s]));
  const dec = (n: number) => n.toFixed(6);
  return {
    call_id: null,
    catalog_version: Number(view.catalog_version) || 0,
    duration_ms: view.header.duration_s * 1000,
    billed_seconds: view.header.duration_s,
    duration_minutes: dec(view.header.billed_minutes),
    total_usd: dec(view.header.total_usd),
    lines: view.lines.map((l) => {
      const s = surcharges.get(l.component as "llm" | "tts");
      return {
        component: l.component,
        provider: l.provider ?? "",
        model: l.model ?? null,
        rate_per_min_usd: dec(l.rate_per_min_usd),
        billed_minutes: dec(l.billed_minutes),
        cost_usd: dec(l.cost_usd),
        surcharge_usd: dec(s?.surcharge_usd ?? 0),
        bundle_multiplier: (s?.multiplier ?? 1).toFixed(2),
        meters: [],
      };
    }),
  } as unknown as CostBreakdown;
}
