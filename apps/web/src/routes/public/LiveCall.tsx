import { BrainCircuit, Captions, CircleCheck, Ear, Mic, RotateCcw, Volume2 } from "lucide-react";
import { motion, useInView, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { FlowChain, LatencyChip, OnAir, Tooltip, Waveform, cn, focusRing, type FlowNode } from "../../components";
import { formatUsd } from "../../lib/money";
import { SAMPLE_CALL, SAMPLE_CALL_SECONDS } from "../../lib/sampleCall";
import { SEED_PER_MINUTE_MICROS } from "../../lib/stack";

const NODES: FlowNode[] = [
  { key: "caller", label: "Caller", icon: <Mic aria-hidden /> },
  { key: "stt", label: "Speech to text", icon: <Captions aria-hidden /> },
  { key: "llm", label: "Model", icon: <BrainCircuit aria-hidden /> },
  { key: "tts", label: "Voice", icon: <Volume2 aria-hidden /> },
  { key: "hears", label: "Caller hears", icon: <Ear aria-hidden /> },
];

/** Which link of the chain is working at time t (seconds). Processing is stretched to be seen. */
function activeLink(t: number): string | null {
  for (const turn of SAMPLE_CALL) {
    if (turn.who !== "agent") continue;
    const start = turn.at - 1.2;
    if (t >= start && t < turn.at) {
      const p = (t - start) / 1.2;
      return p < 0.3 ? "stt" : p < 0.75 ? "llm" : "tts";
    }
    if (t >= turn.at && t < turn.at + 2.4) return "hears";
  }
  return t < SAMPLE_CALL_SECONDS ? "caller" : null;
}

const mss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/**
 * Home hero signature moment (docs/DESIGN.md section 6): one live call plays out once. Turns
 * appear over the waveform, agent turns carry a latency chip split by chain link, the cost ticker
 * runs at the default stack's per-minute price, and the chain lights the link that is working.
 * Under reduced motion it shows the finished call.
 */
export function LiveCall({ className }: { className?: string }) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.4 });
  const [t, setT] = useState(reduce ? SAMPLE_CALL_SECONDS : 0);
  const [run, setRun] = useState(0);

  useEffect(() => {
    if (reduce) {
      setT(SAMPLE_CALL_SECONDS);
      return;
    }
    if (!inView) return;
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const next = Math.min(SAMPLE_CALL_SECONDS, (now - start) / 1000);
      setT(next);
      if (next < SAMPLE_CALL_SECONDS) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [inView, reduce, run]);

  const ended = t >= SAMPLE_CALL_SECONDS;
  const costMicros = (SEED_PER_MINUTE_MICROS * BigInt(Math.round(t * 1000))) / 60_000n;
  const link = ended ? null : activeLink(t);

  return (
    <div ref={ref} className={cn("relative", className)}>
      <figure
        aria-label="Sample call: a dental front desk agent moves an appointment"
        className="relative overflow-hidden rounded-feature border border-console-line bg-console text-console-fg shadow-2"
      >
        <header className="flex items-center justify-between gap-4 border-b border-console-line px-5 py-2.5">
          {ended ? (
            <span className="inline-flex items-center gap-2 text-[13px] font-medium text-console-fg-2">
              <CircleCheck className="size-4 text-[#5fd3a4]" aria-hidden />
              Call ended
            </span>
          ) : (
            <OnAir label="Live call" onConsole />
          )}
          <div className="flex items-center gap-3">
            <dl className="flex items-center gap-4 text-[12px] text-console-fg-2">
              <div className="flex items-center gap-1.5">
                <dt className="sr-only">Duration</dt>
                <dd className="w-9 text-right font-mono text-console-fg tnum">{mss(t)}</dd>
              </div>
              <div className="flex items-center gap-1.5">
                <dt>Cost so far</dt>
                <dd className="w-[62px] text-right font-mono text-console-fg tnum">{formatUsd(costMicros, { places: 4 })}</dd>
              </div>
            </dl>
            <Tooltip content="Replay the call" side="bottom" enabled={ended && !reduce}>
              <button
                type="button"
                onClick={() => {
                  setT(0);
                  setRun((r) => r + 1);
                }}
                disabled={!ended || Boolean(reduce)}
                aria-label="Replay the call"
                className={cn(
                  "grid size-8 shrink-0 cursor-pointer place-items-center rounded-full border border-console-line text-console-fg-2 transition-[opacity,color,border-color] hover:border-[#8b97ff] hover:text-console-fg disabled:pointer-events-none disabled:opacity-0",
                  focusRing,
                )}
              >
                <RotateCcw className="size-4" aria-hidden />
              </button>
            </Tooltip>
          </div>
        </header>

        <div className="px-5 pt-3">
          <Waveform bars={72} seed={11} progress={t / SAMPLE_CALL_SECONDS} live={!ended} onConsole height={30} />
        </div>

        <ol className="flex flex-col gap-2 px-5 py-3" aria-live="off">
          {SAMPLE_CALL.map((turn, i) => {
            const shown = t >= turn.at;
            return (
              <motion.li
                key={`${run}-${i}`}
                initial={false}
                animate={shown ? { opacity: 1, y: 0 } : { opacity: 0, y: 6 }}
                transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
                className={cn("flex flex-col gap-1", turn.who === "agent" ? "items-end text-right" : "items-start")}
                aria-hidden={!shown}
              >
                <span className="text-[12px] font-medium text-console-fg-2">{turn.who === "agent" ? "Agent" : "Caller"}</span>
                <p
                  className={cn(
                    "max-w-[36ch] rounded-panel px-3 py-1.5 text-[13px] leading-snug",
                    turn.who === "agent" ? "rounded-br-[4px] bg-[#2a33a8] text-white" : "rounded-bl-[4px] bg-console-2 text-console-fg",
                  )}
                >
                  {turn.text}
                </p>
                {turn.latency && <LatencyChip latency={turn.latency} onConsole />}
              </motion.li>
            );
          })}
        </ol>

        <footer className="border-t border-console-line px-5 pb-3 pt-3.5">
          <FlowChain nodes={NODES} active={link} flow={!ended} onConsole size="sm" stack="never" />
        </footer>
      </figure>
    </div>
  );
}
