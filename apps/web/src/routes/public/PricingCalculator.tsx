import * as RP from "@radix-ui/react-popover";
import { Check, ChevronDown, CircleAlert, Clock, Ear, Mic, Plus, SlidersHorizontal, Zap } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useCatalog, useQuote } from "../../api/queries";
import type { Catalog, PricingComponent, QuoteLine, QuoteRequest } from "../../api/types";
import {
  COMPONENT_ICONS,
  COMPONENT_LABELS,
  Field,
  FlowChain,
  InfoTip,
  Input,
  Skeleton,
  Slider,
  Ticker,
  Tooltip,
  TruncatedText,
  cn,
  focusRing,
  type FlowNode,
} from "../../components";
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
/** What each link does and how it is billed, shown when a chain node is hovered or focused. */
const NODE_HINTS: Record<keyof Sel, string> = {
  nc: "Cleans background noise out of the caller's audio before speech to text hears it. Optional; billed per minute of call when on.",
  stt: "Turns the caller's speech into text as they talk. Billed per minute of call.",
  llm: "Reads the conversation and decides what the agent says or does next. Billed per minute; each minute includes 20,000 input and 200 output tokens.",
  tts: "Speaks the model's reply in the agent's voice. Billed per minute; each minute includes 750 characters.",
};
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
  const [openNode, setOpenNode] = useState<keyof Sel | null>(null);
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

  const choose = (c: keyof Sel, v: string) => setSel((s) => ({ ...s, [c]: v }));

  const nodeFor = (c: keyof Sel): FlowNode => {
    const off = c === "nc" && sel.nc === NONE;
    const line = lineFor(c);
    const current = groups?.[c].flatMap((g) => g.options).find((o) => o.value === sel[c]);
    const Icon = COMPONENT_ICONS[c]!;
    return {
      key: c,
      label: NODE_TITLES[c],
      off,
      icon: off ? <Plus aria-hidden /> : <Icon aria-hidden />,
      detail: (
        <>
          {groups ? (
            <TruncatedText focusable={false} tooltip={false} className="max-w-full text-[13px] font-medium text-fg">
              {off ? "Off" : current?.label}
            </TruncatedText>
          ) : (
            <Skeleton className="mx-auto mt-1 h-3.5 w-16" />
          )}
          <span className="block font-mono text-[11.5px] text-fg-3 tnum">
            {off
              ? "optional"
              : line?.rate_per_min_usd
                ? `${formatUsd(line.rate_per_min_usd, { places: 4 })}/m`
                : line?.status === "unpriced"
                  ? "unavailable"
                  : ""}
          </span>
        </>
      ),
    };
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
          <FlowChain
            label="Signal chain"
            size="lg"
            flow
            rowHeight={96}
            active={openNode}
            linkLabels={[
              null,
              ...CHAIN.map((c) => (q && (subtotalAfter[c] ?? 0n) > 0n ? <Ticker value={Number(subtotalAfter[c])} format={usd4} /> : null)),
            ]}
            nodes={[
              { key: "caller", label: "Caller speaks", icon: <Mic aria-hidden /> },
              ...CHAIN.map((c) => nodeFor(c)),
              { key: "hears", label: "Caller hears", icon: <Ear aria-hidden /> },
            ]}
            renderNode={(n, content) => {
              if (!(CHAIN as string[]).includes(n.key)) return <div className="flow-node-body">{content}</div>;
              const c = n.key as keyof Sel;
              return (
                <ChainChoice
                  component={c}
                  value={sel[c]}
                  groups={groups?.[c] ?? null}
                  open={openNode === c}
                  onOpenChange={(o) => setOpenNode(o ? c : null)}
                  onChoose={(v) => choose(c, v)}
                >
                  {content}
                </ChainChoice>
              );
            }}
          />
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

function ChainChoice({
  component,
  value,
  groups,
  open,
  onOpenChange,
  onChoose,
  children,
}: {
  component: keyof Sel;
  value: string;
  groups: ChoiceGroup[] | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChoose: (v: string) => void;
  children: ReactNode;
}) {
  const current = groups?.flatMap((g) => g.options).find((o) => o.value === value);
  const title = NODE_TITLES[component];
  const off = component === "nc" && value === NONE;
  const setOpen = onOpenChange;
  return (
    <RP.Root open={open} onOpenChange={onOpenChange}>
      <Tooltip
        enabled={!open}
        content={
          <span className="flex flex-col gap-0.5">
            <span>
              {title}: {off ? "off" : (current?.label ?? "")}
            </span>
            <span className="tooltip-muted font-normal">{NODE_HINTS[component]}</span>
          </span>
        }
      >
        <RP.Trigger
          aria-label={`${title}: ${off ? "Off" : (current?.label ?? "loading")}. Change`}
          disabled={!groups}
          className={cn(
            "flow-node-body relative isolate w-full cursor-pointer rounded-panel before:absolute before:-inset-x-1 before:-inset-y-1.5 before:-z-10 before:rounded-panel before:transition-colors before:duration-150 hover:before:bg-accent-soft/50 data-[state=open]:before:bg-accent-soft/60",
            focusRing,
          )}
        >
          {children}
        </RP.Trigger>
      </Tooltip>
      <RP.Portal>
        <RP.Content
          side="bottom"
          align="center"
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
                      <TruncatedText focusable={false} side="left" className="flex-1">
                        {o.label}
                      </TruncatedText>
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
                  <span className="flex min-w-0 items-center gap-2">
                    <Icon className="size-3.5 shrink-0 text-fg-3" aria-hidden />
                    <span className="text-fg">{COMPONENT_LABELS[l.component]}</span>
                    <TruncatedText className="hidden text-fg-3 sm:block">{l.label ?? providerLabel(l.provider)}</TruncatedText>
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
            <InfoTip label="What a bundle surcharge is" className="text-warning-text">
              Every minute of call includes 20,000 input and 200 output tokens for the model and 750 characters for the voice. Usage past that bills
              the component at a multiple of the call length: the multiplier is the usage divided by the bundle.
            </InfoTip>
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
          <dt className="flex items-center gap-1.5 text-[13px] text-fg-2">
            Per minute
            <InfoTip label="What the per-minute price includes">
              Every link in the chain plus the platform fee, with any bundle surcharge from the usage profile. Calls are billed per second, so a 90
              second call costs one and a half times this.
            </InfoTip>
          </dt>
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
