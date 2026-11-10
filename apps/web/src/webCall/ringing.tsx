/**
 * Ringing while a test call waits for the agent to answer: the phone-style state between joining
 * the room and the agent's first words, a soft ringback tone, and the ringing visual.
 */
import { Phone } from "lucide-react";
import { motion } from "motion/react";
import { useEffect } from "react";
import type { WebCallState } from "./useWebCall";
import { cn } from "../components";

/** The call is placed and the agent has not answered yet (no words from either side). */
export function isRinging(s: Pick<WebCallState, "phase" | "activity" | "turns">): boolean {
  if (s.phase === "connecting") return true;
  return s.phase === "live" && s.activity === "joining" && s.turns.length === 0;
}

// ponytail: one tone, the double ring used in India and the UK (400 + 450 Hz; 0.4 s on, 0.2 off,
// 0.4 on, 2 s off). A per-country tone can come from the agent's language if callers ask for it.
const CYCLE_S = 3;
const BURSTS: [number, number][] = [
  [0, 0.4],
  [0.6, 1.0],
];
const VOLUME = 0.05;

/** Plays the ringback tone while `active`. Silent where Web Audio is missing (tests, old browsers). */
export function useRingback(active: boolean): void {
  useEffect(() => {
    if (!active) return;
    const Ctx = (globalThis as { AudioContext?: typeof AudioContext }).AudioContext;
    if (!Ctx) return;
    let ctx: AudioContext;
    try {
      ctx = new Ctx();
    } catch {
      return;
    }
    const gain = ctx.createGain();
    gain.gain.value = 0;
    gain.connect(ctx.destination);
    const oscillators = [400, 450].map((hz) => {
      const o = ctx.createOscillator();
      o.frequency.value = hz;
      o.connect(gain);
      o.start();
      return o;
    });
    // Schedule a few cycles ahead and top up, so the cadence stays exact even if timers drift.
    let next = ctx.currentTime + 0.05;
    const schedule = () => {
      while (next < ctx.currentTime + CYCLE_S * 2) {
        for (const [on, off] of BURSTS) {
          gain.gain.setTargetAtTime(VOLUME, next + on, 0.01);
          gain.gain.setTargetAtTime(0, next + off, 0.01);
        }
        next += CYCLE_S;
      }
    };
    schedule();
    const timer = setInterval(schedule, 1000);
    return () => {
      clearInterval(timer);
      gain.gain.cancelScheduledValues(ctx.currentTime);
      gain.gain.setValueAtTime(0, ctx.currentTime);
      for (const o of oscillators) o.stop();
      void ctx.close().catch(() => {});
    };
  }, [active]);
}

/** A phone with rings spreading from it, in step with the ringback cadence. */
export function RingingPhone({ reduce, onConsole = false, className }: { reduce: boolean; onConsole?: boolean; className?: string }) {
  return (
    <div className={cn("relative grid size-24 place-items-center", className)} aria-hidden>
      {!reduce &&
        [0, 0.6].map((delay) => (
          <motion.span
            key={delay}
            className={cn("absolute inset-0 rounded-full border-2", onConsole ? "border-console-fg/40" : "border-accent/40")}
            initial={{ scale: 0.55, opacity: 0 }}
            animate={{ scale: [0.55, 1.15], opacity: [0.9, 0] }}
            transition={{ duration: 1.4, delay, repeat: Infinity, repeatDelay: CYCLE_S - 1.4, ease: "easeOut" }}
          />
        ))}
      <motion.span
        className={cn(
          "grid size-14 place-items-center rounded-full shadow-2",
          onConsole ? "bg-console-2 text-console-fg" : "bg-accent text-accent-fg",
        )}
        animate={reduce ? undefined : { rotate: [0, -14, 12, -10, 8, 0, 0, -14, 12, -10, 8, 0, 0] }}
        transition={
          reduce ? undefined : { duration: CYCLE_S, times: [0, 0.03, 0.06, 0.09, 0.12, 0.14, 0.2, 0.23, 0.26, 0.29, 0.32, 0.34, 1], repeat: Infinity }
        }
      >
        <Phone className="size-6" />
      </motion.span>
    </div>
  );
}
