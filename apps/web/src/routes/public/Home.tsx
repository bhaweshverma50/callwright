import { ArrowRight, Crosshair, Wrench } from "@phosphor-icons/react";
import { Link } from "react-router";
import { Button, COMPONENT_LABELS, CostBreakdownCard } from "../../components";
import { formatUsd, toMicros } from "../../lib/money";
import { providerLabel } from "../../lib/providers";
import { catalogV1 } from "../../lib/catalogSeed";
import { referenceBreakdown } from "./reference";

const PARTS = ["stt", "llm", "tts", "nc", "platform"] as const;

/** Lowest per-minute rate per component in the launch catalog (seed version 1). */
function fromRate(component: (typeof PARTS)[number]): string {
  const rates = catalogV1.entries.filter((e) => e.component === component).map((e) => toMicros(e.rate_per_min_usd) ?? 0n);
  const min = rates.reduce((a, b) => (b < a ? b : a));
  return formatUsd(min, { places: 4 });
}

const providers = [...new Set(catalogV1.entries.filter((e) => e.component !== "platform").map((e) => e.provider))];

/** Public home (T044, FR-016). Product visuals are real components fed by the pricing engine. */
export function Home() {
  return (
    <>
      <section className="mx-auto grid max-w-[1200px] items-center gap-12 px-4 pb-20 pt-16 sm:px-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:pt-24">
        <div className="animate-pop-in">
          <h1 className="max-w-[16ch] font-display text-[40px] font-semibold leading-[1.05] tracking-[-0.035em] text-fg md:text-[56px]">
            Voice agents you can price, measure and fix.
          </h1>
          <p className="mt-5 max-w-[46ch] text-[16px] leading-relaxed text-fg-2">
            Build an agent on the speech, model and voice you choose, put it on a phone line, and see what every call cost and why.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Button asChild variant="primary" size="lg">
              <Link to="/register">
                Create account <ArrowRight aria-hidden />
              </Link>
            </Button>
            <Button asChild variant="secondary" size="lg">
              <Link to="/pricing">See pricing</Link>
            </Button>
          </div>
        </div>
        <div className="relative lg:pl-6">
          <div aria-hidden className="absolute -inset-6 -z-0 rounded-[18px] bg-surface-2 [background-image:radial-gradient(var(--border)_1px,transparent_1px)] [background-size:18px_18px]" />
          <CostBreakdownCard breakdown={referenceBreakdown} title="Support call, 4 min 31 s" className="relative shadow-pop" />
        </div>
      </section>

      <section aria-labelledby="loop" className="border-t border-line bg-surface-2/60">
        <div className="mx-auto max-w-[1200px] px-4 py-20 sm:px-6">
          <h2 id="loop" className="max-w-[24ch] font-display text-[30px] font-semibold leading-[1.1] tracking-[-0.025em] text-fg">
            Ship an agent, then keep making it better.
          </h2>
          <div className="mt-10 grid gap-4 md:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] md:grid-rows-2">
            <article className="relative overflow-hidden rounded-panel border border-line bg-surface p-7 md:row-span-2">
              <h3 className="font-display text-[20px] font-semibold tracking-[-0.015em] text-fg">Any vendor, one agent</h3>
              <p className="mt-2 max-w-[44ch] text-[14px] leading-relaxed text-fg-2">
                Speech recognition, language model, voice and noise cancellation each sit behind an adapter. Switch a vendor in the
                agent settings; nothing else changes.
              </p>
              <ul className="mt-8 flex flex-wrap gap-2" aria-label="Supported providers">
                {providers.map((p) => (
                  <li key={p} className="rounded-full border border-line-strong bg-surface-2 px-3 py-1 font-mono text-[12px] text-fg-2">
                    {providerLabel(p)}
                  </li>
                ))}
              </ul>
            </article>
            <article className="rounded-panel border border-accent/25 bg-accent-soft p-6">
              <Crosshair className="size-5 text-accent-text" aria-hidden />
              <h3 className="mt-3 font-display text-[17px] font-semibold tracking-[-0.01em] text-fg">Scores you can trust</h3>
              <p className="mt-1.5 text-[13.5px] leading-relaxed text-fg-2">
                Evaluators grade every call with their reasoning. Your own labels show how often each one agrees with a person.
              </p>
            </article>
            <article className="rounded-panel border border-amber/30 bg-amber-soft p-6">
              <Wrench className="size-5 text-amber-text" aria-hidden />
              <h3 className="mt-3 font-display text-[17px] font-semibold tracking-[-0.01em] text-fg">Fixes that are tested first</h3>
              <p className="mt-1.5 text-[13.5px] leading-relaxed text-fg-2">
                Repeated failures become issues with a drafted prompt fix, replayed against the calls it would change before you apply it.
              </p>
            </article>
          </div>
        </div>
      </section>

      <section aria-labelledby="price" className="border-t border-line">
        <div className="mx-auto max-w-[1200px] px-4 py-20 sm:px-6">
          <h2 id="price" className="font-display text-[30px] font-semibold leading-[1.1] tracking-[-0.025em] text-fg">
            One price per minute, in five parts.
          </h2>
          <p className="mt-3 max-w-[60ch] text-[14px] leading-relaxed text-fg-2">
            Billed per second from a prepaid balance. Rates below are the lowest in each part; the calculator prices your exact setup.
          </p>
          <dl className="mt-10 grid grid-cols-2 gap-px overflow-hidden rounded-panel border border-line bg-line sm:grid-cols-5">
            {PARTS.map((c) => (
              <div key={c} className="flex flex-col gap-2 bg-surface px-5 py-5">
                <dt className="text-[12.5px] text-fg-3">{COMPONENT_LABELS[c]}</dt>
                <dd className="font-mono text-[20px] font-medium text-fg tnum">
                  {c === "platform" ? "" : c === "nc" ? "" : "from "}
                  {fromRate(c)}
                  <span className="text-[12px] text-fg-3">/min</span>
                </dd>
              </div>
            ))}
          </dl>
          <Link to="/pricing" className="mt-6 inline-flex items-center gap-1.5 text-[14px] font-medium text-accent-text underline-offset-4 hover:underline">
            Open the calculator <ArrowRight aria-hidden className="size-4" />
          </Link>
        </div>
      </section>

      <section className="border-t border-line bg-surface-2">
        <div className="mx-auto flex max-w-[1200px] flex-col items-start gap-6 px-4 py-16 sm:px-6 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="font-display text-[28px] font-semibold tracking-[-0.025em] text-fg">Your first $5 of calls is on us.</h2>
            <p className="mt-2 text-[14px] text-fg-2">Every new workspace starts with trial credit. Add funds when you are ready.</p>
          </div>
          <Button asChild variant="primary" size="lg">
            <Link to="/register">Create account</Link>
          </Button>
        </div>
      </section>
    </>
  );
}
