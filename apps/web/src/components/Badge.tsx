import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn, focusRing } from "./cn";
import { useRipple } from "./motion";

export type Tone = "neutral" | "accent" | "warning" | "danger" | "success";

const tones: Record<Tone, string> = {
  neutral: "bg-surface-3 text-fg-2",
  accent: "bg-accent-soft text-accent-text",
  warning: "bg-warning-soft text-warning-text",
  danger: "bg-danger-soft text-danger-text",
  success: "bg-success-soft text-success-text",
};

/** Read-only status label: sentence case, small, fully rounded, an icon when it helps. */
export function Badge({ tone = "neutral", icon, children, className }: { tone?: Tone; icon?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-[22px] items-center gap-1 whitespace-nowrap rounded-full px-2 text-[12px] font-medium leading-none [&_svg]:size-3",
        tones[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

export interface ChipProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  selected?: boolean;
  /** Figures (amounts) use mono; word labels (filters, categories) pass `mono={false}`. */
  mono?: boolean;
}

/** Toggleable choice (preset amounts, filters). Uses aria-pressed so state is announced. */
export function Chip({ selected, mono = true, className, children, onPointerDown, ...rest }: ChipProps) {
  const { onPointerDown: ripple, ripples } = useRipple();
  return (
    <button
      type="button"
      aria-pressed={selected}
      onPointerDown={(e) => {
        ripple(e);
        onPointerDown?.(e);
      }}
      className={cn(
        "relative inline-flex h-9 cursor-pointer items-center gap-1.5 overflow-hidden rounded-full border px-3.5 text-[12.5px] transition-colors duration-150 [&_svg]:size-3.5",
        mono ? "font-mono tnum" : "font-medium",
        selected ? "border-accent bg-accent-soft text-accent-text" : "border-line-strong bg-surface text-fg-2 hover:border-accent/50 hover:text-fg",
        "disabled:cursor-not-allowed disabled:opacity-50",
        focusRing,
        className,
      )}
      {...rest}
    >
      {children}
      {ripples}
    </button>
  );
}

/** Keyboard key hint, for shortcuts in menus and tooltips. */
export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-inline border border-line-strong bg-surface-2 px-1 font-mono text-[10.5px] text-fg-2">
      {children}
    </kbd>
  );
}
