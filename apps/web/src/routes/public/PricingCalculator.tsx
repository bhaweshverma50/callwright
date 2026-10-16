import { Lightning, WarningCircle } from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import { useCatalog, useQuote } from "../../api/queries";
import type { Catalog, PricingComponent, QuoteRequest } from "../../api/types";
import { COMPONENT_LABELS, Field, Input, Label, Select, Skeleton, Slider, type SelectGroup, cn } from "../../components";
import { formatUsd, toMicros } from "../../lib/money";
import { providerLabel } from "../../lib/providers";
import { useDebounced } from "../../lib/useDebounced";

export const MAX_MINUTES = 250_000;
const SAMPLE_MINUTES = 60;
const NONE = "none";

const key = (provider: string, model: string | null | undefined) => `${provider}|${model ?? ""}`;
const parse = (k: string) => {
  const [provider = "", model = ""] = k.split("|");
  return { provider, model: model || null };
};

function groupsFor(catalog: Catalog, component: PricingComponent): SelectGroup[] {
  const byProvider = new Map<string, SelectGroup>();
  for (const e of catalog.entries.filter((x) => x.component === component)) {
    const g = byProvider.get(e.provider) ?? { label: providerLabel(e.provider), options: [] };
    g.options.push({ value: key(e.provider, e.model), label: e.label, meta: `${formatUsd(e.rate_per_min_usd, { places: 4 })}/m` });
    byProvider.set(e.provider, g);
  }
  return [...byProvider.values()];
}

interface Profile {
  inputTokens: number;
  outputTokens: number;
  ttsChars: number;
}

const DEFAULTS = {
  stt: key("deepgram", "nova-3"),
  llm: key("azure_openai", "gpt-5-mini"),
  tts: key("elevenlabs", "eleven_flash_v2_5"),
  nc: NONE,
};

/**
 * Public pricing calculator (T073, US3.4, FR-013). Rates come from the live catalog and every
 * price from the quote endpoint, so the page and the bill use one engine. Per-minute total and
 * monthly estimate update as soon as a choice changes; monthly = per-minute x minutes.
 * The usage profile applies the bundle rule: when tokens or characters per minute pass the
 * bundle, the component bills at the higher of duration and usage over bundle.
 */
export function PricingCalculator() {
  const catalog = useCatalog();
  const [sel, setSel] = useState(DEFAULTS);
  const [minutes, setMinutes] = useState(10_000);
  const [profile, setProfile] = useState<Profile>({ inputTokens: 12_000, outputTokens: 150, ttsChars: 600 });
  const debouncedProfile = useDebounced(profile, 150);

  const request: QuoteRequest | null = useMemo(() => {
    if (!catalog.data) return null;
    return {
      components: {
        stt: parse(sel.stt),
        llm: parse(sel.llm),
        tts: parse(sel.tts),
        nc: sel.nc === NONE ? null : parse(sel.nc),
      },
      usage: {
        duration_ms: SAMPLE_MINUTES * 60_000,
        llm_input_tokens: debouncedProfile.inputTokens * SAMPLE_MINUTES,
        llm_output_tokens: debouncedProfile.outputTokens * SAMPLE_MINUTES,
        tts_chars: debouncedProfile.ttsChars * SAMPLE_MINUTES,
      },
    };
  }, [catalog.data, sel, debouncedProfile]);
  const quote = useQuote(request);

  const groups = useMemo(() => {
    if (!catalog.data) return null;
    return {
      stt: groupsFor(catalog.data, "stt"),
      llm: groupsFor(catalog.data, "llm"),
      tts: groupsFor(catalog.data, "tts"),
      nc: [{ label: "", options: [{ value: NONE, label: "None" }] }, ...groupsFor(catalog.data, "nc")],
    };
  }, [catalog.data]);

  const q = quote.data;
  const baseMicros = q ? (toMicros(q.per_minute_total_usd) ?? 0n) : null;
  const callTotal = q?.call ? (toMicros(q.call.total_usd) ?? 0n) : null;
  const effectiveMicros = callTotal !== null ? (callTotal + BigInt(SAMPLE_MINUTES) / 2n) / BigInt(SAMPLE_MINUTES) : baseMicros;
  const surcharged = q?.call?.lines.filter((l) => (toMicros(l.surcharge_usd) ?? 0n) > 0n) ?? [];
  const perMinute = surcharged.length ? effectiveMicros : baseMicros;
  const monthly = perMinute !== null ? perMinute * BigInt(minutes) : null;
  const unpriced = q?.lines.filter((l) => l.status === "unpriced") ?? [];

  return (
    <div className="grid overflow-hidden rounded-panel border border-line bg-surface shadow-panel lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
      <div className="flex flex-col gap-6 p-6">
        <div className="grid gap-4 sm:grid-cols-2">
          {(["stt", "llm", "tts", "nc"] as const).map((c) => (
            <Field key={c} label={c === "llm" ? "Model" : c === "tts" ? "Voice" : COMPONENT_LABELS[c]}>
              {({ id, describedBy }) =>
                groups ? (
                  <Select
                    id={id}
                    describedBy={describedBy}
                    value={sel[c]}
                    groups={groups[c]}
                    onValueChange={(v) => setSel((s) => ({ ...s, [c]: v }))}
                  />
                ) : (
                  <Skeleton className="h-8 w-full" />
                )
              }
            </Field>
          ))}
        </div>

        <Field label="Minutes per month" aside={<span className="font-mono text-[11px] text-fg-3">0 to {MAX_MINUTES.toLocaleString()}</span>}>
          {({ id, describedBy }) => (
            <div className="flex items-center gap-4">
              <Slider
                aria-label="Minutes per month"
                value={minutes}
                min={0}
                max={MAX_MINUTES}
                step={500}
                onValueChange={setMinutes}
                valueText={(v) => `${v.toLocaleString()} minutes`}
              />
              <Input
                id={id}
                aria-describedby={describedBy}
                inputMode="numeric"
                className="w-[112px] shrink-0 text-right font-mono tnum"
                value={minutes.toLocaleString()}
                onChange={(e) => {
                  const n = Number(e.target.value.replace(/[^\d]/g, ""));
                  setMinutes(Math.min(MAX_MINUTES, Number.isFinite(n) ? n : 0));
                }}
              />
            </div>
          )}
        </Field>

        <details className="group rounded-control border border-line bg-surface-2/60 px-4 py-3">
          <summary className="cursor-pointer select-none text-[13px] font-medium text-fg marker:text-fg-3">
            Usage per minute of call
            <span className="ml-2 font-normal text-fg-3">for long prompts or chatty agents</span>
          </summary>
          <div className="mt-4 flex flex-col gap-4">
            <ProfileSlider label="LLM input tokens" bundle={20_000} max={80_000} step={1_000} value={profile.inputTokens} onChange={(v) => setProfile((p) => ({ ...p, inputTokens: v }))} />
            <ProfileSlider label="LLM output tokens" bundle={200} max={800} step={10} value={profile.outputTokens} onChange={(v) => setProfile((p) => ({ ...p, outputTokens: v }))} />
            <ProfileSlider label="Voice characters" bundle={750} max={2_000} step={25} value={profile.ttsChars} onChange={(v) => setProfile((p) => ({ ...p, ttsChars: v }))} />
          </div>
        </details>
      </div>

      <div className="flex flex-col border-t border-line bg-surface-2/70 p-6 lg:border-l lg:border-t-0" aria-live="polite">
        <div className="grid grid-cols-2 gap-6">
          <div className="flex flex-col gap-1.5">
            <Label>Per minute</Label>
            {perMinute === null ? (
              <Skeleton className="h-8 w-24" />
            ) : (
              <output data-testid="per-minute" className="font-mono text-[28px] font-medium leading-none text-fg tnum">
                {formatUsd(perMinute, { places: 4 })}
              </output>
            )}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Per month</Label>
            {monthly === null ? (
              <Skeleton className="h-8 w-28" />
            ) : (
              <output data-testid="monthly" className="font-mono text-[28px] font-medium leading-none text-fg tnum">
                {formatUsd(monthly, { places: 2 })}
              </output>
            )}
          </div>
        </div>

        {unpriced.length > 0 && (
          <p className="mt-4 flex items-start gap-2 rounded-control bg-amber-soft px-3 py-2 text-[12.5px] text-amber-text">
            <WarningCircle weight="fill" className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            {unpriced.map((l) => COMPONENT_LABELS[l.component]).join(", ")}: price unavailable, so the total is incomplete.
          </p>
        )}

        <table className={cn("mt-6 w-full text-[12.5px] transition-opacity", quote.isFetching && "opacity-70")}>
          <caption className="sr-only">Rate per component</caption>
          <tbody>
            {(q?.lines ?? []).map((l) => (
              <tr key={l.component} className="border-b border-line last:border-0">
                <th scope="row" className="py-2 text-left font-normal">
                  <span className="text-fg">{COMPONENT_LABELS[l.component]}</span>
                  <span className="ml-2 text-fg-3">{l.label ?? providerLabel(l.provider)}</span>
                </th>
                <td className="py-2 text-right font-mono text-fg tnum">
                  {l.rate_per_min_usd ? `${formatUsd(l.rate_per_min_usd, { places: 4 })}/m` : <span className="text-amber-text">unavailable</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {surcharged.length > 0 && (
          <div className="mt-4 rounded-control border border-amber/40 bg-amber-soft/70 px-3 py-2.5 text-[12.5px]">
            <p className="flex items-center gap-1.5 font-medium text-amber-text">
              <Lightning weight="fill" className="size-3.5" aria-hidden />
              Bundle surcharge applies
            </p>
            <ul className="mt-1 flex flex-col gap-0.5 text-fg-2">
              {surcharged.map((l) => (
                <li key={l.component}>
                  {COMPONENT_LABELS[l.component]} bills at <span className="font-mono tnum">{Number(l.bundle_multiplier).toFixed(2)}x</span> the call
                  length, adding <span className="font-mono tnum">{formatUsd((toMicros(l.surcharge_usd) ?? 0n) / BigInt(SAMPLE_MINUTES), { places: 4 })}</span> a minute.
                </li>
              ))}
            </ul>
            {baseMicros !== null && (
              <p className="mt-1.5 font-mono text-[11.5px] text-fg-3 tnum">Base rate without surcharge {formatUsd(baseMicros, { places: 4 })}/m</p>
            )}
          </div>
        )}

        <p className="mt-auto pt-6 text-[12px] leading-relaxed text-fg-3">
          Catalog version {q?.catalog_version ?? catalog.data?.version ?? ""}. Calls are billed per second, rounded up, from your prepaid balance.
        </p>
      </div>
    </div>
  );
}

function ProfileSlider({ label, bundle, max, step, value, onChange }: { label: string; bundle: number; max: number; step: number; value: number; onChange: (v: number) => void }) {
  const over = value > bundle;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between text-[12.5px]">
        <span className="text-fg-2">{label} per minute</span>
        <span className={cn("font-mono tnum", over ? "text-amber-text" : "text-fg")}>
          {value.toLocaleString()}
          <span className="text-fg-3"> / {bundle.toLocaleString()} included</span>
        </span>
      </div>
      <Slider aria-label={`${label} per minute`} value={value} min={0} max={max} step={step} onValueChange={onChange} valueText={(v) => `${v.toLocaleString()} per minute`} />
    </div>
  );
}
