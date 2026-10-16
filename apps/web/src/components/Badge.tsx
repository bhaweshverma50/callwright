import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn, focusRing } from "./cn";

export type Tone = "neutral" | "accent" | "amber" | "danger" | "success";

const tones: Record<Tone, string> = {
  neutral: "bg-surface-3 text-fg-2",
  accent: "bg-accent-soft text-accent-text",
  amber: "bg-amber-soft text-amber-text",
  danger: "bg-danger-soft text-danger-text",
  success: "bg-success-soft text-success-text",
};

/** Read-only status label. Mono, small, fully rounded. */
export function Badge({ tone = "neutral", icon, children, className }: { tone?: Tone; icon?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-full px-2 font-mono text-[11px] font-medium leading-none",
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
}

/** Toggleable choice (preset amounts, filters). Uses aria-pressed so state is announced. */
export function Chip({ selected, className, children, ...rest }: ChipProps) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-full border px-3 font-mono text-[12px] tnum transition-colors",
        selected
          ? "border-accent bg-accent-soft text-accent-text"
          : "border-line-strong bg-surface text-fg-2 hover:border-fg-3 hover:text-fg",
        "disabled:cursor-not-allowed disabled:opacity-50",
        focusRing,
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

/** Keyboard key hint, for shortcuts in menus and tooltips. */
export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-[4px] border border-line-strong bg-surface-2 px-1 font-mono text-[10.5px] text-fg-2">
      {children}
    </kbd>
  );
}
