/**
 * Signal chain visuals (docs/DESIGN.md sections 1 and 6): the waveform, the chain of links a call
 * travels through, per-turn latency chips and the on-air indicator. Heat ramp colours appear only
 * here, inside data visualisation.
 */
import { useReducedMotion } from "motion/react";
import { useId, useMemo, type ReactNode } from "react";
import { cn } from "./cn";

/** Deterministic pseudo-random bar heights (0.15 to 1) so a waveform looks like speech. */
export function waveHeights(count: number, seed = 7): number[] {
  let s = seed;
  const rand = () => {
    s = (s * 9301 + 49297) % 233280;
    return s / 233280;
  };
  return Array.from({ length: count }, (_, i) => {
    const envelope = 0.45 + 0.55 * Math.abs(Math.sin((i / count) * Math.PI * 3.2 + seed));
    return Math.max(0.15, Math.min(1, envelope * (0.35 + rand() * 0.75)));
  });
}

export interface WaveformProps {
  bars?: number;
  seed?: number;
  /** Share of bars (0 to 1) drawn in the heat ramp; the rest in the quiet line colour. */
  progress?: number;
  /** Bars move like live audio. Off under reduced motion. */
  live?: boolean;
  /** Draws on the dark console surface. */
  onConsole?: boolean;
  className?: string;
  height?: number;
  /** Silence: every bar at the floor (the not-found view). */
  flat?: boolean;
}

/** Voice waveform as SVG bars, scaled with transforms so animation stays on the compositor. */
export function Waveform({ bars = 64, seed = 7, progress = 1, live = false, onConsole, className, height = 64, flat = false }: WaveformProps) {
  const id = useId().replace(/:/g, "");
  const reduce = useReducedMotion();
  const heights = useMemo(() => (flat ? Array.from({ length: bars }, () => 0.05) : waveHeights(bars, seed)), [bars, seed, flat]);
  const gap = 2;
  const w = 3;
  const width = bars * (w + gap) - gap;
  const playedUntil = Math.round(progress * bars);
  const animateBars = live && !reduce;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className={cn("block w-full", className)} style={{ height }} aria-hidden>
      <defs>
        <linearGradient id={`heat-${id}`} x1="0" x2={width} y1="0" y2="0" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="var(--heat-1)" />
          <stop offset="0.55" stopColor="var(--heat-2)" />
          <stop offset="1" stopColor="var(--heat-3)" />
        </linearGradient>
      </defs>
      {heights.map((h, i) => {
        const barH = Math.max(3, h * height);
        const played = i < playedUntil;
        return (
          <rect
            key={i}
            x={i * (w + gap)}
            y={(height - barH) / 2}
            width={w}
            height={barH}
            rx={1.5}
            fill={played ? `url(#heat-${id})` : onConsole ? "var(--console-line)" : "var(--border-strong)"}
            style={
              animateBars
                ? {
                    transformBox: "fill-box",
                    transformOrigin: "center",
                    animation: `bar-breathe ${700 + ((i * 137) % 600)}ms ease-in-out ${(i * 53) % 400}ms infinite`,
                  }
                : undefined
            }
          />
        );
      })}
    </svg>
  );
}

/** Pulsing on-air dot. Red is reserved for live and recording state. */
export function OnAir({ label = "Live", className, onConsole }: { label?: ReactNode; className?: string; onConsole?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2 text-[12.5px] font-medium", onConsole ? "text-console-fg" : "text-fg", className)}>
      <span className="relative grid size-2.5 place-items-center" aria-hidden>
        <span className="absolute inset-0 rounded-full bg-on-air animate-on-air" />
        <span className="relative size-2.5 rounded-full bg-on-air" />
      </span>
      {label}
    </span>
  );
}

export interface Latency {
  stt: number;
  llm: number;
  tts: number;
}

/**
 * Per-turn latency: the total in Geist Mono and a bar split by chain link (speech to text, model,
 * voice) in the heat ramp, so the slow link is visible at a glance.
 */
export function LatencyChip({ latency, onConsole, className }: { latency: Latency; onConsole?: boolean; className?: string }) {
  const total = latency.stt + latency.llm + latency.tts;
  const parts: [keyof Latency, string][] = [
    ["stt", "var(--heat-1)"],
    ["llm", "var(--heat-2)"],
    ["tts", "var(--heat-3)"],
  ];
  return (
    <span
      role="img"
      aria-label={`Answered in ${total} milliseconds: speech to text ${latency.stt}, model ${latency.llm}, voice ${latency.tts}`}
      className={cn(
        "inline-flex h-6 items-center gap-2 rounded-full border px-2",
        onConsole ? "border-console-line bg-console-2 text-console-fg" : "border-line bg-surface text-fg",
        className,
      )}
    >
      <span className="flex h-1.5 w-12 overflow-hidden rounded-full" aria-hidden>
        {parts.map(([k, c]) => (
          <span key={k} style={{ width: `${(latency[k] / total) * 100}%`, background: c }} />
        ))}
      </span>
      <span className="font-mono text-[11.5px] tnum">{total} ms</span>
    </span>
  );
}

/** One link of the chain: a heat-ramp line with dashes flowing toward the next node. */
export function ChainLink({ flow, onConsole, className }: { flow?: boolean; onConsole?: boolean; className?: string }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg viewBox="0 0 100 4" preserveAspectRatio="none" className={cn("h-1 w-0 min-w-4", className)} aria-hidden>
      <defs>
        <linearGradient id={`l-${id}`} x1="0" x2="100" y1="0" y2="0" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="var(--heat-1)" />
          <stop offset="0.6" stopColor="var(--heat-2)" />
          <stop offset="1" stopColor="var(--heat-3)" />
        </linearGradient>
      </defs>
      <line
        x1="0"
        x2="100"
        y1="2"
        y2="2"
        stroke={onConsole ? "var(--console-line)" : "var(--border-strong)"}
        strokeWidth="2"
        vectorEffect="non-scaling-stroke"
      />
      <line
        x1="0"
        x2="100"
        y1="2"
        y2="2"
        stroke={`url(#l-${id})`}
        strokeWidth="2"
        strokeDasharray={flow ? "6 6" : undefined}
        vectorEffect="non-scaling-stroke"
        className={flow ? "animate-flow" : undefined}
      />
    </svg>
  );
}
