import type { ReactNode } from "react";
import { cn } from "./cn";

export interface EmptyStateProps {
  icon?: ReactNode;
  title: ReactNode;
  children?: ReactNode;
  /** Primary and secondary actions. */
  actions?: ReactNode;
  /** Compact variant for inside tables and panels. */
  compact?: boolean;
  className?: string;
}

/** Says what is missing, why, and how to fill it. Left aligned so it reads like the page. */
export function EmptyState({ icon, title, children, actions, compact, className }: EmptyStateProps) {
  return (
    <div className={cn("flex flex-col items-start gap-3", compact ? "px-4 py-8" : "px-1 py-14", className)}>
      {icon && (
        <div className="grid size-9 place-items-center rounded-panel border border-line bg-surface-2 text-fg-2 [&_svg]:size-[18px]">
          {icon}
        </div>
      )}
      <div className="flex max-w-[52ch] flex-col gap-1">
        <h3 className={cn("font-display font-semibold tracking-[-0.01em] text-fg", compact ? "text-[14px]" : "text-[16px]")}>{title}</h3>
        {children && <div className="text-[13px] leading-relaxed text-fg-2">{children}</div>}
      </div>
      {actions && <div className="mt-1 flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
