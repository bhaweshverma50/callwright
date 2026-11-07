import { bodyLimits } from "./contract.gen";
/**
 * Money helpers. The API sends USD as decimal strings with up to 6 fractional digits
 * (core.yaml MoneyUsd). Display never goes through floats for rounding decisions that matter;
 * amounts are formatted from the string with BigInt micro-dollars.
 */

const MICRO = 1_000_000n;

/** Parses "12.5", "-0.477000", "5" into micro-dollars. Returns null for anything else. */
export function toMicros(value: string): bigint | null {
  const m = /^(-)?(\d+)(?:\.(\d{1,6}))?$/.exec(value.trim());
  if (!m) return null;
  const [, neg, whole = "0", frac = ""] = m;
  const micros = BigInt(whole) * MICRO + BigInt(frac.padEnd(6, "0"));
  return neg ? -micros : micros;
}

/** Formats micro-dollars as a decimal string with `places` digits (half away from zero). */
export function microsToDecimal(micros: bigint, places = 6): string {
  const neg = micros < 0n;
  let abs = neg ? -micros : micros;
  const drop = 6 - places;
  if (drop > 0) {
    const unit = 10n ** BigInt(drop);
    abs = (abs + unit / 2n) / unit;
  }
  const scale = 10n ** BigInt(places);
  const whole = abs / scale;
  const frac = places > 0 ? "." + (abs % scale).toString().padStart(places, "0") : "";
  return `${neg && abs !== 0n ? "-" : ""}${whole.toString()}${frac}`;
}

function groupThousands(s: string): string {
  return s.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

export interface FormatOptions {
  /** Fractional digits to show. Balance uses 3 (charges move in $0.001 steps). */
  places?: number;
  /** Prefix "+" on positive values (ledger amounts). */
  signed?: boolean;
}

/** "-0.477000" -> "-$0.477"; "30" -> "$30.00" with places 2. */
export function formatUsd(value: string | bigint, { places = 2, signed = false }: FormatOptions = {}): string {
  const micros = typeof value === "bigint" ? value : toMicros(value);
  if (micros === null) return "n/a";
  const s = microsToDecimal(micros, places);
  const neg = s.startsWith("-");
  const body = neg ? s.slice(1) : s;
  const [w = "0", f] = body.split(".");
  const out = `$${groupThousands(w)}${f !== undefined ? "." + f : ""}`;
  if (neg) return `-${out}`;
  if (signed && micros > 0n) return `+${out}`;
  return out;
}

/** Cents per minute for compact rate display: "0.0085" -> "0.85¢". */
export function formatCentsPerMin(rate: string): string {
  const micros = toMicros(rate);
  if (micros === null) return "n/a";
  // 1 cent = 10_000 micros, so a hundredth of a cent is 100 micros.
  const hundredths = (micros + 50n) / 100n;
  return `${(hundredths / 100n).toString()}.${(hundredths % 100n).toString().padStart(2, "0")}¢`;
}

export type AmountCheck = { ok: true; micros: bigint; normalized: string } | { ok: false; reason: string };

const TOP_UP = bodyLimits["POST /billing/checkout-sessions"].amount_usd;
export const TOP_UP_MIN = toMicros(TOP_UP["x-minimum-usd"])!;
export const TOP_UP_MAX = toMicros(TOP_UP["x-maximum-usd"])!;
const whole = (micros: bigint) => formatUsd(micros, { places: 0 });

/**
 * Validates a custom top-up amount typed by the user (FR-008): within the contract's range, whole
 * cents. Accepts an optional leading "$" and thousands commas.
 */
export function checkTopUpAmount(input: string): AmountCheck {
  const cleaned = input.trim().replace(/^\$/, "").replace(/,/g, "");
  if (cleaned === "") return { ok: false, reason: `Enter an amount between ${whole(TOP_UP_MIN)} and ${whole(TOP_UP_MAX)}.` };
  if (!/^\d+(\.\d+)?$/.test(cleaned)) return { ok: false, reason: "Use numbers only, like 25 or 99.50." };
  const frac = cleaned.split(".")[1] ?? "";
  if (frac.length > 2) return { ok: false, reason: "Use whole cents: at most two digits after the point." };
  const micros = toMicros(cleaned);
  if (micros === null) return { ok: false, reason: "Use numbers only, like 25 or 99.50." };
  if (micros < TOP_UP_MIN) return { ok: false, reason: `The minimum top-up is ${whole(TOP_UP_MIN)}.` };
  if (micros > TOP_UP_MAX) return { ok: false, reason: `The maximum top-up is ${whole(TOP_UP_MAX)}. Contact sales for larger amounts.` };
  return { ok: true, micros, normalized: microsToDecimal(micros, 2) };
}
