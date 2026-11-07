import { AudioLines, BrainCircuit, Captions, Mic, Server, Volume2, Zap, type LucideIcon } from "lucide-react";
import type { CostBreakdown as CostBreakdownT, CostLine } from "../api/types";
import { formatUsd, toMicros } from "../lib/money";
import { modelLabel } from "../lib/catalogSeed";
import { providerLabel } from "../lib/providers";
import { cn } from "./cn";
import { MoneyText } from "./Money";
import { InfoTip, TruncatedText } from "./TruncatedText";
import { mss } from "../lib/format";

export const COMPONENT_LABELS: Record<string, string> = {
  stt: "Speech to text",
  llm: "Language model",
  tts: "Text to speech",
  nc: "Noise cancellation",
  platform: "Platform",
  embedding: "Embeddings",
};

/** One icon per link of the chain, used wherever a component is named. */
export const COMPONENT_ICONS: Record<string, LucideIcon> = {
  mic: Mic,
  stt: Captions,
  llm: BrainCircuit,
  tts: Volume2,
  nc: AudioLines,
  platform: Server,
  embedding: BrainCircuit,
};

const UNIT_LABELS: Record<string, string> = {
  llm_input_tokens: "input tokens",
  llm_output_tokens: "output tokens",
  tts_chars: "characters",
};

/** Average per-minute price over the billed duration, 4 places: total / duration_minutes. */
function avgPerMinute(b: CostBreakdownT): string {
  const total = toMicros(b.total_usd) ?? 0n;
  if (b.billed_seconds === 0) return formatUsd(0n, { places: 4 });
  return formatUsd((total * 60n) / BigInt(b.billed_seconds), { places: 4 });
}

const hasSurcharge = (l: CostLine) => (toMicros(l.surcharge_usd) ?? 0n) > 0n;

/**
 * Itemised call cost as a receipt (spec 001 US3, FR-011): duration, billed minutes and average
 * rate; one line per link of the chain; then a highlighted surcharge line for every component
 * whose usage ran past its per-minute bundle, with the multiplier and the meter that caused it.
 */
export function CostBreakdownCard({
  breakdown,
  className,
  title = "Cost breakdown",
  onConsole,
}: {
  breakdown: CostBreakdownT;
  className?: string;
  title?: string;
  onConsole?: boolean;
}) {
  const surcharged = breakdown.lines.filter(hasSurcharge);
  return (
    <section aria-label={title} className={cn("@container overflow-hidden rounded-panel border border-line bg-surface", className)}>
      <header className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 px-5 pb-3 pt-4">
        <h3 className="text-[14px] font-semibold text-fg">{title}</h3>
        <div className="flex items-center gap-3">
          <dl className="flex gap-3 text-[12px] text-fg-3">
            <div className="flex gap-1">
              <dt className="sr-only">Duration</dt>
              <dd className="font-mono tnum">{mss(breakdown.billed_seconds)}</dd>
            </div>
            <div className="flex gap-1">
              <dt className="sr-only">Billed minutes</dt>
              <dd>
                <span className="font-mono tnum">{Number(breakdown.duration_minutes).toFixed(2)}</span> min
              </dd>
            </div>
            <div className="flex gap-1">
              <dt className="sr-only">Average per minute</dt>
              <dd>
                <span className="font-mono tnum">{avgPerMinute(breakdown)}</span> a minute
              </dd>
            </div>
          </dl>
          <InfoTip label="How the call was measured">
            Calls are billed per second, rounded up to the whole second. Billed minutes are those seconds divided by 60, and the rate a minute is the
            total divided by them.
          </InfoTip>
        </div>
      </header>

      <table className="w-full border-t border-dashed border-line-strong text-[13px]">
        <caption className="sr-only">Base cost per component</caption>
        <thead className="sr-only">
          <tr>
            <th scope="col">Component</th>
            <th scope="col" className="hidden @[24rem]:table-cell">
              Rate per minute
            </th>
            <th scope="col">Billed minutes</th>
            <th scope="col">Cost</th>
          </tr>
        </thead>
        <tbody>
          {breakdown.lines.map((l) => {
            const Icon = COMPONENT_ICONS[l.component] ?? Server;
            const surcharge = hasSurcharge(l);
            return (
              <tr key={l.component} className="border-b border-line/70 last:border-0">
                <th scope="row" className="py-2.5 pl-5 pr-2 text-left font-normal">
                  <span className="flex min-w-0 items-center gap-2">
                    <Icon className={cn("size-3.5 shrink-0", surcharge ? "text-warning-text" : "text-fg-3")} aria-hidden />
                    <span className="whitespace-nowrap text-fg">{COMPONENT_LABELS[l.component] ?? l.component}</span>
                    <TruncatedText className="hidden text-fg-3 @[30rem]:block">
                      {l.component === "platform"
                        ? providerLabel(l.provider)
                        : (modelLabel(l.component, l.provider, l.model) ?? providerLabel(l.provider))}
                    </TruncatedText>
                  </span>
                </th>
                <td className="hidden px-2 text-right font-mono text-fg-3 tnum @[24rem]:table-cell">
                  {formatUsd(l.rate_per_min_usd, { places: 4 })}/m
                </td>
                <td className={cn("px-2 text-right font-mono tnum", surcharge ? "font-medium text-warning-text" : "text-fg-3")}>
                  {Number(l.billed_minutes).toFixed(2)}m
                </td>
                <td className="py-2.5 pl-2 pr-5 text-right">
                  <MoneyText value={l.cost_usd} places={3} className="text-fg" />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {surcharged.length > 0 && (
        <div className="heat-border mx-3 mb-3 mt-1 rounded-control bg-warning-soft/70 px-4 py-3">
          <p className="mb-1.5 flex items-center gap-1.5 text-[13px] font-semibold text-warning-text">
            <Zap className="size-3.5" aria-hidden />
            Bundle surcharge
            <InfoTip label="What a bundle surcharge is" className="text-warning-text">
              Every minute of call includes a bundle: 20,000 input and 200 output tokens for the model, 750 characters for the voice. A call that uses
              more bills that component for more minutes than it lasted. The multiplier is those billed minutes divided by the call length.
            </InfoTip>
          </p>
          <ul className="flex flex-col gap-2">
            {surcharged.map((l) => {
              const over = l.meters.filter((m) => m.used > Number(m.included));
              return (
                <li key={l.component} className="grid grid-cols-[1fr_auto] gap-x-4 text-[13px]">
                  <span className="text-fg">
                    {COMPONENT_LABELS[l.component]} billed at <span className="font-mono tnum">{Number(l.bundle_multiplier).toFixed(2)}x</span> the
                    call length
                  </span>
                  <MoneyText value={l.surcharge_usd} places={4} signed className="font-medium text-warning-text" />
                  {over.map((m) => (
                    <span key={m.unit} className="col-span-2 text-[12px] text-fg-2">
                      <span className="font-mono tnum">{m.used.toLocaleString()}</span> {UNIT_LABELS[m.unit] ?? m.unit} used,{" "}
                      <span className="font-mono tnum">{Math.floor(Number(m.included)).toLocaleString()}</span> included
                    </span>
                  ))}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <footer
        className={cn(
          "flex items-baseline justify-between border-t border-dashed border-line-strong px-5 py-3.5",
          onConsole ? "bg-surface" : "bg-surface-2/60",
        )}
      >
        <span className="flex items-center gap-1.5 text-[13px] text-fg-2">
          Total <span className="text-[12px] text-fg-3">on catalog version {breakdown.catalog_version}</span>
          <InfoTip label="About the catalog version">
            The price list in force when the call started. Each line is rounded up to $0.001, and later price changes never alter this receipt.
          </InfoTip>
        </span>
        <MoneyText value={breakdown.total_usd} places={3} className="text-[17px] font-semibold text-fg" />
      </footer>
    </section>
  );
}
