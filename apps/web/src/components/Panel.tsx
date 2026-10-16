import type { ReactNode } from "react";
import { cn } from "./cn";

/** Bordered surface for a group of related content. Use only when the grouping carries meaning. */
export function Panel({
  title,
  description,
  actions,
  children,
  className,
  bodyClassName,
  as: As = "section",
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  as?: "section" | "div";
}) {
  return (
    <As className={cn("rounded-panel border border-line bg-surface shadow-panel", className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-3">
          <div className="flex flex-col gap-0.5">
            {title && <h2 className="text-[13.5px] font-semibold text-fg">{title}</h2>}
            {description && <p className="text-[12.5px] text-fg-3">{description}</p>}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn(bodyClassName ?? "p-4")}>{children}</div>
    </As>
  );
}

/** Page title row: display title, optional one-line description, actions on the right. */
export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="font-display text-[24px] font-semibold leading-tight tracking-[-0.02em] text-fg">{title}</h1>
        {description && <p className="max-w-[72ch] text-[13px] text-fg-2">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

/** Small mono label used for figure captions and key/value keys. */
export function Label({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("font-mono text-[10.5px] uppercase tracking-[0.08em] text-fg-3", className)}>{children}</span>;
}
