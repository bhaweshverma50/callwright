import { AnimatePresence, motion, useInView, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { COMPONENT_ICONS, COMPONENT_LABELS, LatencyChip, Waveform, cn, focusRing } from "../../../components";
import { catalogV1 } from "../../../lib/catalogSeed";
import { providerLabel } from "../../../lib/providers";

type Link = "nc" | "stt" | "llm" | "tts";

const providersFor = (c: Link) => [...new Set(catalogV1.entries.filter((e) => e.component === c).map((e) => providerLabel(e.provider)))];

const LINKS: { c: Link; text: string }[] = [
  { c: "nc", text: "Optional. Cleans the line before anything listens to it." },
  { c: "stt", text: "Hears the caller. Pick for accuracy on your callers' accents and line quality." },
  { c: "llm", text: "Decides what to say, calls your tools and searches your documents." },
  { c: "tts", text: "Speaks the answer. Pick a voice that fits the business." },
];

/** Each link stays on screen this long before the demo moves on, until the visitor picks one. */
const DWELL_MS = 6500;
const EASE = [0.16, 1, 0.3, 1] as const;

const CALLER = "I've had a fever since Sunday and my throat really hurts.";

/**
 * "Every link is yours to choose", shown working: pick a link of the chain and the console plays
 * one sample turn through it. Advances on its own while in view; a click hands control to the
 * visitor. Reduced motion shows each scene's end state and never advances.
 */
export function ChainDemo() {
  const [active, setActive] = useState<Link>("stt");
  const [auto, setAuto] = useState(true);
  const reduce = useReducedMotion() ?? false;
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { amount: 0.35 });
  const running = auto && !reduce && inView;

  useEffect(() => {
    if (!running) return;
    const t = setTimeout(() => {
      const i = LINKS.findIndex((l) => l.c === active);
      setActive(LINKS[(i + 1) % LINKS.length]!.c);
    }, DWELL_MS);
    return () => clearTimeout(t);
  }, [running, active]);

  return (
    <div ref={ref} className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-10">
      <div role="tablist" aria-label="Links in the call" aria-orientation="vertical" className="flex flex-col gap-1.5">
        {LINKS.map((l) => {
          const selected = l.c === active;
          const Icon = COMPONENT_ICONS[l.c]!;
          return (
            <button
              key={l.c}
              type="button"
              role="tab"
              id={`chain-tab-${l.c}`}
              aria-selected={selected}
              aria-controls="chain-panel"
              onClick={() => {
                setAuto(false);
                setActive(l.c);
              }}
              className={cn(
                "group relative cursor-pointer rounded-panel px-4 py-4 text-left transition-colors duration-200",
                selected ? "bg-surface shadow-1" : "hover:bg-surface/60",
                focusRing,
              )}
            >
              <span className={cn("flex items-center gap-2.5 text-[15px] font-semibold", selected ? "text-fg" : "text-fg-2 group-hover:text-fg")}>
                <Icon className={cn("size-4 shrink-0", selected ? "text-accent-text" : "text-fg-3")} aria-hidden />
                {COMPONENT_LABELS[l.c]}
              </span>
              <span className={cn("mt-1 block text-[14px] leading-relaxed", selected ? "text-fg-2" : "text-fg-3")}>{l.text}</span>
              <span className={cn("mt-2 block text-[13px]", selected ? "text-fg-3" : "text-fg-3/70")}>{providersFor(l.c).join(", ")}</span>
              {selected && running && (
                <motion.span
                  key={`timer-${l.c}`}
                  aria-hidden
                  className="absolute inset-x-4 bottom-0 h-[2px] origin-left rounded-full bg-[linear-gradient(90deg,var(--heat-1),var(--heat-2),var(--heat-3))]"
                  initial={{ scaleX: 0 }}
                  animate={{ scaleX: 1 }}
                  transition={{ duration: DWELL_MS / 1000, ease: "linear" }}
                />
              )}
            </button>
          );
        })}
      </div>

      <div
        id="chain-panel"
        role="tabpanel"
        aria-labelledby={`chain-tab-${active}`}
        className="relative flex h-[420px] flex-col overflow-hidden rounded-feature border border-console-line bg-console p-6 text-console-fg shadow-2 sm:p-8"
      >
        <p className="flex items-center justify-between text-[12.5px] text-console-fg-2">
          <span>Sample turn</span>
          <span>{COMPONENT_LABELS[active]}</span>
        </p>
        <div className="relative mt-6 flex-1">
          <AnimatePresence initial={false}>
            <motion.div
              key={active}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25, ease: EASE }}
              className="absolute inset-0 flex flex-col gap-5"
            >
              {active === "nc" && <NoiseScene reduce={reduce} />}
              {active === "stt" && <SpeechScene reduce={reduce} />}
              {active === "llm" && <ModelScene reduce={reduce} />}
              {active === "tts" && <VoiceScene reduce={reduce} />}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}

/** Children fade in one after another; reduced motion shows them all at once. */
function Step({ i, reduce, children, className }: { i: number; reduce: boolean; children: ReactNode; className?: string }) {
  return (
    <motion.div
      className={className}
      initial={reduce ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: EASE, delay: i * 0.9 }}
    >
      {children}
    </motion.div>
  );
}

function Readout({ children }: { children: ReactNode }) {
  return <p className="font-mono text-[13px] text-console-fg-2 tnum">{children}</p>;
}

function NoiseScene({ reduce }: { reduce: boolean }) {
  return (
    <>
      <Step i={0} reduce={reduce} className="flex flex-col gap-2">
        <p className="text-[13px] text-console-fg-2">The caller's line, with a TV and traffic behind them</p>
        <Waveform bars={72} seed={23} progress={0} live onConsole height={40} />
      </Step>
      <Step i={1} reduce={reduce} className="flex flex-col gap-2">
        <p className="text-[13px] text-console-fg-2">What speech to text hears after noise cancellation</p>
        <Waveform bars={72} seed={5} progress={1} live onConsole height={40} />
      </Step>
      <Step i={2} reduce={reduce} className="mt-auto">
        <p className="max-w-[44ch] text-[15px] leading-relaxed">Fewer misheard words and fewer false interruptions from background voices.</p>
      </Step>
    </>
  );
}

function SpeechScene({ reduce }: { reduce: boolean }) {
  const words = CALLER.split(" ");
  return (
    <>
      <Waveform bars={72} seed={11} progress={1} live onConsole height={32} />
      <p className="max-w-[40ch] text-[20px] leading-snug" aria-label={CALLER}>
        {words.map((w, i) => (
          <motion.span
            key={i}
            aria-hidden
            initial={reduce ? false : { opacity: 0, filter: "blur(4px)" }}
            animate={{ opacity: 1, filter: "blur(0px)" }}
            transition={{ duration: 0.3, delay: 0.2 + i * 0.16 }}
          >
            {w}{" "}
          </motion.span>
        ))}
      </p>
      <Step i={2.4} reduce={reduce} className="mt-auto flex flex-wrap gap-x-6 gap-y-1">
        <Readout>Final text 180 ms after they stop</Readout>
        <Readout>96% sure</Readout>
      </Step>
    </>
  );
}

function ModelScene({ reduce }: { reduce: boolean }) {
  return (
    <>
      <Step i={0} reduce={reduce}>
        <p className="w-fit max-w-[40ch] rounded-panel rounded-br-[4px] bg-console-2 px-3 py-2 text-[14px] leading-snug">
          Can I come in tomorrow morning?
        </p>
      </Step>
      <Step i={1} reduce={reduce} className="rounded-panel border border-console-line px-4 py-3 font-mono text-[12.5px] leading-relaxed">
        <p className="text-console-fg-2">check_availability</p>
        <p>{`{ "department": "general", "day": "tomorrow" }`}</p>
        <p className="mt-1 text-[#5fd3a4]">{`["9:30", "11:15"]`}</p>
      </Step>
      <Step i={2} reduce={reduce}>
        <p className="w-fit max-w-[40ch] rounded-panel rounded-bl-[4px] bg-[#2a33a8] px-3 py-2 text-[14px] leading-snug text-white">
          I have 9:30 or 11:15 tomorrow with the general clinic. Which works for you?
        </p>
      </Step>
      <Step i={2.6} reduce={reduce} className="mt-auto">
        <Readout>First words ready in 420 ms, tool call included</Readout>
      </Step>
    </>
  );
}

function VoiceScene({ reduce }: { reduce: boolean }) {
  const voices = providersFor("tts");
  return (
    <>
      <p className="max-w-[40ch] text-[18px] leading-snug">I have 9:30 or 11:15 tomorrow with the general clinic. Which works for you?</p>
      <Step i={0.5} reduce={reduce}>
        <Waveform bars={72} seed={31} progress={1} live onConsole height={44} />
      </Step>
      <Step i={1.2} reduce={reduce} className="flex flex-wrap gap-1.5">
        {voices.map((v, i) => (
          <span
            key={v}
            className={cn(
              "rounded-full border px-3 py-1 text-[13px]",
              i === 0 ? "border-transparent bg-console-2 text-console-fg" : "border-console-line text-console-fg-2",
            )}
          >
            {v}
          </span>
        ))}
      </Step>
      <Step i={2} reduce={reduce} className="mt-auto flex flex-wrap items-center gap-x-6 gap-y-2">
        <Readout>First audio in 190 ms</Readout>
        <span className="flex items-center gap-2 text-[13px] text-console-fg-2">
          Whole reply
          <LatencyChip latency={{ stt: 180, llm: 420, tts: 190 }} onConsole />
        </span>
      </Step>
    </>
  );
}
