import { Link } from "react-router";
import { Button, COMPONENT_LABELS, CostBreakdownCard } from "../../components";
import { PricingCalculator } from "./PricingCalculator";
import { REFERENCE_USAGE, referenceBreakdown } from "./reference";

const PARTS: { c: keyof typeof COMPONENT_LABELS; text: string }[] = [
  { c: "stt", text: "Turns the caller's speech into text, per minute of call." },
  { c: "llm", text: "Decides what to say. Includes 20,000 input and 200 output tokens per minute." },
  { c: "tts", text: "Speaks the reply. Includes 750 characters per minute." },
  { c: "nc", text: "Optional. Cleans background noise before recognition." },
  { c: "platform", text: "Runs the call: telephony, orchestration, recording and analytics." },
];

/** Public pricing (T073, FR-013): calculator first, then how the price is built. */
export function Pricing() {
  const llm = referenceBreakdown.lines.find((l) => l.component === "llm")!;
  return (
    <div className="mx-auto max-w-[1200px] px-4 pb-24 pt-14 sm:px-6">
      <h1 className="max-w-[20ch] font-display text-[40px] font-semibold leading-[1.05] tracking-[-0.03em] text-fg">Pay per minute, billed per second.</h1>
      <p className="mt-4 max-w-[58ch] text-[15px] leading-relaxed text-fg-2">
        Pick the parts your agent uses. The price per minute is the sum of five parts, and the same engine prices your real calls.
      </p>

      <div className="mt-10">
        <PricingCalculator />
      </div>

      <section aria-labelledby="parts" className="mt-20">
        <h2 id="parts" className="font-display text-[26px] font-semibold leading-[1.15] tracking-[-0.02em] text-fg">
          What a minute is made of
        </h2>
        <dl className="mt-8 grid gap-x-8 gap-y-6 sm:grid-cols-2 lg:grid-cols-5">
          {PARTS.map((p) => (
            <div key={p.c} className="flex flex-col gap-1 border-t border-line-strong pt-4">
              <dt className="text-[14px] font-medium text-fg">{COMPONENT_LABELS[p.c]}</dt>
              <dd className="text-[13.5px] leading-relaxed text-fg-2">{p.text}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section aria-labelledby="rule" className="mt-20 grid items-start gap-10 border-t border-line pt-16 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div>
          <h2 id="rule" className="font-display text-[26px] font-semibold leading-[1.15] tracking-[-0.02em] text-fg">
            When a call uses more than its bundle
          </h2>
          <p className="mt-4 text-[14px] leading-relaxed text-fg-2">
            The model and voice parts include a usage bundle per minute. A component is billed for whichever is longer: the call
            itself, or its usage divided by the bundle. Speech recognition, noise cancellation and the platform fee never carry a
            surcharge.
          </p>
          <pre className="mt-6 overflow-x-auto rounded-control border border-line bg-surface-2 px-4 py-3 font-mono text-[12.5px] leading-relaxed text-fg">
{`billed minutes = max(call minutes, usage / bundle)
cost           = rate x billed minutes`}
          </pre>
          <p className="mt-6 text-[14px] leading-relaxed text-fg-2">
            Example: a {Math.round(REFERENCE_USAGE.duration_ms / 1000)} second call sent {REFERENCE_USAGE.llm_input_tokens.toLocaleString()} input
            tokens to the model. That is {Number(llm.billed_minutes).toFixed(2)} minutes of bundle on a{" "}
            {Number(referenceBreakdown.duration_minutes).toFixed(2)} minute call, so the model line bills at{" "}
            {Number(llm.bundle_multiplier).toFixed(2)}x. The voice stayed inside its bundle and bills at the call length.
          </p>
          <Button asChild variant="secondary" className="mt-6">
            <Link to="/enterprise">Talk to us about volume</Link>
          </Button>
        </div>
        <CostBreakdownCard breakdown={referenceBreakdown} title="Worked example" />
      </section>
    </div>
  );
}
