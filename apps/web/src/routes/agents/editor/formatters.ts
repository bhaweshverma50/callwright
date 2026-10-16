/**
 * Display formatters for agent settings (T094, FR-042). Every slider label and number helper uses
 * these, driven by the catalog `controls` table, so a label always equals the value that will be
 * saved: 1,500 ms is "1.5 s", gain 1.0 is "100%", speed 1 is "1.0x".
 */
import type { ControlRange } from "../../../api/agents";

/** Whole seconds as "30 s", "1 min 30 s", "10 min". */
export function formatSeconds(total: number): string {
  if (!Number.isFinite(total)) return "";
  const neg = total < 0 ? "-" : "";
  const s = Math.abs(total);
  if (s < 60) return `${neg}${trim(s, 1)} s`;
  const m = Math.floor(s / 60);
  const rest = Math.round((s - m * 60) * 10) / 10;
  return `${neg}${m} min${rest ? ` ${trim(rest, 1)} s` : ""}`;
}

/** Milliseconds as seconds with at most one decimal ("1.5 s", "5 s", "2 min"). */
export function formatMs(ms: number): string {
  return formatSeconds(ms / 1000);
}

/** "1.0x", "1.25x" (one decimal unless the value needs two). */
export function formatMultiplier(v: number): string {
  return `${Number.isInteger(v * 10) ? v.toFixed(1) : v.toFixed(2)}x`;
}

/** Gain as a percent of normal loudness: 1.0 is 100%, 0.8 is 80%, 3.0 is 300%. */
export function formatPercentOfNormal(v: number): string {
  return `${Math.round(v * 100)}%`;
}

export function formatDecimal(v: number, places = 2): string {
  return v.toFixed(places);
}

function trim(n: number, places: number): string {
  return String(Math.round(n * 10 ** places) / 10 ** places);
}

/** The label for a control's value, by the catalog's display rule and unit. */
export function formatControl(c: Pick<ControlRange, "display" | "unit">, value: number): string {
  switch (c.display) {
    case "multiplier":
      return formatMultiplier(value);
    case "percent_of_normal":
      return formatPercentOfNormal(value);
    case "duration":
      return c.unit === "ms" ? formatMs(value) : formatSeconds(value);
    default:
      return formatDecimal(value);
  }
}

/** Rounds to the nearest step from min, without float noise (0.1 + 0.2 stays 0.3). */
export function snap(value: number, min: number, step: number): number {
  const n = Math.round((value - min) / step);
  const places = (String(step).split(".")[1] ?? "").length;
  return Number((min + n * step).toFixed(places));
}

/** Parses a typed number ("1.5", " 2 ", "-1"); null for anything else. */
export function parseNumber(text: string): number | null {
  const t = text.trim().replace(/,/g, "");
  if (!/^-?\d*(\.\d+)?$/.test(t) || t === "" || t === "-") return null;
  return Number(t);
}
