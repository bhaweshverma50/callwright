/** Call-specific display helpers: latency tone and the call cost view as a receipt. */
import type { CostView } from "../../api/calls";
import type { CostBreakdown } from "../../api/types";
import type { Tone } from "../../components";

/** Turn latency tone: under a second reads well on the phone, over 1.6 s feels slow. */
export function latencyTone(value: number | null | undefined): Tone {
  if (value === null || value === undefined) return "neutral";
  if (value <= 1000) return "success";
  if (value <= 1600) return "warning";
  return "danger";
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
