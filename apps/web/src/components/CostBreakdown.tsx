import { Lightning } from "@phosphor-icons/react";
import type { CostBreakdown as CostBreakdownT, CostLine } from "../api/types";
import { formatUsd, toMicros } from "../lib/money";
import { providerLabel } from "../lib/providers";
import { cn } from "./cn";
import { MoneyText } from "./Money";

export const COMPONENT_LABELS: Record<string, string> = {
  stt: "Speech to text",
  llm: "Language model",
  tts: "Text to speech",
  nc: "Noise cancellation",
  platform: "Platform",
  embedding: "Embeddings",
};

const UNIT_LABELS: Record<string, string> = {
  llm_input_tokens: "input tokens",
  llm_output_tokens: "output tokens",
  tts_chars: "characters",
};

function mss(seconds: number) {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/** Average per-minute price over the billed duration, 4 places: total / duration_minutes. */
function avgPerMinute(b: CostBreakdownT): string {
  const total = toMicros(b.total_usd) ?? 0n;
  if (b.billed_seconds === 0) return formatUsd(0n, { places: 4 });
  return formatUsd((total * 60n) / BigInt(b.billed_seconds), { places: 4 });
}

const hasSurcharge = (l: CostLine) => (toMicros(l.surcharge_usd) ?? 0n) > 0n;

/**
 * Itemised call cost (spec 001 US3, FR-011): header with duration, billed minutes and average
 * rate; one base line per component; then a surcharge block for every component whose usage ran
 * past its per-minute bundle, with the multiplier and the meter that caused it. Amber marks the
 * evidence (what pushed the price up), never a failure.
 */
export function CostBreakdownCard({ breakdown, className, title = "Cost breakdown" }: { breakdown: CostBreakdownT; className?: string; title?: string }) {
  const surcharged = breakdown.lines.filter(hasSurcharge);
  return (
    <section aria-label={title} className={cn("rounded-panel border border-line bg-surface", className)}>
      <header className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-line px-4 py-3">
        <h3 className="text-[13px] font-medium text-fg">{title}</h3>
        <dl className="flex gap-4 font-mono text-[11.5px] text-fg-3 tnum">
          <div className="flex gap-1.5">
            <dt className="sr-only">Duration</dt>
            <dd>{mss(breakdown.billed_seconds)}</dd>
          </div>
          <div className="flex gap-1.5">
            <dt className="sr-only">Billed minutes</dt>
            <dd>{Number(breakdown.duration_minutes).toFixed(2)}m</dd>
          </div>
          <div className="flex gap-1.5">
            <dt className="sr-only">Average per minute</dt>
            <dd>{avgPerMinute(breakdown)}/m avg</dd>
          </div>
        </dl>
      </header>

      <table className="w-full text-[12.5px]">
        <caption className="sr-only">Base cost per component</caption>
        <thead className="sr-only">
          <tr>
            <th scope="col">Component</th>
            <th scope="col">Rate per minute</th>
            <th scope="col">Billed minutes</th>
            <th scope="col">Cost</th>
          </tr>
        </thead>
        <tbody>
          {breakdown.lines.map((l) => (
            <tr key={l.component} className="border-b border-line/70 last:border-0">
              <th scope="row" className="py-2 pl-4 pr-2 text-left font-normal">
                <span className="text-fg">{COMPONENT_LABELS[l.component] ?? l.component}</span>
                <span className="ml-2 text-fg-3">
                  {providerLabel(l.provider)}
                  {l.model ? ` ${l.model}` : ""}
                </span>
              </th>
              <td className="px-2 text-right font-mono text-fg-3 tnum">{formatUsd(l.rate_per_min_usd, { places: 4 })}/m</td>
              <td className="px-2 text-right font-mono text-fg-3 tnum">{Number(l.billed_minutes).toFixed(2)}m</td>
              <td className="py-2 pl-2 pr-4 text-right">
                <MoneyText value={l.cost_usd} places={3} className="text-fg" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {surcharged.length > 0 && (
        <div className="border-t border-line bg-amber-soft/50 px-4 py-3">
          <p className="mb-2 flex items-center gap-1.5 text-[12px] font-medium text-amber-text">
            <Lightning weight="fill" className="size-3.5" aria-hidden />
            Bundle surcharge
          </p>
          <ul className="flex flex-col gap-2">
            {surcharged.map((l) => {
              const over = l.meters.filter((m) => m.used > Number(m.included));
              return (
                <li key={l.component} className="grid grid-cols-[1fr_auto] gap-x-4 text-[12.5px]">
                  <span className="text-fg">
                    {COMPONENT_LABELS[l.component]} billed at{" "}
                    <span className="font-mono tnum">{Number(l.bundle_multiplier).toFixed(2)}x</span> duration
                  </span>
                  <MoneyText value={l.surcharge_usd} places={4} signed className="text-amber-text" />
                  {over.map((m) => (
                    <span key={m.unit} className="col-span-2 font-mono text-[11.5px] text-fg-3 tnum">
                      {m.used.toLocaleString()} {UNIT_LABELS[m.unit] ?? m.unit} used, {Math.floor(Number(m.included)).toLocaleString()} included
                    </span>
                  ))}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <footer className="flex items-baseline justify-between border-t border-line px-4 py-3">
        <span className="text-[12.5px] text-fg-2">
          Total <span className="font-mono text-[11px] text-fg-3">catalog v{breakdown.catalog_version}</span>
        </span>
        <MoneyText value={breakdown.total_usd} places={3} className="text-[15px] font-medium text-fg" />
      </footer>
    </section>
  );
}
