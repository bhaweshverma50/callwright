import { cn } from "./cn";

const BARS = [
  { x: 6, h: 6 },
  { x: 10, h: 12 },
  { x: 14, h: 16 },
  { x: 18, h: 9 },
];

/**
 * Callwright mark: four signal bars in a cobalt to violet tile (they breathe on hover), then the
 * wordmark in Unbounded.
 */
export function Logo({ compact, className, onConsole }: { compact?: boolean; className?: string; onConsole?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <span className="grad-action grid size-8 shrink-0 place-items-center rounded-[9px] shadow-[0_6px_14px_-8px_rgb(91_60_244/0.8)]">
        <svg viewBox="0 0 24 24" className="size-5" aria-hidden>
          <g className="breathe">
            {BARS.map((b) => (
              <rect key={b.x} x={b.x - 1.25} y={12 - b.h / 2} width={2.5} height={b.h} rx={1.25} fill="white" style={{ transformBox: "fill-box" }} />
            ))}
          </g>
        </svg>
      </span>
      {!compact && (
        <span className={cn("font-display text-[15px] font-semibold tracking-[-0.02em]", onConsole ? "text-console-fg" : "text-fg")}>Callwright</span>
      )}
      {compact && <span className="sr-only">Callwright</span>}
    </span>
  );
}
