import { Building, Clock } from "lucide-react";
import { Link } from "react-router";
import { Button, COMPONENT_ICONS, COMPONENT_LABELS, CostBreakdownCard } from "../../components";
import { SEED_PER_MINUTE_MICROS, talkMinutes } from "../../lib/stack";
import { PricingCalculator } from "./PricingCalculator";
import { REFERENCE_USAGE, referenceBreakdown } from "./reference";

const PARTS: { c: keyof typeof COMPONENT_LABELS; text: string }[] = [
  { c: "stt", text: "Turns the caller's speech into text, per minute of call." },
  { c: "llm", text: "Decides what to say. Includes 20,000 input and 200 output tokens per minute." },
  { c: "tts", text: "Speaks the reply. Includes 750 characters per minute." },
  { c: "nc", text: "Optional. Cleans background noise before speech to text hears it." },
  { c: "platform", text: "Runs the call: telephony, orchestration, recording and analytics." },
];

/** Public pricing (T073, FR-013): the chain calculator first, then how the price is built. */
export function Pricing() {
  const llm = referenceBreakdown.lines.find((l) => l.component === "llm")!;
  return (
    <div className="mx-auto max-w-[1200px] px-4 pb-24 pt-12 sm:px-6 lg:pt-16">
      <h1 className="grad-text max-w-[18ch] font-display text-[32px] font-semibold leading-[1.08] tracking-[-0.03em] sm:text-[44px]">
        Pay per minute, billed per second.
      </h1>
      <p className="mt-5 max-w-[60ch] text-[16px] leading-relaxed text-fg-2">
        Build the chain your agent uses. The price per minute is the sum of its links plus the platform fee, and the same engine prices
        your real calls.
      </p>
      <p className="mt-3 flex items-center gap-2 text-[13.5px] text-fg-3">
        <Clock className="size-4" aria-hidden />
        $5.00 of trial credit is about <span className="font-mono text-fg-2 tnum">{talkMinutes(5_000_000n, SEED_PER_MINUTE_MICROS)}</span> minutes on the default chain.
      </p>

      <div className="mt-12">
        <PricingCalculator />
      </div>

      <section aria-labelledby="parts" className="mt-24">
        <h2 id="parts" className="font-display text-[24px] font-medium leading-[1.15] tracking-[-0.02em] text-fg sm:text-[28px]">
          What a minute is made of
        </h2>
        <dl className="mt-8 grid gap-x-8 gap-y-8 sm:grid-cols-2 lg:grid-cols-5">
          {PARTS.map((p) => {
            const Icon = COMPONENT_ICONS[p.c]!;
            return (
              <div key={p.c} className="flex flex-col gap-2 border-t-2 border-line pt-5">
                <dt className="flex items-center gap-2 text-[14.5px] font-semibold text-fg">
                  <Icon className="size-4 text-accent-text" aria-hidden />
                  {COMPONENT_LABELS[p.c]}
                </dt>
                <dd className="text-[14px] leading-relaxed text-fg-2">{p.text}</dd>
              </div>
            );
          })}
        </dl>
      </section>

      <section aria-labelledby="rule" className="mt-24 grid items-start gap-12 border-t border-line pt-16 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div>
          <h2 id="rule" className="font-display text-[24px] font-medium leading-[1.15] tracking-[-0.02em] text-fg sm:text-[28px]">
            When a call uses more than its bundle
          </h2>
          <p className="mt-5 text-[15px] leading-relaxed text-fg-2">
            The model and voice include a usage bundle per minute. Each is billed for whichever is longer: the call itself, or its usage
            divided by the bundle. Speech to text, noise cancellation and the platform fee never carry a surcharge.
          </p>
          <pre className="mt-6 overflow-x-auto rounded-panel border border-line bg-surface px-4 py-3.5 font-mono text-[12.5px] leading-relaxed text-fg">
{`billed minutes = max(call minutes, usage / bundle)
cost           = rate x billed minutes`}
          </pre>
          <p className="mt-6 text-[15px] leading-relaxed text-fg-2">
            Example: a <span className="font-mono tnum">{Math.round(REFERENCE_USAGE.duration_ms / 1000)}</span> second call sent{" "}
            <span className="font-mono tnum">{REFERENCE_USAGE.llm_input_tokens.toLocaleString()}</span> input tokens to the model. That is{" "}
            <span className="font-mono tnum">{Number(llm.billed_minutes).toFixed(2)}</span> minutes of bundle on a{" "}
            <span className="font-mono tnum">{Number(referenceBreakdown.duration_minutes).toFixed(2)}</span> minute call, so the model line bills
            at <span className="font-mono tnum">{Number(llm.bundle_multiplier).toFixed(2)}x</span> and adds{" "}
            <span className="font-mono tnum">${Number(llm.surcharge_usd).toFixed(4)}</span>. The voice stayed inside its bundle and bills at the
            call length.
          </p>
          <Button asChild variant="secondary" className="mt-7" icon={<Building aria-hidden />}>
            <Link to="/enterprise">Talk to us about volume</Link>
          </Button>
        </div>
        <CostBreakdownCard breakdown={referenceBreakdown} title="Worked example: support call, 4 min 31 s" className="shadow-2" />
      </section>
    </div>
  );
}
