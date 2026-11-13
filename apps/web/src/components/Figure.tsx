import type { ReactNode } from "react";
import { cn } from "./cn";
import { InfoTip } from "./TruncatedText";

/** A labelled figure in a header strip (not a card): label above, mono value below. */
export function Figure({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="text-[12px] text-fg-3">{label}</span>
      <span className="truncate font-mono text-[15px] font-semibold text-fg tnum">{children}</span>
      {hint && <span className="text-[12px] text-fg-3">{hint}</span>}
    </div>
  );
}

/** Thin stacked bar: completed, failed, cancelled out of the total. */
export function ProgressBar({
  completed,
  failed,
  cancelled = 0,
  total,
  className,
  label,
}: {
  completed: number;
  failed: number;
  cancelled?: number;
  total: number;
  className?: string;
  label?: string;
}) {
  const w = (n: number) => `${total ? (n / total) * 100 : 0}%`;
  return (
    <div
      role="progressbar"
      aria-label={label ?? "Progress"}
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={completed + failed + cancelled}
      className={cn("flex h-1.5 w-full overflow-hidden rounded-full bg-surface-3", className)}
    >
      <span className="h-full bg-success transition-[width] duration-500" style={{ width: w(completed) }} />
      <span className="h-full bg-danger transition-[width] duration-500" style={{ width: w(failed) }} />
      <span className="h-full bg-fg-3/40 transition-[width] duration-500" style={{ width: w(cancelled) }} />
    </div>
  );
}

/** Text colour for a rate change: green up, red down, quiet under a twentieth of a point. */
export function deltaTone(delta: number | null | undefined): string {
  if (delta === null || delta === undefined || Math.abs(delta) < 0.05) return "text-fg-2";
  return delta > 0 ? "text-success-text" : "text-danger-text";
}

/**
 * A row of equal fact cells (label over value) with 1px rules between them, drawn by the grid gap
 * on the line colour so the rules stay right however the cells wrap. Pass the column count for
 * each breakpoint in `className`.
 */
export function FactGrid({ children, className }: { children: ReactNode; className?: string }) {
  return <dl className={cn("grid grid-cols-1 gap-px bg-line", className)}>{children}</dl>;
}

/** One cell of a {@link FactGrid}: icon and label on top, the value under it. */
export function Fact({ icon, label, hint, children }: { icon?: ReactNode; label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-2 bg-surface px-5 py-4">
      <dt className="flex items-center gap-2 text-[13px] text-fg-3 [&_svg]:size-4">
        {icon}
        {label}
        {hint && <InfoTip label={`About ${label.toLowerCase()}`}>{hint}</InfoTip>}
      </dt>
      <dd className="min-w-0 text-[15px]">{children}</dd>
    </div>
  );
}
