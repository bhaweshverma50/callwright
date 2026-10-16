import { ChartLineUp, Crosshair, Wrench } from "@phosphor-icons/react";
import { BadgeDollarSign, Calculator, Clock, UserPlus } from "lucide-react";
import { Link } from "react-router";
import { Button, COMPONENT_ICONS, COMPONENT_LABELS, ChainLink, Reveal, RevealItem, cn } from "../../components";
import { catalogV1 } from "../../lib/catalogSeed";
import { formatUsd, toMicros } from "../../lib/money";
import { providerLabel } from "../../lib/providers";
import { SEED_PER_MINUTE_MICROS, talkMinutes } from "../../lib/stack";
import { LiveCall } from "./LiveCall";

const PARTS = ["stt", "llm", "tts", "nc", "platform"] as const;
type Part = (typeof PARTS)[number];

/** Lowest per-minute rate per component in the launch catalog (seed version 1). */
function fromRate(component: Part): string {
  const rates = catalogV1.entries.filter((e) => e.component === component).map((e) => toMicros(e.rate_per_min_usd) ?? 0n);
  const min = rates.reduce((a, b) => (b < a ? b : a));
  return formatUsd(min, { places: 4 });
}

const providersFor = (c: Part) => [...new Set(catalogV1.entries.filter((e) => e.component === c).map((e) => providerLabel(e.provider)))];

const NcIcon = COMPONENT_ICONS.nc!;
const TRIAL_MINUTES = talkMinutes(5_000_000n, SEED_PER_MINUTE_MICROS);

const LINKS: { c: Part; text: string }[] = [
  { c: "stt", text: "Hears the caller. Pick for accuracy on your callers' accents and line quality." },
  { c: "llm", text: "Decides what to say, calls your tools and searches your documents." },
  { c: "tts", text: "Speaks the answer. Pick a voice that fits the business." },
];

const LOOP = [
  { icon: ChartLineUp, title: "See every call", text: "Transcript, recording, per-turn latency and the itemised cost of each call, as it happens." },
  { icon: Crosshair, title: "Score it, then check the score", text: "Evaluators grade calls with their reasons. Your own labels show how often each one agrees with a person." },
  { icon: Wrench, title: "Fix what repeats", text: "Repeated failures become issues with a drafted prompt fix, replayed against the calls it would change before you apply it." },
];

/** Public home (T044, FR-016). Product visuals are real components fed by the pricing engine. */
export function Home() {
  return (
    <>
      <section className="relative overflow-hidden">
        <div className="mx-auto grid max-w-[1200px] items-center gap-14 px-4 pb-20 pt-12 sm:px-6 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] lg:pb-28 lg:pt-20">
          <Reveal>
            <RevealItem>
              <h1 className="grad-text max-w-[15ch] font-display text-[34px] font-semibold leading-[1.08] tracking-[-0.035em] sm:text-[46px] lg:text-[54px]">
                Phone agents fast enough that callers keep talking.
              </h1>
            </RevealItem>
            <RevealItem>
              <p className="mt-6 max-w-[48ch] text-[16px] leading-relaxed text-fg-2">
                Choose the speech recognition, model and voice. Callwright runs the call, times every turn and prices every second, so you can
                see why a caller stayed or hung up.
              </p>
            </RevealItem>
            <RevealItem className="mt-8 flex flex-wrap gap-3">
              <Button asChild variant="primary" size="lg" icon={<UserPlus aria-hidden />}>
                <Link to="/register">Create account</Link>
              </Button>
              <Button asChild variant="secondary" size="lg" icon={<Calculator aria-hidden />}>
                <Link to="/pricing">See pricing</Link>
              </Button>
            </RevealItem>
            <RevealItem>
              <p className="mt-6 flex items-center gap-2 text-[13.5px] text-fg-3">
                <Clock className="size-4" aria-hidden />
                New workspaces start with $5.00, about <span className="font-mono text-fg-2 tnum">{TRIAL_MINUTES}</span> minutes of calls.
              </p>
            </RevealItem>
          </Reveal>
          <LiveCall />
        </div>
      </section>

      <section aria-labelledby="chain" className="border-t border-line bg-surface/60">
        <div className="mx-auto max-w-[1200px] px-4 py-20 sm:px-6">
          <h2 id="chain" className="max-w-[22ch] font-display text-[26px] font-medium leading-[1.15] tracking-[-0.025em] text-fg sm:text-[32px]">
            Every link in the call is yours to choose.
          </h2>
          <p className="mt-4 max-w-[60ch] text-[15px] leading-relaxed text-fg-2">
            A call travels from the caller through speech to text, the model and the voice, and back. Swap any link in the agent settings;
            nothing else changes.
          </p>
          <ol className="mt-12 grid gap-4 md:grid-cols-[1fr_auto_1fr_auto_1fr] md:items-stretch md:gap-0">
            {LINKS.map((l, i) => {
              const Icon = COMPONENT_ICONS[l.c]!;
              return (
                <li key={l.c} className="contents">
                  <article className="lift flex flex-col rounded-panel border border-line bg-surface p-6 shadow-1">
                    <span className="grid size-10 place-items-center rounded-control bg-accent-soft text-accent-text">
                      <Icon className="size-5" aria-hidden />
                    </span>
                    <h3 className="mt-4 text-[16px] font-semibold text-fg">{COMPONENT_LABELS[l.c]}</h3>
                    <p className="mt-1.5 text-[14px] leading-relaxed text-fg-2">{l.text}</p>
                    <ul className="mt-5 flex flex-wrap gap-1.5" aria-label={`${COMPONENT_LABELS[l.c]} providers`}>
                      {providersFor(l.c).map((p) => (
                        <li key={p} className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[12.5px] text-fg-2">
                          {p}
                        </li>
                      ))}
                    </ul>
                  </article>
                  {i < LINKS.length - 1 && (
                    <div aria-hidden className="hidden w-10 items-center md:flex">
                      <ChainLink flow className="w-full" />
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
          <p className="mt-6 flex items-center gap-2 text-[13.5px] text-fg-3">
            <NcIcon className="size-4" aria-hidden />
            Optional noise cancellation from {providersFor("nc").join(" or ")} cleans the line before speech to text hears it.
          </p>
        </div>
      </section>

      <section aria-labelledby="loop" className="border-t border-line">
        <div className="mx-auto max-w-[1200px] px-4 py-20 sm:px-6">
          <h2 id="loop" className="max-w-[24ch] font-display text-[26px] font-medium leading-[1.15] tracking-[-0.025em] text-fg sm:text-[32px]">
            Then keep making it better.
          </h2>
          <div className="mt-12 grid gap-10 md:grid-cols-3">
            {LOOP.map((x) => (
              <div key={x.title} className="flex flex-col gap-3 border-t-2 border-line pt-6">
                <x.icon weight="duotone" className="size-8 text-accent-text" aria-hidden />
                <h3 className="text-[16px] font-semibold text-fg">{x.title}</h3>
                <p className="text-[14px] leading-relaxed text-fg-2">{x.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section aria-labelledby="price" className="border-t border-line bg-surface/60">
        <div className="mx-auto max-w-[1200px] px-4 py-20 sm:px-6">
          <h2 id="price" className="font-display text-[26px] font-medium leading-[1.15] tracking-[-0.025em] text-fg sm:text-[32px]">
            One price per minute, in five parts.
          </h2>
          <p className="mt-4 max-w-[60ch] text-[15px] leading-relaxed text-fg-2">
            Billed per second from a prepaid balance. These are the lowest rates for each part; the calculator prices your exact setup.
          </p>
          <dl className="mt-10 grid grid-cols-2 gap-px overflow-hidden rounded-panel border border-line bg-line sm:grid-cols-3 lg:grid-cols-5">
            {PARTS.map((c) => {
              const Icon = COMPONENT_ICONS[c]!;
              return (
                <div key={c} className={cn("flex flex-col gap-3 bg-surface px-5 py-5", c === "platform" && "col-span-2 sm:col-span-1")}>
                  <dt className="flex items-center gap-2 text-[13px] text-fg-2">
                    <Icon className="size-4 text-fg-3" aria-hidden />
                    {COMPONENT_LABELS[c]}
                  </dt>
                  <dd className="text-[13px] text-fg-3">
                    {c === "nc" ? (
                      <span className="text-[18px] font-medium text-fg">Included</span>
                    ) : (
                      <>
                        {c !== "platform" && "from "}
                        <span className="font-mono text-[18px] font-medium text-fg tnum">{fromRate(c)}</span> a minute
                      </>
                    )}
                  </dd>
                </div>
              );
            })}
          </dl>
          <Button asChild variant="secondary" className="mt-8" icon={<Calculator aria-hidden />}>
            <Link to="/pricing">Open the calculator</Link>
          </Button>
        </div>
      </section>

      <section className="border-t border-line">
        <div className="mx-auto max-w-[1200px] px-4 py-16 sm:px-6">
          <div className="relative overflow-hidden rounded-feature bg-console px-6 py-12 text-console-fg sm:px-12">
            <div aria-hidden className="glow-backdrop pointer-events-none absolute inset-0 opacity-90" />
            <div className="relative flex flex-col items-start gap-6 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="flex items-center gap-2 text-[13px] text-console-fg-2">
                  <BadgeDollarSign className="size-4" aria-hidden />
                  Trial credit
                </p>
                <h2 className="mt-3 max-w-[22ch] font-display text-[24px] font-medium leading-[1.2] tracking-[-0.025em] sm:text-[30px]">
                  Your first $5 is about {TRIAL_MINUTES} minutes of calls.
                </h2>
                <p className="mt-3 max-w-[52ch] text-[14.5px] text-console-fg-2">No card needed until you add funds. Calls are billed per second from your balance.</p>
              </div>
              <Button asChild variant="primary" size="lg" icon={<UserPlus aria-hidden />}>
                <Link to="/register">Create account</Link>
              </Button>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
