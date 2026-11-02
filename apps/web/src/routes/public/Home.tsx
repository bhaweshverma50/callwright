import type { ReactNode } from "react";
import { Link } from "react-router";
import { Button, COMPONENT_ICONS, COMPONENT_LABELS, Reveal, RevealItem } from "../../components";
import { catalogV1 } from "../../lib/catalogSeed";
import { formatUsd, toMicros } from "../../lib/money";
import { providerLabel } from "../../lib/providers";
import { SEED_PER_MINUTE_MICROS, talkMinutes } from "../../lib/stack";
import { Playground } from "./playground/Playground";

const PARTS = ["stt", "llm", "tts", "nc", "platform"] as const;
type Part = (typeof PARTS)[number];

/** Lowest per-minute rate per component in the launch catalog (seed version 1). */
function fromRate(component: Part): string {
  const rates = catalogV1.entries.filter((e) => e.component === component).map((e) => toMicros(e.rate_per_min_usd) ?? 0n);
  const min = rates.reduce((a, b) => (b < a ? b : a));
  return formatUsd(min, { places: 4 });
}

const providersFor = (c: Part) => [...new Set(catalogV1.entries.filter((e) => e.component === c).map((e) => providerLabel(e.provider)))];

const TRIAL_MINUTES = talkMinutes(5_000_000n, SEED_PER_MINUTE_MICROS);

const LINKS: { c: Part; text: string }[] = [
  { c: "nc", text: "Optional. Cleans the line before anything listens to it." },
  { c: "stt", text: "Hears the caller. Pick for accuracy on your callers' accents and line quality." },
  { c: "llm", text: "Decides what to say, calls your tools and searches your documents." },
  { c: "tts", text: "Speaks the answer. Pick a voice that fits the business." },
];

const LOOP = [
  { title: "See every call", text: "Transcript, recording, per-turn latency and the itemised cost of each call, as it happens." },
  {
    title: "Score it, then check the score",
    text: "Evaluators grade calls with their reasons. Your own labels show how often each one agrees with a person.",
  },
  {
    title: "Fix what repeats",
    text: "Repeated failures become issues with a drafted prompt fix, replayed against the calls it would change before you apply it.",
  },
];

const H2 = "font-display text-[26px] font-medium leading-[1.15] tracking-[-0.025em] text-fg sm:text-[32px]";

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

/** Public home (T044, FR-016). Product visuals are real components fed by the pricing engine. */
export function Home() {
  return (
    <>
      <section>
        <div className="mx-auto grid max-w-[1200px] grid-cols-[minmax(0,1fr)] items-center gap-12 px-4 pb-20 pt-10 sm:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:pb-24 lg:pt-14">
          <Reveal>
            <RevealItem>
              <h1 className="max-w-[14ch] text-balance font-display text-[34px] font-semibold leading-[1.06] tracking-[-0.035em] text-fg sm:text-[46px] lg:text-[52px]">
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
              <Button asChild variant="primary" size="lg" idleSheen>
                <Link to="/register">Create account</Link>
              </Button>
              <Button asChild variant="link" className="text-[15px]">
                <Link to="/pricing">See pricing</Link>
              </Button>
            </RevealItem>
            <RevealItem>
              <p className="mt-6 text-[13.5px] text-fg-3">
                New workspaces start with $5.00, about <span className="font-mono text-fg-2 tnum">{TRIAL_MINUTES}</span> minutes of calls.
              </p>
            </RevealItem>
          </Reveal>
          <Playground />
        </div>
      </section>

      <Band
        id="chain"
        title="Every link in the call is yours to choose."
        intro="A call travels from the caller through speech to text, the model and the voice, and back. Swap any link in the agent settings; nothing else changes."
      >
        <ol className="divide-y divide-line border-y border-line">
          {LINKS.map((l) => {
            const Icon = COMPONENT_ICONS[l.c]!;
            return (
              <li key={l.c} className="grid grid-cols-[minmax(0,1fr)] items-start gap-x-8 gap-y-1.5 py-6 sm:grid-cols-[180px_minmax(0,1fr)]">
                <h3 className="flex items-center gap-2.5 text-[15px] font-semibold text-fg">
                  <Icon className="size-4 shrink-0 text-accent-text" aria-hidden />
                  {COMPONENT_LABELS[l.c]}
                </h3>
                <div>
                  <p className="text-[15px] leading-relaxed text-fg-2">{l.text}</p>
                  <p className="mt-1.5 text-[13.5px] text-fg-3">{providersFor(l.c).join(", ")}</p>
                </div>
              </li>
            );
          })}
        </ol>
      </Band>

      <Band id="loop" title="Then keep making it better.">
        <ul className="divide-y divide-line border-y border-line">
          {LOOP.map((x) => (
            <li key={x.title} className="grid grid-cols-[minmax(0,1fr)] items-start gap-x-8 gap-y-1.5 py-6 sm:grid-cols-[180px_minmax(0,1fr)]">
              <h3 className="text-[15px] font-semibold text-fg">{x.title}</h3>
              <p className="text-[15px] leading-relaxed text-fg-2">{x.text}</p>
            </li>
          ))}
        </ul>
      </Band>

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
              <dd className="text-right text-[13.5px] text-fg-3">
                {c === "nc" ? (
                  <span className="text-[15px] text-fg">Included</span>
                ) : (
                  <>
                    {c !== "platform" && "from "}
                    <span className="font-mono text-[16px] text-fg tnum">{fromRate(c)}</span> a minute
                  </>
                )}
              </dd>
            </div>
          ))}
        </dl>
      </Band>

      <section aria-labelledby="start">
        <div className="mx-auto max-w-[1200px] px-4 py-24 sm:px-6 lg:py-28">
          <h2
            id="start"
            className="max-w-[20ch] text-balance font-display text-[30px] font-semibold leading-[1.1] tracking-[-0.03em] text-fg sm:text-[40px]"
          >
            Your first $5 is about {TRIAL_MINUTES} minutes of calls.
          </h2>
          <p className="mt-4 max-w-[52ch] text-[16px] leading-relaxed text-fg-2">
            No card needed until you add funds. Calls are billed per second from your balance.
          </p>
          <Button asChild variant="primary" size="lg" idleSheen className="mt-8">
            <Link to="/register">Create account</Link>
          </Button>
        </div>
      </section>
    </>
  );
}
