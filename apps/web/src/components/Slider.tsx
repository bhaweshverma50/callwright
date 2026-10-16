import * as RSl from "@radix-ui/react-slider";
import { cn } from "./cn";

export interface SliderMark {
  value: number;
  label: string;
}

export interface SliderProps {
  id?: string;
  value: number;
  onValueChange: (value: number) => void;
  /** Fires once when a drag or key press ends (commit a value, mark the field touched). */
  onValueCommit?: (value: number) => void;
  min: number;
  max: number;
  step?: number;
  disabled?: boolean;
  /** Accessible label when no visible <label> points at the thumb. */
  "aria-label"?: string;
  "aria-describedby"?: string;
  /** Spoken value, for example "12,000 minutes". */
  valueText?: (value: number) => string;
  /** Heat ramp fill for data sliders (usage meters); cobalt to violet otherwise. */
  tone?: "action" | "heat";
  /** Labels under the track (for example Low, Medium, High), aligned with the thumb centre. */
  marks?: SliderMark[];
  className?: string;
}

const THUMB_HALF = 9;

/**
 * Where the thumb centre sits for a value: Radix keeps the 18px thumb inside the track, so the
 * centre runs from 9px at the minimum to 9px short of the end at the maximum.
 */
function thumbLeft(pct: number) {
  return `calc(${pct}% + ${THUMB_HALF - (pct / 50) * THUMB_HALF}px)`;
}

/** One-thumb slider. Arrow keys move one step, Page Up/Down ten, Home/End jump to the ends. */
export function Slider({
  id,
  value,
  onValueChange,
  onValueCommit,
  min,
  max,
  step = 1,
  disabled,
  valueText,
  tone = "action",
  marks,
  className,
  ...aria
}: SliderProps) {
  return (
    <div className={cn("flex w-full flex-col", disabled && "opacity-50", className)}>
      <RSl.Root
        className="relative flex h-6 w-full cursor-pointer touch-none select-none items-center data-[disabled]:cursor-not-allowed"
        value={[value]}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onValueChange={(v) => onValueChange(v[0] ?? min)}
        onValueCommit={onValueCommit ? (v) => onValueCommit(v[0] ?? min) : undefined}
      >
        <RSl.Track className="relative h-1.5 grow overflow-hidden rounded-full bg-surface-3">
          <RSl.Range className={cn("absolute h-full", tone === "heat" ? "grad-heat" : "grad-action")} />
        </RSl.Track>
        <RSl.Thumb
          id={id}
          aria-label={aria["aria-label"]}
          aria-describedby={aria["aria-describedby"]}
          aria-valuetext={valueText?.(value)}
          className={cn(
            "block size-[18px] rounded-full border-2 border-accent bg-surface shadow-1 transition-[transform,box-shadow] duration-150",
            "hover:scale-110 hover:shadow-[0_0_0_6px_var(--accent-soft)] focus-visible:shadow-[0_0_0_6px_var(--accent-soft)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
          )}
        />
      </RSl.Root>
      {marks && marks.length > 0 && (
        <div aria-hidden className="relative mt-1 h-4 text-[11.5px] text-fg-3">
          {marks.map((m, i) => {
            const pct = ((m.value - min) / (max - min)) * 100;
            const edge = i === 0 && pct <= 0 ? "start" : i === marks.length - 1 && pct >= 100 ? "end" : "mid";
            return (
              <span
                key={m.value}
                className={cn("absolute top-0 whitespace-nowrap", edge === "mid" && "-translate-x-1/2", edge === "end" && "-translate-x-full")}
                style={{ left: edge === "start" ? 0 : edge === "end" ? "100%" : thumbLeft(pct) }}
              >
                {m.label}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}
