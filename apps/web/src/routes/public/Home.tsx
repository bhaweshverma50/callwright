import type { ReactNode } from "react";
import { Link } from "react-router";
import { Button, COMPONENT_LABELS, Reveal, RevealItem, Skeleton, TalkMinutes } from "../../components";
import { formatUsd, toMicros, TRIAL_CREDIT, TRIAL_CREDIT_MICROS } from "../../lib/money";
import { ChainDemo } from "./home/ChainDemo";
import { ProductVideo } from "./home/ProductVideo";
import { ProviderStrip } from "./home/ProviderStrip";
import { QualityStory } from "./home/QualityStory";
import { TemplateRail } from "./home/TemplateRail";
import { Playground } from "./playground/Playground";
import { useCatalogEntries } from "../../api/pricing";
import type { CatalogEntry } from "../../api/types";

const PARTS = ["stt", "llm", "tts", "nc", "platform"] as const;
type Part = (typeof PARTS)[number];

/** Lowest per-minute rate per component in the catalog in effect; null until it loads. */
function fromRate(entries: CatalogEntry[], component: Part): string | null {
  const rates = entries.filter((e) => e.component === component).map((e) => toMicros(e.rate_per_min_usd) ?? 0n);
  if (!rates.length) return null;
  return formatUsd(
    rates.reduce((a, b) => (b < a ? b : a)),
    { places: 4 },
  );
}

/** Trial credit a new workspace starts with (the API grants it on sign-up; not served before then). */

const H2 = "font-display text-[26px] leading-[1.15] tracking-[-0.025em] text-fg sm:text-[32px]";

/** A titled band: heading and intro on the left, the content as ruled rows on the right. */
function Band({ id, title, intro, children }: { id: string; title: string; intro?: ReactNode; children: ReactNode }) {
  return (
    <section aria-labelledby={id}>
      <div className="mx-auto grid max-w-[1200px] grid-cols-[minmax(0,1fr)] gap-x-16 gap-y-10 px-4 py-14 sm:px-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:py-20">
        <div>
          <h2 id={id} className={`${H2} max-w-[18ch]`}>
            {title}
          </h2>
          {intro && <div className="mt-4 max-w-[44ch] text-[15px] leading-relaxed text-fg-2">{intro}</div>}
        </div>
        <div>{children}</div>
      </div>
    </section>
  );
}

/** A titled section with the content full width under the heading. */
function Stacked({ id, title, intro, children }: { id: string; title: string; intro?: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id}>
      <div className="mx-auto max-w-[1200px] px-4 py-14 sm:px-6 lg:py-20">
        <h2 id={id} className={`${H2} max-w-[22ch]`}>
          {title}
        </h2>
        {intro && <p className="mt-4 max-w-[60ch] text-[15px] leading-relaxed text-fg-2">{intro}</p>}
        <div className="mt-12">{children}</div>
      </div>
    </section>
  );
}

/** Public home (T044, FR-016). Product visuals are real components fed by the pricing engine. */
export function Home() {
  const entries = useCatalogEntries();
  return (
    <>
      <section>
        <div className="mx-auto grid max-w-[1200px] grid-cols-[minmax(0,1fr)] items-center gap-12 px-4 pb-20 pt-10 sm:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:pb-24 lg:pt-14">
          <Reveal>
            <RevealItem>
              <h1 className="max-w-[14ch] text-balance font-display text-[34px] leading-[1.06] tracking-[-0.035em] text-fg sm:text-[46px] lg:text-[52px]">
                Phone agents fast enough that callers keep talking.
              </h1>
            </RevealItem>
            <RevealItem>
              <p className="mt-6 max-w-[46ch] text-[16px] leading-relaxed text-fg-2">
                Choose the speech recognition, model and voice. Callwright runs the call, times every turn and prices every second, so you can see why
                a caller stayed or hung up.
              </p>
            </RevealItem>
            <RevealItem className="mt-9 flex flex-wrap items-center gap-x-6 gap-y-4">
              <Button asChild variant="primary" size="lg">
                <Link to="/register">Create account</Link>
              </Button>
              <Button asChild variant="link" className="text-[15px]">
                <Link to="/pricing">See pricing</Link>
              </Button>
            </RevealItem>
            <RevealItem>
              <p className="mt-6 text-[14px] text-fg-3">
                New workspaces start with {TRIAL_CREDIT}, about{" "}
                <span className="font-mono text-fg-2 tnum">
                  <TalkMinutes micros={TRIAL_CREDIT_MICROS} />
                </span>{" "}
                minutes of calls.
              </p>
            </RevealItem>
          </Reveal>
          <Playground />
        </div>
      </section>

      <ProviderStrip />

      <Stacked
        id="chain"
        title="Every link in the call is yours to choose."
        intro="A call travels from the caller through speech to text, the model and the voice, and back. Swap any link in the agent settings; nothing else changes."
      >
        <ChainDemo />
      </Stacked>

      <Stacked
        id="tour"
        title="Build it, call it, read the call."
        intro="Thirty seconds of the real app: write an agent, talk to it from the browser, then open the call to see every turn timed and every second priced."
      >
        <ProductVideo />
      </Stacked>

      <Stacked id="loop" title="Then fix what keeps failing.">
        <QualityStory />
      </Stacked>

      <section aria-labelledby="templates" className="py-14 lg:py-20">
        <TemplateRail />
      </section>

      <Band
        id="price"
        title="One price per minute, in five parts."
        intro={
          <>
            <p>Billed per second from a prepaid balance. These are the lowest rates for each part; the calculator prices your exact setup.</p>
            <Button asChild variant="link" className="mt-5 text-[15px]">
              <Link to="/pricing">Open the calculator</Link>
            </Button>
          </>
        }
      >
        <dl className="divide-y divide-line border-y border-line">
          {PARTS.map((c) => (
            <div key={c} className="flex items-baseline justify-between gap-6 py-4">
              <dt className="text-[15px] text-fg">{COMPONENT_LABELS[c]}</dt>
              <dd className="text-right text-[14px] text-fg-3">
                {c === "nc" ? (
                  <span className="text-[15px] text-fg">Included</span>
                ) : (
                  <>
                    {c !== "platform" && "from "}
                    <span className="font-mono text-[16px] text-fg tnum">
                      {fromRate(entries, c) ?? <Skeleton className="inline-block h-[1em] w-[7ch] align-middle" />}
                    </span>{" "}
                    a minute
                  </>
                )}
              </dd>
            </div>
          ))}
        </dl>
      </Band>

      <section aria-labelledby="start">
        <div className="mx-auto max-w-[1200px] px-4 py-24 sm:px-6 lg:py-28">
          <h2 id="start" className="max-w-[20ch] text-balance font-display text-[30px] leading-[1.1] tracking-[-0.03em] text-fg sm:text-[40px]">
            Your first {formatUsd(TRIAL_CREDIT_MICROS, { places: 0 })} is about <TalkMinutes micros={TRIAL_CREDIT_MICROS} /> minutes of calls.
          </h2>
          <p className="mt-4 max-w-[52ch] text-[16px] leading-relaxed text-fg-2">
            No card needed until you add funds. Calls are billed per second from your balance.
          </p>
          <Button asChild variant="primary" size="lg" className="mt-8">
            <Link to="/register">Create account</Link>
          </Button>
        </div>
      </section>
    </>
  );
}
