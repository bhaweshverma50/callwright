/**
 * The 001 pricing rule in TypeScript for the mock API's quote endpoint. The API's
 * `pricing/engine.py` is the source of truth; this file mirrors it and is pinned by the same
 * reference-call test (SC-004).
 *
 * Rules (spec US3, research R1, R4):
 * - Duration is rounded up to the whole second; duration_minutes = billed_seconds / 60.
 * - For llm and tts, billed_minutes = max(duration_minutes, used / bundle_per_min) over meters.
 * - cost = rate x billed_minutes, rounded UP to $0.001 per line.
 * - surcharge = rate x (billed_minutes - duration_minutes), informational, 6 places.
 * - bundle_multiplier = billed_minutes / duration_minutes, 4 places.
 * All arithmetic is exact (BigInt rationals); nothing goes through floats.
 */
import { microsToDecimal, toMicros } from "../../lib/money";

export type Component = "stt" | "llm" | "tts" | "nc" | "platform";
export type BundleUnit = "llm_input_tokens" | "llm_output_tokens" | "tts_chars";

export interface EntryLike {
  component: Component;
  provider: string;
  model: string | null;
  label: string;
  rate_per_min_usd: string;
  bundles: { unit: BundleUnit; per_min: number }[];
}
export interface CatalogLike {
  version: number;
  entries: EntryLike[];
}
export interface Selection {
  provider: string;
  model?: string | null;
}
export interface Selections {
  stt: Selection;
  llm: Selection;
  tts: Selection;
  nc?: Selection | null;
}
export interface UsageMeters {
  duration_ms: number;
  llm_input_tokens?: number;
  llm_output_tokens?: number;
  tts_chars?: number;
}

export interface QuoteLineOut {
  component: Component;
  provider: string;
  model: string | null;
  label: string | null;
  status: "priced" | "unpriced";
  rate_per_min_usd: string | null;
  bundles: { unit: BundleUnit; per_min: number }[];
}
export interface MeterOut {
  unit: BundleUnit;
  used: number;
  bundle_per_min: number;
  included: string;
}
export interface CostLineOut {
  component: Component;
  provider: string;
  model: string | null;
  rate_per_min_usd: string;
  billed_minutes: string;
  cost_usd: string;
  surcharge_usd: string;
  bundle_multiplier: string;
  meters: MeterOut[];
}
export interface CostBreakdownOut {
  call_id?: string | null;
  catalog_version: number;
  duration_ms: number;
  billed_seconds: number;
  duration_minutes: string;
  lines: CostLineOut[];
  total_usd: string;
}
export interface QuoteOut {
  catalog_version: number;
  lines: QuoteLineOut[];
  per_minute_total_usd: string;
  complete: boolean;
  call?: CostBreakdownOut;
}

/** Exact lookup by (component, provider, model), then the provider row with model null. */
export function findEntry(catalog: CatalogLike, component: Component, sel: Selection): EntryLike | undefined {
  const model = sel.model ?? null;
  const rows = catalog.entries.filter((e) => e.component === component && e.provider === sel.provider);
  return rows.find((e) => e.model === model) ?? rows.find((e) => e.model === null);
}

/** A rational number n/d with d > 0. */
interface Ratio {
  n: bigint;
  d: bigint;
}
const gt = (a: Ratio, b: Ratio) => a.n * b.d > b.n * a.d;
const ceilDiv = (n: bigint, d: bigint) => (n <= 0n ? -(-n / d) : (n + d - 1n) / d);
const roundDiv = (n: bigint, d: bigint) => (n >= 0n ? (2n * n + d) / (2n * d) : -((2n * -n + d) / (2n * d)));
/** Ratio to a decimal string with `places` digits, half-up. */
function ratioToDecimal(r: Ratio, places: number): string {
  const scale = 10n ** BigInt(places);
  const v = roundDiv(r.n * scale, r.d);
  const neg = v < 0n;
  const abs = neg ? -v : v;
  return `${neg ? "-" : ""}${(abs / scale).toString()}.${(abs % scale).toString().padStart(places, "0")}`;
}

const METER_FIELD: Record<BundleUnit, keyof UsageMeters> = {
  llm_input_tokens: "llm_input_tokens",
  llm_output_tokens: "llm_output_tokens",
  tts_chars: "tts_chars",
};

function priceLine(entry: EntryLike, usage: UsageMeters, billedSeconds: bigint): CostLineOut {
  const rate = toMicros(entry.rate_per_min_usd) ?? 0n;
  const durMin: Ratio = { n: billedSeconds, d: 60n };
  let billed: Ratio = durMin;
  const meters: MeterOut[] = [];
  for (const b of entry.bundles) {
    const used = BigInt(Math.max(0, Math.floor(Number(usage[METER_FIELD[b.unit]] ?? 0))));
    const per = BigInt(b.per_min);
    const candidate: Ratio = { n: used, d: per };
    if (gt(candidate, billed)) billed = candidate;
    meters.push({
      unit: b.unit,
      used: Number(used),
      bundle_per_min: b.per_min,
      included: ratioToDecimal({ n: per * billedSeconds, d: 60n }, 6),
    });
  }
  // cost in micro-dollars = rate_micros * billed; ceil to 1000 micros ($0.001).
  const costMicros = ceilDiv(rate * billed.n, billed.d * 1000n) * 1000n;
  const surcharge: Ratio = { n: rate * (billed.n * durMin.d - durMin.n * billed.d), d: billed.d * durMin.d * 1_000_000n };
  const multiplier: Ratio = billedSeconds === 0n ? { n: 1n, d: 1n } : { n: billed.n * durMin.d, d: billed.d * durMin.n };
  return {
    component: entry.component,
    provider: entry.provider,
    model: entry.model,
    rate_per_min_usd: entry.rate_per_min_usd,
    billed_minutes: ratioToDecimal(billed, 6),
    cost_usd: microsToDecimal(costMicros, 6),
    surcharge_usd: ratioToDecimal(surcharge, 6),
    bundle_multiplier: ratioToDecimal(multiplier, 4),
    meters,
  };
}

export function priceQuote(catalog: CatalogLike, selections: Selections, usage?: UsageMeters): QuoteOut {
  const wanted: [Component, Selection][] = [
    ["stt", selections.stt],
    ["llm", selections.llm],
    ["tts", selections.tts],
  ];
  if (selections.nc) wanted.push(["nc", selections.nc]);
  wanted.push(["platform", { provider: "callwright", model: null }]);

  const lines: QuoteLineOut[] = [];
  const entries: EntryLike[] = [];
  let totalMicros = 0n;
  for (const [component, sel] of wanted) {
    const entry = findEntry(catalog, component, sel);
    if (entry) {
      entries.push(entry);
      totalMicros += toMicros(entry.rate_per_min_usd) ?? 0n;
    }
    lines.push({
      component,
      provider: sel.provider,
      model: sel.model ?? null,
      label: entry?.label ?? null,
      status: entry ? "priced" : "unpriced",
      rate_per_min_usd: entry?.rate_per_min_usd ?? null,
      bundles: entry?.bundles ?? [],
    });
  }
  const quote: QuoteOut = {
    catalog_version: catalog.version,
    lines,
    per_minute_total_usd: microsToDecimal(totalMicros, 6),
    complete: lines.every((l) => l.status === "priced"),
  };
  if (usage) {
    const billedSeconds = BigInt(Math.ceil(Math.max(0, usage.duration_ms) / 1000));
    const costLines = entries.map((e) => priceLine(e, usage, billedSeconds));
    const total = costLines.reduce((s, l) => s + (toMicros(l.cost_usd) ?? 0n), 0n);
    quote.call = {
      call_id: null,
      catalog_version: catalog.version,
      duration_ms: usage.duration_ms,
      billed_seconds: Number(billedSeconds),
      duration_minutes: ratioToDecimal({ n: billedSeconds, d: 60n }, 6),
      lines: costLines,
      total_usd: microsToDecimal(total, 6),
    };
  }
  return quote;
}
