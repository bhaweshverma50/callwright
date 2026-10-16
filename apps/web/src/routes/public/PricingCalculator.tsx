import * as RP from "@radix-ui/react-popover";
import { Check, ChevronDown, CircleAlert, Clock, Ear, Mic, Plus, SlidersHorizontal, Zap } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useId, useMemo, useState, type ReactNode } from "react";
import { useCatalog, useQuote } from "../../api/queries";
import type { Catalog, PricingComponent, QuoteLine, QuoteRequest } from "../../api/types";
import { COMPONENT_ICONS, COMPONENT_LABELS, Field, Input, Skeleton, Slider, Ticker, cn, focusRing } from "../../components";
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

interface Choice {
  value: string;
  label: string;
  rate: string;
}
interface ChoiceGroup {
  label: string;
  options: Choice[];
}

function groupsFor(catalog: Catalog, component: PricingComponent): ChoiceGroup[] {
  const byProvider = new Map<string, ChoiceGroup>();
  for (const e of catalog.entries.filter((x) => x.component === component)) {
    const g = byProvider.get(e.provider) ?? { label: providerLabel(e.provider), options: [] };
    g.options.push({ value: key(e.provider, e.model), label: e.label, rate: e.rate_per_min_usd });
    byProvider.set(e.provider, g);
  }
  return [...byProvider.values()];
}

interface Profile {
  inputTokens: number;
  outputTokens: number;
  ttsChars: number;
}

type Sel = { stt: string; llm: string; tts: string; nc: string };
const DEFAULTS: Sel = {
  stt: key("deepgram", "nova-3"),
  llm: key("azure_openai", "gpt-5-mini"),
  tts: key("elevenlabs", "eleven_flash_v2_5"),
  nc: NONE,
};

const NODE_TITLES: Record<keyof Sel, string> = { nc: "Noise cancellation", stt: "Speech to text", llm: "Model", tts: "Voice" };
/** The order a voice travels: the caller's mic, optional noise cancellation, then the chain. */
const CHAIN: (keyof Sel)[] = ["nc", "stt", "llm", "tts"];

const usd4 = (micros: number) => formatUsd(BigInt(Math.round(micros)), { places: 4 });
const usd2 = (micros: number) => formatUsd(BigInt(Math.round(micros)), { places: 2 });

/**
 * Public pricing calculator as a signal chain (T073, US3.4, FR-013; docs/DESIGN.md section 6).
 * Mic > noise cancellation (optional) > speech to text > model > voice > speaker. Clicking a link
 * opens its vendor and model choices; the per-minute cost runs along the chain into the receipt.
 * Rates come from the live catalog and every price from the quote endpoint, so the page and the
 * bill use one engine. Monthly = per-minute x minutes. The usage profile applies the bundle rule.
 */
export function PricingCalculator() {
  const catalog = useCatalog();
  const [sel, setSel] = useState<Sel>(DEFAULTS);
  const [minutes, setMinutes] = useState(10_000);
  const [pulse, setPulse] = useState(0);
  const [profile, setProfile] = useState<Profile>({ inputTokens: 12_000, outputTokens: 150, ttsChars: 600 });
  const debouncedProfile = useDebounced(profile, 150);

  const request: QuoteRequest | null = useMemo(() => {
    if (!catalog.data) return null;
    return {
      components: { stt: parse(sel.stt), llm: parse(sel.llm), tts: parse(sel.tts), nc: sel.nc === NONE ? null : parse(sel.nc) },
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
      nc: [{ label: "", options: [{ value: NONE, label: "Off", rate: "0" }] }, ...groupsFor(catalog.data, "nc")],
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
  const lineFor = (c: string): QuoteLine | undefined => q?.lines.find((l) => l.component === c);

  // Running per-minute subtotal after each link, in the order the voice travels.
  let running = 0n;
  const subtotalAfter: Partial<Record<keyof Sel, bigint>> = {};
  for (const c of CHAIN) {
    const rate = lineFor(c)?.rate_per_min_usd;
    if (rate) running += toMicros(rate) ?? 0n;
    subtotalAfter[c] = running;
  }

  const choose = (c: keyof Sel, v: string) => {
    setSel((s) => ({ ...s, [c]: v }));
    setPulse((p) => p + 1);
  };

  return (
    <div className="relative">
      <div aria-hidden className="glow-backdrop pointer-events-none absolute -inset-8 -z-0 rounded-[48px] blur-2xl" />
      <div className="relative overflow-hidden rounded-feature border border-line bg-surface shadow-2">
        <div className="border-b border-line px-5 pb-6 pt-5 sm:px-7">
          <p className="mb-5 flex items-center gap-2 text-[13px] text-fg-3">
            <SlidersHorizontal className="size-4" aria-hidden />
            Click a link in the chain to change it.
          </p>
          <ol aria-label="Signal chain" className="flex flex-col items-stretch gap-0 lg:flex-row lg:items-start">
            <EndNode icon={<Mic aria-hidden />} title="Caller speaks" />
            {CHAIN.map((c) => (
              <li key={c} className="contents">
                <Wire subtotal={subtotalAfter[CHAIN[CHAIN.indexOf(c) - 1] as keyof Sel] ?? 0n} pulse={pulse} first={c === "nc"} loading={!q} />
                <ChainChoice component={c} value={sel[c]} groups={groups?.[c] ?? null} line={lineFor(c)} onChoose={(v) => choose(c, v)} />
              </li>
            ))}
            <li className="contents">
              <Wire subtotal={subtotalAfter.tts ?? 0n} pulse={pulse} loading={!q} />
            </li>
            <EndNode icon={<Ear aria-hidden />} title="Caller hears" />
          </ol>
        </div>

        <div className="grid lg:grid-cols-[minmax(0,1fr)_minmax(0,420px)]">
          <div className="flex flex-col gap-6 px-5 py-6 sm:px-7">
            <Field
              label="Minutes per month"
              aside={
                <span className="text-[12px] text-fg-3">
                  0 to <span className="font-mono tnum">{MAX_MINUTES.toLocaleString()}</span>
                </span>
              }
            >
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
                    className="w-[120px] shrink-0 text-right font-mono tnum"
                    value={minutes.toLocaleString()}
                    onChange={(e) => {
                      const n = Number(e.target.value.replace(/[^\d]/g, ""));
                      setMinutes(Math.min(MAX_MINUTES, Number.isFinite(n) ? n : 0));
                    }}
                  />
                </div>
              )}
            </Field>

            <details className="group rounded-panel border border-line bg-surface-2/60 px-4 py-3.5">
              <summary className={cn("flex cursor-pointer select-none list-none items-center gap-2 text-[13.5px] font-medium text-fg", focusRing)}>
                <ChevronDown className="size-4 text-fg-3 transition-transform group-open:rotate-180" aria-hidden />
                Usage per minute of call
                <span className="font-normal text-fg-3">for long prompts or chatty agents</span>
              </summary>
              <div className="mt-4 flex flex-col gap-4">
                <ProfileSlider
                  label="LLM input tokens"
                  bundle={20_000}
                  max={80_000}
                  step={1_000}
                  value={profile.inputTokens}
                  onChange={(v) => setProfile((p) => ({ ...p, inputTokens: v }))}
                />
                <ProfileSlider
                  label="LLM output tokens"
                  bundle={200}
                  max={800}
                  step={10}
                  value={profile.outputTokens}
                  onChange={(v) => setProfile((p) => ({ ...p, outputTokens: v }))}
                />
                <ProfileSlider
                  label="Voice characters"
                  bundle={750}
                  max={2_000}
                  step={25}
                  value={profile.ttsChars}
                  onChange={(v) => setProfile((p) => ({ ...p, ttsChars: v }))}
                />
              </div>
            </details>

            {perMinute !== null && perMinute > 0n && (
              <section aria-labelledby="buys">
                <h3 id="buys" className="flex items-center gap-2 text-[13.5px] font-medium text-fg">
                  <Clock className="size-4 text-fg-3" aria-hidden />
                  What a top-up buys on this chain
                </h3>
                <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {[25, 100, 500, 1000].map((d) => (
                    <div key={d} className="rounded-control border border-line bg-surface-2/60 px-3.5 py-3">
                      <dt className="font-mono text-[12.5px] text-fg-3 tnum">{formatUsd(String(d), { places: 0 })}</dt>
                      <dd className="mt-1 text-[13px] text-fg-2">
                        <Ticker
                          value={Number((BigInt(d) * 1_000_000n) / perMinute)}
                          format={(n) => Math.round(n).toLocaleString()}
                          className="font-mono text-[16px] font-medium text-fg"
                        />{" "}
                        min
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            )}

            {unpriced.length > 0 && (
              <p className="flex items-start gap-2 rounded-control bg-warning-soft px-3 py-2 text-[13px] text-warning-text">
                <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                {unpriced.map((l) => COMPONENT_LABELS[l.component]).join(", ")}: price unavailable, so the total is incomplete.
              </p>
            )}
          </div>

          <Receipt
            lines={q?.lines ?? null}
            perMinute={perMinute}
            baseMicros={baseMicros}
            monthly={monthly}
            minutes={minutes}
            surcharged={surcharged.map((l) => ({
              component: l.component,
              multiplier: l.bundle_multiplier,
              perMinute: (toMicros(l.surcharge_usd) ?? 0n) / BigInt(SAMPLE_MINUTES),
            }))}
            fetching={quote.isFetching}
            version={q?.catalog_version ?? catalog.data?.version}
          />
        </div>
      </div>
    </div>
  );
}

function EndNode({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <li className="flex items-center gap-3 lg:w-[88px] lg:shrink-0 lg:flex-col lg:gap-2 lg:pt-2">
      <span className="grid size-11 place-items-center rounded-full border border-line-strong bg-surface-2 text-fg-2 [&_svg]:size-5">{icon}</span>
      <span className="text-[12.5px] text-fg-2 lg:text-center">{title}</span>
    </li>
  );
}

/** A link between nodes: heat-ramp line with flowing dashes; a particle runs along it after a change. */
function Wire({ subtotal, pulse, first, loading }: { subtotal: bigint; pulse: number; first?: boolean; loading: boolean }) {
  const reduce = useReducedMotion();
  const id = useId().replace(/:/g, "");
  return (
    <div
      aria-hidden
      className="relative flex h-8 items-center pl-[21px] lg:h-auto lg:min-w-6 lg:flex-1 lg:flex-col lg:items-stretch lg:pl-0 lg:pt-[29px]"
    >
      <span className="grad-heat absolute bottom-0 left-[21px] top-0 w-0.5 opacity-70 lg:hidden" />
      <svg viewBox="0 0 100 6" preserveAspectRatio="none" className="hidden h-1.5 w-full lg:block">
        <defs>
          <linearGradient id={`w-${id}`} x1="0" x2="100" y1="0" y2="0" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="var(--heat-1)" />
            <stop offset="0.6" stopColor="var(--heat-2)" />
            <stop offset="1" stopColor="var(--heat-3)" />
          </linearGradient>
        </defs>
        <line x1="0" x2="100" y1="3" y2="3" stroke="var(--border-strong)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        <line
          x1="0"
          x2="100"
          y1="3"
          y2="3"
          stroke={`url(#w-${id})`}
          strokeWidth="2"
          strokeDasharray="5 5"
          vectorEffect="non-scaling-stroke"
          className="animate-flow"
        />
        {!reduce && pulse > 0 && (
          <motion.circle
            key={pulse}
            r="3"
            cy="3"
            fill="var(--heat-2)"
            initial={{ cx: 0, opacity: 1 }}
            animate={{ cx: 100, opacity: [1, 1, 0] }}
            transition={{ duration: 0.9, ease: "easeInOut" }}
          />
        )}
      </svg>
      {!first && (
        <span className="relative ml-6 min-h-4 font-mono text-[11.5px] text-fg-3 tnum lg:ml-0 lg:mt-2 lg:text-center">
          {loading || subtotal === 0n ? "" : <Ticker value={Number(subtotal)} format={usd4} />}
        </span>
      )}
    </div>
  );
}

function ChainChoice({
  component,
  value,
  groups,
  line,
  onChoose,
}: {
  component: keyof Sel;
  value: string;
  groups: ChoiceGroup[] | null;
  line: QuoteLine | undefined;
  onChoose: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const Icon = COMPONENT_ICONS[component]!;
  const off = component === "nc" && value === NONE;
  const current = groups?.flatMap((g) => g.options).find((o) => o.value === value);
  const title = NODE_TITLES[component];
  return (
    <RP.Root open={open} onOpenChange={setOpen}>
      <RP.Trigger
        aria-label={`${title}: ${current?.label ?? "loading"}. Change`}
        disabled={!groups}
        className={cn(
          "live-border group flex w-full cursor-pointer items-center gap-3 rounded-panel border bg-surface px-3.5 py-3 text-left transition-[border-color,box-shadow,transform] duration-150 lg:w-[150px] lg:shrink-0 lg:flex-col lg:items-start lg:gap-2",
          off ? "border-dashed border-line-strong" : "border-line-strong shadow-1 hover:-translate-y-0.5 hover:border-accent/50 hover:shadow-glow",
          focusRing,
        )}
        data-active={open}
      >
        <span
          className={cn(
            "grid size-9 shrink-0 place-items-center rounded-full [&_svg]:size-4",
            off ? "bg-surface-2 text-fg-3" : "grad-action text-white",
          )}
        >
          {off ? <Plus aria-hidden /> : <Icon aria-hidden />}
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="text-[12px] text-fg-3">{title}</span>
          {groups ? (
            <span className="truncate text-[13.5px] font-medium text-fg">{off ? "Off" : current?.label}</span>
          ) : (
            <Skeleton className="mt-1 h-3.5 w-20" />
          )}
          <span className="font-mono text-[12px] text-fg-2 tnum">
            {off
              ? "optional"
              : line?.rate_per_min_usd
                ? `${formatUsd(line.rate_per_min_usd, { places: 4 })}/m`
                : line?.status === "unpriced"
                  ? "unavailable"
                  : ""}
          </span>
        </span>
        <ChevronDown className="size-4 shrink-0 text-fg-3 transition-transform group-data-[state=open]:rotate-180 lg:hidden" aria-hidden />
      </RP.Trigger>
      <RP.Portal>
        <RP.Content
          side="bottom"
          align="start"
          sideOffset={8}
          collisionPadding={16}
          className="z-50 max-h-[min(420px,var(--radix-popover-content-available-height))] w-[300px] overflow-y-auto rounded-panel border border-line bg-surface p-1.5 shadow-pop outline-none data-[state=open]:animate-pop-in data-[state=closed]:animate-[pop-in_120ms_ease-in_reverse]"
        >
          <div role="radiogroup" aria-label={`${title} choices`}>
            {groups?.map((g, gi) => (
              <div key={g.label || gi} className="pb-1">
                {g.label && <p className="px-2.5 pb-1 pt-2 text-[12px] font-medium text-fg-3">{g.label}</p>}
                {g.options.map((o) => {
                  const checked = o.value === value;
                  return (
                    <button
                      key={o.value}
                      type="button"
                      role="radio"
                      aria-checked={checked}
                      onClick={() => {
                        onChoose(o.value);
                        setOpen(false);
                      }}
                      className={cn(
                        "flex h-9 w-full cursor-pointer items-center gap-2.5 rounded-[6px] px-2.5 text-left text-[13px] text-fg transition-colors hover:bg-accent-soft/60",
                        checked && "bg-accent-soft/70",
                        focusRing,
                      )}
                    >
                      <Check className={cn("size-3.5 shrink-0 text-accent-text", !checked && "invisible")} strokeWidth={2.5} aria-hidden />
                      <span className="flex-1 truncate">{o.label}</span>
                      {o.value !== NONE && <span className="font-mono text-[11.5px] text-fg-3 tnum">{formatUsd(o.rate, { places: 4 })}/m</span>}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </RP.Content>
      </RP.Portal>
    </RP.Root>
  );
}

function Receipt({
  lines,
  perMinute,
  baseMicros,
  monthly,
  minutes,
  surcharged,
  fetching,
  version,
}: {
  lines: QuoteLine[] | null;
  perMinute: bigint | null;
  baseMicros: bigint | null;
  monthly: bigint | null;
  minutes: number;
  surcharged: { component: string; multiplier: string; perMinute: bigint }[];
  fetching: boolean;
  version: number | undefined;
}) {
  return (
    <section
      aria-label="Receipt"
      aria-live="polite"
      className="flex flex-col border-t border-line bg-surface-2/60 px-5 py-6 sm:px-7 lg:border-l lg:border-t-0"
    >
      <table className={cn("w-full text-[13px] transition-opacity", fetching && "opacity-70")}>
        <caption className="sr-only">Rate per component</caption>
        <tbody>
          {(lines ?? []).map((l) => {
            const Icon = COMPONENT_ICONS[l.component]!;
            return (
              <tr key={l.component} className="border-b border-dashed border-line-strong last:border-0">
                <th scope="row" className="py-2.5 text-left font-normal">
                  <span className="flex items-center gap-2">
                    <Icon className="size-3.5 text-fg-3" aria-hidden />
                    <span className="text-fg">{COMPONENT_LABELS[l.component]}</span>
                    <span className="hidden truncate text-fg-3 sm:inline">{l.label ?? providerLabel(l.provider)}</span>
                  </span>
                </th>
                <td className="py-2.5 text-right font-mono text-fg tnum">
                  {l.rate_per_min_usd ? `${formatUsd(l.rate_per_min_usd, { places: 4 })}/m` : <span className="text-warning-text">unavailable</span>}
                </td>
              </tr>
            );
          })}
          {!lines &&
            [0, 1, 2, 3].map((i) => (
              <tr key={i}>
                <td colSpan={2} className="py-2.5">
                  <Skeleton className="h-3.5 w-full" />
                </td>
              </tr>
            ))}
        </tbody>
      </table>

      {surcharged.length > 0 && (
        <div className="heat-border mt-3 rounded-control bg-warning-soft/70 px-3.5 py-3 text-[13px]">
          <p className="flex items-center gap-1.5 font-semibold text-warning-text">
            <Zap className="size-3.5" aria-hidden />
            Bundle surcharge applies
          </p>
          <ul className="mt-1 flex flex-col gap-0.5 text-fg-2">
            {surcharged.map((l) => (
              <li key={l.component}>
                {COMPONENT_LABELS[l.component]} bills at <span className="font-mono tnum">{Number(l.multiplier).toFixed(2)}x</span> the call length,
                adding <span className="font-mono tnum">{formatUsd(l.perMinute, { places: 4 })}</span> a minute.
              </li>
            ))}
          </ul>
          {baseMicros !== null && (
            <p className="mt-1.5 text-[12px] text-fg-3">
              Base rate without surcharge <span className="font-mono tnum">{formatUsd(baseMicros, { places: 4 })}</span> a minute
            </p>
          )}
        </div>
      )}

      <dl className="mt-5 grid grid-cols-2 gap-5 border-t border-line-strong pt-5">
        <div className="flex flex-col gap-1.5">
          <dt className="text-[13px] text-fg-2">Per minute</dt>
          <dd>
            {perMinute === null ? (
              <Skeleton className="h-8 w-28" />
            ) : (
              <output data-testid="per-minute" className="font-mono text-[26px] font-medium leading-none text-fg tnum">
                <Exact micros={perMinute} places={4} />
              </output>
            )}
          </dd>
        </div>
        <div className="flex flex-col gap-1.5">
          <dt className="text-[13px] text-fg-2">
            Per month, <span className="font-mono tnum">{minutes.toLocaleString()}</span> min
          </dt>
          <dd>
            {monthly === null ? (
              <Skeleton className="h-8 w-32" />
            ) : (
              <output data-testid="monthly" className="font-mono text-[26px] font-medium leading-none text-fg tnum">
                <Exact micros={monthly} places={2} />
              </output>
            )}
          </dd>
        </div>
      </dl>

      <p className="mt-auto pt-6 text-[12.5px] leading-relaxed text-fg-3">
        Catalog version <span className="font-mono tnum">{version ?? ""}</span>. Calls are billed per second, rounded up, from your prepaid balance.
      </p>
    </section>
  );
}

/** Counts to the new amount; the last frame is the exact figure. */
function Exact({ micros, places }: { micros: bigint; places: 2 | 4 }) {
  const exact = formatUsd(micros, { places });
  return <Ticker value={Number(micros)} format={(n) => (Math.round(n) === Number(micros) ? exact : places === 4 ? usd4(n) : usd2(n))} />;
}

function ProfileSlider({
  label,
  bundle,
  max,
  step,
  value,
  onChange,
}: {
  label: string;
  bundle: number;
  max: number;
  step: number;
  value: number;
  onChange: (v: number) => void;
}) {
  const over = value > bundle;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between text-[13px]">
        <span className="text-fg-2">{label} per minute</span>
        <span className={cn(over ? "text-warning-text" : "text-fg")}>
          <span className="font-mono tnum">{value.toLocaleString()}</span>
          <span className="text-fg-3">
            {" "}
            of <span className="font-mono tnum">{bundle.toLocaleString()}</span> included
          </span>
        </span>
      </div>
      <Slider
        aria-label={`${label} per minute`}
        tone="heat"
        value={value}
        min={0}
        max={max}
        step={step}
        onValueChange={onChange}
        valueText={(v) => `${v.toLocaleString()} per minute`}
      />
    </div>
  );
}
