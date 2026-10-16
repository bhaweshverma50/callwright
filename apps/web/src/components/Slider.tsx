import * as RSl from "@radix-ui/react-slider";
import { cn } from "./cn";

export interface SliderProps {
  id?: string;
  value: number;
  onValueChange: (value: number) => void;
  min: number;
  max: number;
  step?: number;
  disabled?: boolean;
  /** Accessible label when no visible <label> points at the thumb. */
  "aria-label"?: string;
  /** Spoken value, for example "12,000 minutes". */
  valueText?: (value: number) => string;
  /** Heat ramp fill for data sliders (usage meters); cobalt to violet otherwise. */
  tone?: "action" | "heat";
  className?: string;
}

/** One-thumb slider. Arrow keys move one step, Page Up/Down ten, Home/End jump to the ends. */
export function Slider({ id, value, onValueChange, min, max, step = 1, disabled, valueText, tone = "action", className, ...aria }: SliderProps) {
  return (
    <RSl.Root
      className={cn("relative flex h-6 w-full cursor-pointer touch-none select-none items-center", disabled && "opacity-50", className)}
      value={[value]}
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      onValueChange={(v) => onValueChange(v[0] ?? min)}
    >
      <RSl.Track className="relative h-1.5 grow overflow-hidden rounded-full bg-surface-3">
        <RSl.Range className={cn("absolute h-full", tone === "heat" ? "grad-heat" : "grad-action")} />
      </RSl.Track>
      <RSl.Thumb
        id={id}
        aria-label={aria["aria-label"]}
        aria-valuetext={valueText?.(value)}
        className={cn(
          "block size-[18px] rounded-full border-2 border-accent bg-surface shadow-1 transition-[transform,box-shadow] duration-150",
          "hover:scale-110 hover:shadow-[0_0_0_6px_var(--accent-soft)] focus-visible:shadow-[0_0_0_6px_var(--accent-soft)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        )}
      />
    </RSl.Root>
  );
}
