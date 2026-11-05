import type { ReactNode } from "react";
import { cn } from "./cn";

export interface EmptyStateProps {
  /** A Phosphor duotone icon (docs/DESIGN.md section 7). */
  icon?: ReactNode;
  title: ReactNode;
  children?: ReactNode;
  /** Primary and secondary actions. */
  actions?: ReactNode;
  /** Compact variant for inside lists and panels. */
  compact?: boolean;
  className?: string;
}

/** Says what is missing, why, and how to fill it. Left aligned so it reads like the page. */
export function EmptyState({ icon, title, children, actions, compact, className }: EmptyStateProps) {
  return (
    <div className={cn("flex flex-col items-start gap-3", compact ? "px-5 py-8" : "px-1 py-12", className)}>
      {icon && (
        <div
          className={cn(
            "grid place-items-center rounded-panel border border-accent/20 bg-accent-soft text-accent-text",
            compact ? "size-10 [&_svg]:size-5" : "size-12 [&_svg]:size-7",
          )}
        >
          {icon}
        </div>
      )}
      <div className="flex max-w-[56ch] flex-col gap-1">
        <h3 className={cn("font-display tracking-[-0.01em] text-fg", compact ? "text-[14px]" : "text-[17px]")}>{title}</h3>
        {children && <div className="text-[14px] leading-relaxed text-fg-2">{children}</div>}
      </div>
      {actions && <div className="mt-1 flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
