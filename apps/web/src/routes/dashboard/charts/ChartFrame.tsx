import type { ReactNode } from "react";
import { cn } from "../../../components";

/**
 * Chart tokens. Categorical slots for the four channels, validated with the dataviz palette
 * check (light on #FFFFFF, dark on #161A42: lightness band, chroma, CVD and contrast all pass).
 * Single-series charts use the accent; status uses the semantic colours.
 */
export const chartVars =
  "[--ch-1:#3346E8] [--ch-2:#E0457B] [--ch-3:#C47A0A] [--ch-4:#14A38B] dark:[--ch-1:#6E7DFF] dark:[--ch-4:#1E9E84] [--series:#3346E8] dark:[--series:#7E8BFF]";

export const axisTick = { fill: "var(--text-3)", fontSize: 11, fontFamily: "Geist Mono Variable, ui-monospace, monospace" };

/** A titled chart card: what it shows on the left, a figure or control on the right. */
export function ChartCard({
  title,
  description,
  aside,
  children,
  className,
  bodyClassName,
}: {
  title: string;
  description?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section aria-label={title} className={cn("flex min-w-0 flex-col rounded-panel border border-line bg-surface shadow-1", className)}>
      <header className="flex items-start justify-between gap-4 px-5 pb-1 pt-4">
        <div className="min-w-0">
          <h2 className="text-[14px] font-semibold text-fg">{title}</h2>
          {description && <p className="mt-0.5 text-[13px] text-fg-3">{description}</p>}
        </div>
        {aside}
      </header>
      <div className={cn("min-w-0 flex-1 px-5 pb-5 pt-3", bodyClassName)}>{children}</div>
    </section>
  );
}

/** Tooltip card shared by every chart (the app's tooltip look). */
export function ChartTooltip({ title, rows }: { title: ReactNode; rows: { label: ReactNode; value: ReactNode; color?: string }[] }) {
  return (
    <div className="min-w-[140px] rounded-control border border-[var(--tooltip-edge)] bg-[var(--tooltip-bg)] px-3 py-2 text-[12px] text-[var(--tooltip-fg)] shadow-pop">
      <p className="mb-1 font-medium">{title}</p>
      {rows.map((r, i) => (
        <p key={i} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 opacity-85">
            {r.color && <span className="size-2 rounded-full" style={{ background: r.color }} aria-hidden />}
            {r.label}
          </span>
          <span className="font-mono tnum">{r.value}</span>
        </p>
      ))}
    </div>
  );
}

const dayFmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", timeZone: "UTC" });
/** Bucket starts are calendar dates; format them as dates, never shifted by the viewer's zone. */
export const bucketLabel = (iso: string) => dayFmt.format(new Date(`${iso}T00:00:00Z`));
