/** Display formatting shared by every page: durations, dates, rates, money from JSON numbers, counts and ids. */
import { formatUsd } from "./money";

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

/** Dollars from a JSON number (several contracts send numbers): 0.477 -> "$0.477". */
export function usd(value: number | null | undefined, places = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  return formatUsd(value.toFixed(6), { places });
}

/** Run and batch costs: four decimals under ten cents so a fraction of a cent still shows, else two. */
export function costUsd(value: number | null | undefined): string {
  if (value === null || value === undefined) return "n/a";
  return usd(value, Math.abs(value) < 0.1 ? 4 : 2);
}

export function ms(value: number | null | undefined): string {
  return value === null || value === undefined ? "n/a" : `${Math.round(value).toLocaleString()} ms`;
}

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
const dateOnly = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" });
const calendarDay = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", timeZone: "UTC" });

export const when = (iso: string) => dateTime.format(new Date(iso));
export const whenLong = (iso: string) => dateTimeLong.format(new Date(iso));
export const dateLabel = (iso: string) => dateOnly.format(new Date(iso));
/** A calendar date ("2026-10-01") as "1 Oct", never shifted by the viewer's zone. */
export const dayLabel = (isoDate: string) => calendarDay.format(new Date(`${isoDate}T00:00:00Z`));

/** "just now", "5 min ago", "3 h ago", "2 days ago", else the date. */
export function timeAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const s = Math.max(0, now - Date.parse(iso)) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86_400) return `${Math.floor(s / 3600)} h ago`;
  const d = Math.floor(s / 86_400);
  if (d < 30) return `${d} ${d === 1 ? "day" : "days"} ago`;
  return dateLabel(iso);
}

/** 0.4 -> "40%", 0.405 -> "40.5%" (one decimal when there is one); `places` 0 gives whole percents. */
export function pct(rate: number | null | undefined, places = 1): string {
  if (rate === null || rate === undefined) return "n/a";
  const scale = 10 ** places;
  return `${Math.round(rate * 100 * scale) / scale}%`;
}

/** Percentage points, half away from zero to one decimal: 30 -> "+30.0 pp", -0.05 -> "-0.1 pp". */
export function pp(delta: number | null | undefined): string {
  if (delta === null || delta === undefined) return "n/a";
  const rounded = (Math.sign(delta) * Math.round(Math.abs(delta) * 10)) / 10;
  if (rounded === 0) return "0.0 pp";
  return `${rounded > 0 ? "+" : "-"}${Math.abs(rounded).toFixed(1)} pp`;
}

export const plural = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString()} ${n === 1 ? one : many}`;

/** call_01MOCKSIMCALL0000000000007 -> "call_01MO...000007": long ids keep both ends visible. */
export function shortId(id: string, head = 9, tail = 6): string {
  return id.length <= head + tail + 3 ? id : `${id.slice(0, head)}...${id.slice(-tail)}`;
}

/** "+1 555 123 4567" style spacing for display only; filters always send what was typed. */
export function phone(value: string | null | undefined): string {
  if (!value) return "";
  const m = /^\+1(\d{3})(\d{3})(\d{4})$/.exec(value);
  return m ? `+1 ${m[1]} ${m[2]} ${m[3]}` : value;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function viewerTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}
